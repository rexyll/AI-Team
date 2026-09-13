from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from config.model import ask_ai
from runtime.context_compaction import ContextCompactor
from runtime.llm.base import BaseLLM
from runtime.llm_metrics import LLMMetrics
from runtime.plan_constraints import apply_path_constraints, extract_required_paths
from runtime.task_validator import validate_plan
from agents.base import BaseAgent
from runtime.task import Task

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
你是一名专业的软件项目规划师（Planner）。

你的职责是：
1. 理解用户的软件开发需求
2. 将需求拆分成清晰、可执行的开发任务
3. 为每个任务指定负责角色
4. 确定任务之间的依赖关系

你不能编写代码、修改文件或执行命令。

允许使用的角色：architect、developer、tester、reviewer。

用户需求中的显式约束必须逐条落实，不得省略或改写，尤其是输出目录、文件路径、命名、技术栈和阶段顺序。
与目录/路径相关的约束必须写入第一个实现类任务的 description 中。
拆解完成后必须逐条核对需求原文，确认没有遗漏显式约束。

如果提示中包含"需求分析师草案"部分：它仅供参考，不是用户原文。
草案中的任何目录/路径/技术栈信息都不得视为用户显式约束，更不得出现在你声明的
路径约束中；目录与路径约束只能来自用户原文。

角色职责：
- architect：设计结构与接口规范，不产出业务代码。
- developer：编写代码、编写测试、运行验证命令、修复问题。
- "编写单元测试"类任务属于 developer；不要给 tester 安排编写测试、执行命令或修改代码的任务。
- tester：审查 Developer 的测试证据并给出 TEST_PASSED / TEST_FAILED，不编写测试、不执行命令。
- reviewer：最终审核并判定 APPROVED / REVISION_REQUIRED；reviewer 不执行修复，发现问题应返回 developer 修复。

必须输出一个 JSON 对象：
{
  "project": "项目名称",
  "summary": "项目摘要",
  "tasks": [
    {
      "id": "TASK-001",
      "title": "任务名称",
      "description": "任务详细描述",
      "role": "architect",
      "dependencies": []
    }
  ]
}

严格规则：
1. project、summary 必须为非空字符串。
2. tasks 必须为非空数组。
3. 每个 task 必须且只能包含 id、title、description、role、dependencies。
4. task id 必须唯一。
5. role 只能是 architect、developer、tester、reviewer。
6. dependencies 必须是 task id 数组，只能引用当前计划中的任务。
7. 不允许自依赖、重复 dependency 或循环依赖。
8. 只输出 JSON，不要 Markdown、代码围栏或解释文字。
"""

MAX_PLAN_RETRIES = 2

@dataclass(frozen=True)
class PlannerAttempt:
    attempt: int
    response_length: int
    error_type: str | None
    error: str | None
    stage: str
    success: bool

def _extract_json_object(response: str) -> str:
    response = response.strip()
    if not response:
        raise ValueError("Planner 返回了空响应。")
    if response.startswith("{") and response.endswith("}"):
        return response
    if response.startswith("[") and response.endswith("]"):
        return response
    if "```" in response:
        blocks = response.split("```")
        for block in blocks:
            candidate = block.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate
    start = response.find("{")
    if start == -1:
        raise ValueError("Planner 返回内容中没有找到 JSON 对象。")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(response)):
        char = response[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return response[start:index + 1]
    raise ValueError("Planner 返回内容包含不完整的 JSON 对象。")

def _parse_plan_response(response: str) -> dict[str, Any]:
    if not isinstance(response, str) or not response.strip():
        raise ValueError("Planner 返回为空响应")
    extracted = _extract_json_object(response)
    try:
        plan = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ValueError("Planner 返回的内容不是合法 JSON。") from exc
    if not isinstance(plan, dict):
        raise ValueError("根节点必须是对象")
    validate_plan(plan)
    return plan

def _classify_validation_error(error: Exception) -> str:
    message = str(error).lower()
    if "json" in message or "对象" in message or "object" in message:
        return "format"
    if "field" in message or "role" in message or "task" in message:
        return "schema"
    if "depend" in message or "circular" in message or "cycle" in message:
        return "dependency"
    return "validation"

def _build_repair_prompt(requirement: str, invalid_response: str, error: Exception, attempt: int) -> str:
    error_kind = _classify_validation_error(error)
    bounded_response = invalid_response[:12000]
    return f"""
这是第 {attempt} 次修复生成。上一轮 Planner 输出无法通过验证。

失败类型：{error_kind}
验证错误：{error}

原始需求：
{requirement}

上一轮输出（仅供定位问题，不要原样复用）：
{bounded_response}

