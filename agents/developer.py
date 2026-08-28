import json
from datetime import datetime, timezone
from typing import Any

from tools.registry import TOOL_REGISTRY, TOOLS
from agents.base import BaseAgent
from runtime.task import Task
from runtime.agent_context import AgentContext
from runtime.context_view import context_view
from runtime.tool_execution_history import ToolExecutionHistory
from runtime.tool_execution_record import ToolExecutionRecord
from runtime.tool_loop_telemetry import classify_tool_call
from runtime.tool_loop_cache import ToolResultCache, CACHEABLE_TOOLS
from runtime.tool_loop_progress_guard import ToolLoopProgressGuard
from runtime.tool_loop_checkpoint import build_tool_loop_checkpoint, DEFAULT_CHECKPOINT_INTERVAL, upsert_tool_loop_checkpoint
from runtime.tool_loop_verification import should_suppress_verification, record_verification_evidence
from runtime.tool_loop_decision_turn import classify_decision_turn
from runtime.tool_result_evidence import reduce_tool_result
from runtime.safe_tool_batch import classify_safe_tool_batch
from runtime.safe_tool_batch_executor import execute_safe_tool_batch
from security.tool_guard import validate_tool_arguments
from runtime.agent_result import AgentResult

MAX_TOOL_ITERATIONS = 50
TOOL_LOOP_CHECKPOINT_INTERVAL = DEFAULT_CHECKPOINT_INTERVAL

SYSTEM_PROMPT = """
你是一名专业的 AI 软件开发工程师。
你运行在 Windows 11 环境。

你只能操作受保护的项目工作区。
对你而言，"." 表示工作区根目录。
不要访问工作区之外的目录、系统目录、用户目录、Program Files、注册表或系统配置。

查看目录优先使用 list_files，读取文件使用 read_file，修改文件使用 write_file。
不要使用 run_command 代替文件工具。
run_command 只用于测试、构建、执行程序或专用开发工具。

执行开发任务时：
1. 理解任务
2. 阅读 Architect 提供的设计
3. 检查工作区
4. 阅读相关代码
5. 分析问题
6. 制定最小修改方案
7. 修改代码
8. 运行测试
9. 检查测试结果
10. 必要时继续修复
11. 汇报完成情况

修改代码之前必须先读取相关文件。
遵循正确性优先、简单优先、最小修改、不进行无关重构的原则。

工具探索效率规则：
- list_files 对同一路径通常只需要调用一次；已有结果仍然有效时不要重复调用。
- 同一个文件已经成功 read_file 后，不要无理由再次读取；只有文件可能已发生变化、需要重新确认或证据不足时才重新读取。
- 只读的参考文档，只读取一次即可；不要为了“确认”而重复读取完全相同的只读内容。
- 对已经获得且仍然有效的工具证据，优先复用已有证据，避免无意义的重复探索。
- 效率规则绝不能降低正确性。
- 测试失败、实现发生变化或证据不足时，必须重新读取、重新执行或重新验证；不得为了减少 tool call 而复用失效证据。

交付前必须做可运行性自检（站在最终用户视角）：
1. 确定用户运行交付物的确切命令（直接脚本，或 python -m 包名.模块名）。
2. 实际执行该命令，确认产物按预期工作。
3. 若入口模块使用了包内相对导入，禁止让用户以裸脚本方式直接运行它；必须在汇报中写明正确的启动命令，并确保该命令已实测通过。

收到返工要求或测试未通过时：
- 先核对上一轮是否真的产出了文件、修改与测试证据；
- 若反馈指出你未实际创建文件、未调用工具或仅有文字说明，必须在本轮立即使用 write_file 等工具完成实际产物，禁止再次仅输出文字说明或重复上轮的空汇报；
- 每一轮都必须有可验证的新增动作（新工具调用或新测试结果）。

最终汇报时必须说明：完成了什么、修改了哪些文件、执行了哪些测试、测试结果、用户运行交付物的确切命令、是否存在遗留问题。
"""


class DeveloperAgent(BaseAgent):
    @property
    def role(self) -> str:
        return "developer"

    def _build_messages(self, context: AgentContext):
        view = context_view(context, self.role)
        context_text = ""
        if view["dependency_context"]:
            context_text += "\n====================\nUPSTREAM AGENT CONTEXT\n====================\n"
            for context_key, data in view["dependency_context"].items():
                if not isinstance(data, dict):
                    continue
                context_text += f"\nDependency: {context_key}\nRole: {data.get('role', '')}\nTitle: {data.get('title', '')}\n"
                result = data.get("result", {})
                if isinstance(result, dict):
                    architecture = result.get("architecture")
                    if architecture:
                        context_text += "\nArchitect Architecture Design:\n" + str(architecture)
                    else:
                        context_text += json.dumps(result, ensure_ascii=False, indent=2)
                else:
                    context_text += str(result)
                context_text += "\n"
        if view["reviewer_feedback"]:
            context_text += "\n====================\nPREVIOUS REVIEW FEEDBACK\n====================\n\n以下是上一轮 Reviewer 给出的修改意见。\n本轮必须认真处理这些意见，并在最终结果中说明如何解决。\n\n"
            context_text += json.dumps(view["reviewer_feedback"], ensure_ascii=False, indent=2)
        prompt = f"""
====================
CURRENT TASK
====================
Task ID: {view['task_id']}
Role: {view['role']}
Title: {view['task_title']}
Description: {view['task_description']}
Status: {view['status']}
Dependencies: {view['dependencies']}
Current Task Result:
{view['task_result']}
Tester Feedback:
{view['tester_feedback']}
Review Round:
{view['review_round']}
Execution History:
{view['history']}
Metadata:
{view['metadata']}
{context_text}
====================
EXECUTION REQUIREMENT
====================
请完成当前开发任务。
开始工作前先检查工作区并阅读相关代码。
完成修改后运行相关测试。如果测试失败，请继续分析和修复。
最终给出简洁的开发结果报告。
报告必须包含：1. 完成内容 2. 修改文件 3. 测试命令 4. 测试结果 5. 遗留问题
"""
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]

    def run(self, task: Task) -> AgentResult:
        if not isinstance(task, Task):
            raise TypeError("DeveloperAgent.run() expects Task, " f"got {type(task).__name__}")
        context = self.build_context(task)
        messages = self._build_messages(context)
        persisted_history = task.context.get("tool_execution_history")
        if persisted_history is None:
            self.tool_execution_history = ToolExecutionHistory()
        else:
            try:
                self.tool_execution_history = ToolExecutionHistory.from_dict(persisted_history)
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"task {task.id} contains invalid persisted tool execution history") from exc
        changed_files: list[str] = []
        command_results: list[dict[str, Any]] = []
        verification_evidence: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        loop_telemetry: list[dict[str, Any]] = []
        prior_signatures: list[tuple[str, str, str, str]] = []
        cache = ToolResultCache()
        progress_guard = ToolLoopProgressGuard()
        verification_reused_count = 0
        workspace_revision = 0
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._generate_with_tools(messages, tools=TOOL_REGISTRY.schemas(), tool_choice="auto")
            if not response.tool_calls:
                content = response.content or ""
                if not changed_files and not command_results and not tool_calls:
                    return AgentResult(status="failed", agent=self.role, task_id=context.task_id, message=("Developer produced no artifacts: zero tool calls, zero file changes, zero commands. " f"Final text head: {content[:200]}"), data={"validation": {"tool_call_count": 0, "test_command_count": 0, "files_changed_count": 0, "no_artifact_completion": True}, "report": content})
                data = self._build_result_data(content=content, changed_files=changed_files, command_results=command_results, tool_calls=tool_calls, loop_telemetry=loop_telemetry)
                data["tool_loop_cache"] = {"hits": cache.hits, "misses": cache.misses, "invalidations": cache.invalidations}
                data["tool_loop_verification"] = {"reused": verification_reused_count}
                return AgentResult(status="completed", agent=self.role, task_id=context.task_id, message=content, data=data)
            messages.append({"role": "assistant", "content": response.content, "tool_calls": [{"id": call.call_id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in response.tool_calls]})

            batched_results: dict[str, Any] = {}
            batch_candidates: list[dict[str, Any]] = []
            batch_possible = len(response.tool_calls) > 1
            if batch_possible:
                try:
                    for call in response.tool_calls:
                        parsed = json.loads(call.arguments)
                        if not isinstance(parsed, dict):
                            batch_possible = False
                            break
                        tool_function = TOOL_REGISTRY.get(call.name)
                        tool_schema = TOOL_REGISTRY.schema(call.name)
                        validated, ignored = validate_tool_arguments(tool_function, parsed, schema=tool_schema)
                        if ignored:
                            batch_possible = False
                            break
                        if call.name not in CACHEABLE_TOOLS:
                            batch_possible = False
                            break
                        if cache.lookup(call.name, validated) is not None:
                            batch_possible = False
                            break
                        batch_candidates.append({"call_id": call.call_id, "name": call.name, "arguments": dict(validated)})
                    if batch_possible:
                        decision = classify_safe_tool_batch(batch_candidates)
                        if decision.safe:
                            _, results = execute_safe_tool_batch(
                                [{"name": item["name"], "arguments": item["arguments"]} for item in batch_candidates],
                                lambda name, arguments: TOOL_REGISTRY.get(name)(**arguments),
                            )
                            batched_results = {item["call_id"]: result for item, result in zip(batch_candidates, results)}
                except Exception:
                    # Fall back to the existing serial path; a safe batch is an
                    # optimization and must never change error semantics.
                    batched_results = {}

            for tool_call in response.tool_calls:
                tool_name = tool_call.name
                started_at = datetime.now(timezone.utc).isoformat()
                status = "completed"
                result: Any = None
                error: Any = None
                record_arguments: dict[str, Any] = {}
                verification_reused = False
                print(f"\n[Tool] {tool_name}")
                try:
                    arguments = json.loads(tool_call.arguments)
                except (TypeError, json.JSONDecodeError) as exc:
                    status = "invalid_arguments"
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    result = "Tool error: invalid JSON arguments: " f"{type(exc).__name__}: {exc}"
                    telemetry = classify_tool_call(tool_name=tool_name, arguments={}, result=result, prior=prior_signatures)
                    telemetry_dict = self._telemetry_dict(tool_call.call_id, tool_name, telemetry)
                    loop_telemetry.append(telemetry_dict)
                    messages.append({"role": "tool", "tool_call_id": tool_call.call_id, "content": self._build_tool_message(tool_name, result)})
                    self._record_tool_execution(execution_id=tool_call.call_id, task_id=context.task_id, tool_name=tool_name, started_at=started_at, status=status, arguments=record_arguments, output=None, error=error, metadata=telemetry_dict)
                    prior_signatures.append((tool_call.call_id, tool_name, telemetry.arguments_hash, status))
                    reason = progress_guard.record(tool_name=tool_name, status=status, duplicate_of=telemetry.duplicate_of, retry_of=telemetry.retry_of)
                    if reason:
                        return self._progress_guard_failure(context.task_id, reason, loop_telemetry, changed_files, command_results, tool_calls, cache, verification_reused_count)
                    self._append_checkpoint(messages, loop_telemetry, changed_files, command_results, workspace_revision)
                    continue
                if not isinstance(arguments, dict):
                    status = "invalid_arguments"
                    error = {"type": "TypeError", "message": "tool arguments must be a JSON object"}
                    result = "Tool error: arguments must be a JSON object"
                    telemetry = classify_tool_call(tool_name=tool_name, arguments={}, result=result, prior=prior_signatures)
                    telemetry_dict = self._telemetry_dict(tool_call.call_id, tool_name, telemetry)
                    loop_telemetry.append(telemetry_dict)
                    messages.append({"role": "tool", "tool_call_id": tool_call.call_id, "content": self._build_tool_message(tool_name, result)})
                    self._record_tool_execution(execution_id=tool_call.call_id, task_id=context.task_id, tool_name=tool_name, started_at=started_at, status=status, arguments=record_arguments, output=None, error=error, metadata=telemetry_dict)
                    prior_signatures.append((tool_call.call_id, tool_name, telemetry.arguments_hash, status))
                    reason = progress_guard.record(tool_name=tool_name, status=status, duplicate_of=telemetry.duplicate_of, retry_of=telemetry.retry_of)
                    if reason:
                        return self._progress_guard_failure(context.task_id, reason, loop_telemetry, changed_files, command_results, tool_calls, cache, verification_reused_count)
                    self._append_checkpoint(messages, loop_telemetry, changed_files, command_results, workspace_revision)
                    continue
                print(f"[Args] {arguments}")
                try:
                    tool_function = TOOL_REGISTRY.get(tool_name)
                    tool_schema = TOOL_REGISTRY.schema(tool_name)
                    validated_arguments, ignored_arguments = validate_tool_arguments(tool_function, arguments, schema=tool_schema)
                    record_arguments = dict(validated_arguments)
                    if ignored_arguments:
                        print("[Ignored Args] " f"{ignored_arguments}")
                    tool_calls.append({"name": tool_name, "arguments": dict(validated_arguments)})
                    verification_reused = should_suppress_verification(tool_name=tool_name, arguments=validated_arguments, command_results=verification_evidence, changed_files=changed_files, workspace_revision=workspace_revision)
                    if verification_reused:
                        verification_reused_count += 1
                        command = str(validated_arguments.get("command", ""))
                        result = f"Verification evidence reused: {command} previously succeeded at workspace revision {workspace_revision}; no workspace mutation occurred since that verification."
                        context_result = result
                        print("[Verification] prior successful evidence reused; command execution suppressed")
                    else:
                        cached = cache.lookup(tool_name, validated_arguments) if tool_name in CACHEABLE_TOOLS else None
                        if cached is not None:
                            result = cached.result
                            context_result = cached.context_evidence()
                            print("[Cache] exact read-only tool result reused")
                        elif tool_call.call_id in batched_results:
                            result = batched_results[tool_call.call_id]
                            context_result = result
                            cache.store(tool_name=tool_name, arguments=validated_arguments, result=result, execution_id=tool_call.call_id)
                            print("[Safe Batch] independent read-only tool result executed concurrently")
                        else:
                            result = tool_function(**validated_arguments)
                            context_result = result
                            cache.store(tool_name=tool_name, arguments=validated_arguments, result=result, execution_id=tool_call.call_id)
                        self._record_tool_evidence(tool_name=tool_name, arguments=validated_arguments, result=result, changed_files=changed_files, command_results=command_results)
                        if tool_name == "write_file" and status == "completed":
                            workspace_revision += 1
                        if tool_name == "run_command" and isinstance(validated_arguments.get("command"), str):
                            verification_evidence.append(record_verification_evidence(command=validated_arguments["command"], result=result, changed_files=changed_files, workspace_revision=workspace_revision))
                    if tool_name != "run_command" or not verification_reused:
                        cache.invalidate_for(tool_name)
                except KeyError:
                    status = "unknown_tool"
                    error = {"type": "KeyError", "message": f"Unknown tool: {tool_name}"}
                    result = f"Unknown tool: {tool_name}"
                    context_result = result
                except Exception as exc:
                    status = "failed"
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    result = "Tool error: " f"{type(exc).__name__}: {exc}"
                    context_result = result
                telemetry = classify_tool_call(tool_name=tool_name, arguments=record_arguments, result=result, prior=prior_signatures)
                telemetry_dict = self._telemetry_dict(tool_call.call_id, tool_name, telemetry)
                loop_telemetry.append(telemetry_dict)
                print(f"[Result]\n{result}")
                messages.append({"role": "tool", "tool_call_id": tool_call.call_id, "content": self._build_tool_message(tool_name, context_result)})
                self._record_tool_execution(execution_id=tool_call.call_id, task_id=context.task_id, tool_name=tool_name, started_at=started_at, status=status, arguments=record_arguments, output=result if status == "completed" else None, error=error, metadata=telemetry_dict)
                prior_signatures.append((tool_call.call_id, tool_name, telemetry.arguments_hash, status))
                reason = progress_guard.record(tool_name=tool_name, status=status, duplicate_of=telemetry.duplicate_of, retry_of=telemetry.retry_of, result_hash=telemetry.result_hash, progress=True if verification_reused else None)
                if reason:
                    return self._progress_guard_failure(context.task_id, reason, loop_telemetry, changed_files, command_results, tool_calls, cache, verification_reused_count)
                self._append_checkpoint(messages, loop_telemetry, changed_files, command_results, workspace_revision)
                if tool_name == "run_command":
                    decision = classify_decision_turn(tool_name=tool_name, arguments=record_arguments, result=result, status=status, category=telemetry.category, duplicate_of=telemetry.duplicate_of, retry_of=telemetry.retry_of, changed_files=changed_files, command_results=command_results, verification_reused=verification_reused)
                    if decision.terminal:
                        content = f"Terminal verification succeeded: {record_arguments.get('command', '')}"
                        data = self._build_result_data(content=content, changed_files=changed_files, command_results=command_results, tool_calls=tool_calls, loop_telemetry=loop_telemetry)
                        data["tool_loop_cache"] = {"hits": cache.hits, "misses": cache.misses, "invalidations": cache.invalidations}
                        data["tool_loop_verification"] = {"reused": verification_reused_count}
                        data["tool_loop_decision"] = {"reason": decision.decision.reason, "skip_llm_turn": decision.skip_llm_turn, "terminal": decision.terminal}
                        return AgentResult(status="completed", agent=self.role, task_id=context.task_id, message=content, data=data)
        raise RuntimeError("Developer tool loop exceeded maximum iterations: " f"{MAX_TOOL_ITERATIONS}")

    @staticmethod
    def _append_checkpoint(messages: list[dict[str, Any]], loop_telemetry: list[dict[str, Any]], changed_files: list[str], command_results: list[dict[str, Any]], workspace_revision: int = 0) -> None:
        if not loop_telemetry or len(loop_telemetry) % TOOL_LOOP_CHECKPOINT_INTERVAL != 0:
            return
        upsert_tool_loop_checkpoint(messages, loop_telemetry, changed_files=changed_files, command_results=command_results, workspace_revision=workspace_revision)

    def _progress_guard_failure(self, task_id: str, reason: str, loop_telemetry: list[dict[str, Any]], changed_files: list[str], command_results: list[dict[str, Any]], tool_calls: list[dict[str, Any]], cache: ToolResultCache, verification_reused_count: int = 0) -> AgentResult:
        data = self._build_result_data(content=reason, changed_files=changed_files, command_results=command_results, tool_calls=tool_calls, loop_telemetry=loop_telemetry)
        data["tool_loop_cache"] = {"hits": cache.hits, "misses": cache.misses, "invalidations": cache.invalidations}
        data["tool_loop_guard"] = {"tripped": True, "reason": reason}
        data["tool_loop_verification"] = {"reused": verification_reused_count}
        return AgentResult(status="failed", agent="developer", task_id=task_id, message=reason, data=data)

    def _record_tool_execution(self, *, execution_id: str, task_id: str, tool_name: str, started_at: str, status: str, arguments: dict[str, Any], output: Any, error: Any, metadata: dict[str, Any] | None = None) -> None:
        self.tool_execution_history.append(ToolExecutionRecord(execution_id=execution_id, task_id=task_id, agent_role=self.role, tool_name=tool_name, started_at=started_at, completed_at=datetime.now(timezone.utc).isoformat(), status=status, arguments=arguments, output=output, error=error, metadata=metadata or {}))

    @staticmethod
    def _telemetry_dict(execution_id: str, tool_name: str, telemetry: Any) -> dict[str, Any]:
        return {"execution_id": execution_id, "tool_name": tool_name, "arguments_hash": telemetry.arguments_hash, "result_hash": telemetry.result_hash, "result_chars": telemetry.result_chars, "retained_result_chars": telemetry.retained_result_chars, "result_truncated": telemetry.result_truncated, "duplicate_of": telemetry.duplicate_of, "retry_of": telemetry.retry_of, "category": telemetry.category}

    @staticmethod
    def _build_tool_message(tool_name: str, result: Any) -> str:
        return reduce_tool_result(tool_name, result).content

    @staticmethod
    def _record_tool_evidence(*, tool_name: str, arguments: dict[str, Any], result: Any, changed_files: list[str], command_results: list[dict[str, Any]]) -> None:
        if tool_name == "write_file":
            path = arguments.get("path")
            if isinstance(path, str) and path and path not in changed_files:
                changed_files.append(path)
        if tool_name == "run_command":
            command = arguments.get("command")
            if isinstance(command, str) and command:
                command_results.append({"command": command, "result": str(result)})

    @staticmethod
    def _build_result_data(*, content: str, changed_files: list[str], command_results: list[dict[str, Any]], tool_calls: list[dict[str, Any]], loop_telemetry: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        telemetry = list(loop_telemetry or [])
        duplicate_count = sum(1 for item in telemetry if item.get("duplicate_of"))
        retry_count = sum(1 for item in telemetry if item.get("retry_of"))
        result_chars = sum(int(item.get("result_chars", 0) or 0) for item in telemetry)
        retained_result_chars = sum(int(item.get("retained_result_chars", item.get("result_chars", 0)) or 0) for item in telemetry)
        truncated_result_count = sum(1 for item in telemetry if item.get("result_truncated"))
        validation = {"tool_call_count": len(tool_calls), "test_command_count": len(command_results), "files_changed_count": len(changed_files)}
        if telemetry:
            validation.update({"unique_tool_calls": len(telemetry) - duplicate_count, "duplicate_tool_calls": duplicate_count, "retry_tool_calls": retry_count, "tool_result_chars": result_chars, "retained_tool_result_chars": retained_result_chars, "tool_result_reduction_chars": max(0, result_chars - retained_result_chars), "truncated_tool_results": truncated_result_count, "largest_tool_result_chars": max((int(item.get("result_chars", 0) or 0) for item in telemetry), default=0), "tool_call_categories": {category: sum(1 for item in telemetry if item.get("category") == category) for category in sorted({str(item.get("category")) for item in telemetry})}})
        return {"summary": content.strip(), "files_changed": list(changed_files), "tests": list(command_results), "validation": validation, "tool_loop_telemetry": telemetry, "report": content}