请针对上述具体错误重新生成完整合法计划，而不是只输出修复片段。
必须重新检查：project、summary、tasks、每个 task 的五个字段、唯一 ID、合法 role、依赖存在性、自依赖、重复依赖和循环依赖。
必须保留原始需求中的所有显式路径/目录/技术栈/顺序约束，不得省略或改写。
只输出最终 JSON Object，不要 Markdown 或解释文字。
"""

def _enforce_requirement_paths(requirement: str, plan: dict) -> dict:
    required_dirs = extract_required_paths(requirement)
    if not required_dirs:
        return plan
    injected = apply_path_constraints(plan, required_dirs)
    if injected:
        print(f"[Planner] 已将缺失的路径约束注入任务描述: {injected}")
    else:
        print(f"[Planner] 路径约束已由模型逐任务落实，无需注入: {required_dirs}")
    return plan

def create_plan(requirement: str, *, llm: BaseLLM | None = None, max_retries: int | None = None, metrics: LLMMetrics | None = None, requirement_analysis: str | None = None) -> dict:
    if llm is not None and not isinstance(llm, BaseLLM):
        raise TypeError("create_plan llm must implement BaseLLM")
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("Planner requirement cannot be empty")
    if requirement_analysis is not None and not isinstance(requirement_analysis, str):
        raise TypeError("requirement_analysis must be a string or None")
    retry_budget = MAX_PLAN_RETRIES if max_retries is None else max_retries
    if not isinstance(retry_budget, int) or retry_budget < 0:
        raise ValueError("max_retries must be a non-negative integer")
    prompt = f"请根据下面的软件需求制定开发计划：\n\n{requirement}"
    compactor = ContextCompactor()
    attempts: list[PlannerAttempt] = []
    last_error: Exception | None = None
    last_response = ""
    for attempt in range(retry_budget + 1):
        current_prompt = prompt if attempt == 0 else _build_repair_prompt(requirement, last_response, last_error or ValueError("unknown validation error"), attempt)
        bounded_prompt, bounded_system, stats = compactor.compact_prompt(current_prompt, system_prompt=SYSTEM_PROMPT)
        started = perf_counter()
        try:
            if llm is not None:
                response = llm.generate(bounded_prompt, system_prompt=bounded_system)
            else:
                response = ask_ai(prompt=bounded_prompt, system_prompt=bounded_system)
        except Exception as exc:
            if metrics is not None:
                metrics.record_llm_call(prompt_chars=stats.compacted_chars, input_tokens=stats.compacted_tokens, elapsed_seconds=perf_counter() - started)
                metrics.finish()
            attempts.append(PlannerAttempt(attempt + 1, 0, type(exc).__name__, str(exc), "generation", False))
            last_error = exc
            last_response = ""
            logger.warning("Planner attempt %d generation failed: %s", attempt + 1, exc)
            continue
        if metrics is not None:
            metrics.record_llm_call(prompt_chars=stats.compacted_chars, input_tokens=stats.compacted_tokens, elapsed_seconds=perf_counter() - started)
            metrics.finish()
        if not isinstance(response, str):
            response = str(response or "")
        last_response = response
        try:
            plan = _parse_plan_response(response)
            plan = _enforce_requirement_paths(requirement, plan)
            attempts.append(PlannerAttempt(attempt + 1, len(response), None, None, "validation", True))
            logger.info("Planner succeeded: attempt=%d tasks=%d response_chars=%d", attempt + 1, len(plan["tasks"]), len(response))
            return plan
        except ValueError as exc:
            last_error = exc
            attempts.append(PlannerAttempt(attempt + 1, len(response), type(exc).__name__, str(exc), _classify_validation_error(exc), False))
            logger.warning("Planner attempt %d validation failed: type=%s error=%s response_chars=%d", attempt + 1, _classify_validation_error(exc), exc, len(response))
    diagnostics = "; ".join(f"attempt={item.attempt}, stage={item.stage}, error_type={item.error_type}, error={item.error!r}, response_chars={item.response_length}" for item in attempts)
    raise ValueError("Planner 在多次尝试后仍无法生成合法计划。\n" f"attempts={len(attempts)}; diagnostics: {diagnostics}") from last_error

class PlannerAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "planner"
    def run(self, task: Task):
        if not isinstance(task, Task):
            raise TypeError("PlannerAgent.run() expects Task, " f"got {type(task).__name__}")
        requirement_analysis = task.context.get("requirement_analysis")
        plan = create_plan(
            task.description,
            llm=self.llm,
            metrics=self.llm_metrics,
            requirement_analysis=requirement_analysis if isinstance(requirement_analysis, str) else None,
        )
        return {"status": "planner_completed", "agent": self.role, "task_id": task.id, "plan": plan}
