# AI-Team 使用说明书（User Guide）

> 适用版本：当前 `feature/reviewer-reliability-fallback` 开发分支
> 本手册描述如何使用 AI-Team 真实运行一次 AI 开发团队，从用户需求到可检验的交付物。

---

## 1.1 澄清工作流（需求模糊时推荐）

需求只有一句话时，推荐先用分析模式拿到结构化的需求规格草案与待确认问题：

```bash
# 第一步：只做需求分析（一次模型调用，产出规格草案 + 待确认问题）
python main.py "<你的需求>" --analyze-only
# 输出 requirement_analysis.md，其中包含【假设】与【待确认问题】

# 第二步：客户在文末『客户答复』章节逐条作答后，带答复启动完整交付
python main.py "<你的需求>" --clarifications requirement_analysis.md
```

答复会被视为权威结论：相关【假设】升级为已确认约束，已解决问题移出待确认列表。

## 1.2 阻断式验收门禁（CI/自动化推荐）

```bash
python main.py "<需求>" --strict-acceptance
```

交付阶段会对每条需求（REQ-xxx）做确定性追溯验收（需求文档/设计文档/测试报告）；
启用该开关后，验收结论为 FAILED 时进程以非零码退出，可直接接入 CI 作为交付门禁。

## 1.3 交付包

完整交付运行结束后，`<交付目录>/` 内自动生成：
- 产品代码与测试
- `docs/`：需求规格说明书、设计文档、测试结果报告、部署指引、用户手册、验收报告
- `DELIVERY_MANIFEST.md`：全部交付文件的 SHA-256 清单
- `<项目名>-delivery.zip`：以上内容的单个交付包（已通过完整性校验）

---

## 1. 这是什么

AI-Team 是一个由七个角色组成的 AI 软件开发团队运行时：

```
你的需求 → Analyst(需求分析,产出需求规格草案) → Planner(拆解计划) → Architect(设计)
        → Developer(编码) → Tester(测试) → Reviewer(审核/返工)
        → Doc Writer(交付文档:需求/设计/测试报告/部署指引/用户手册 + 交付清单) → 项目结果
```

你只需要在命令行给出一句话需求或完整功能清单，团队将自动完成需求分析、计划、设计、编码、
测试、审核与交付文档的完整闭环。交付文档写入工作区 `docs/` 目录，交付清单
`DELIVERY_MANIFEST.md` 含每个交付文件的 SHA-256 校验值。

---

## 2. 环境准备

### 2.1 硬性要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 11 | 官方支持环境 |
| Python | **3.14** | 当前开发与测试基线 |
| 终端 | PowerShell | 所有命令以仓库根为工作目录 |

### 2.2 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2.3 确认基线健康

首次真实运行前，先确认契约测试全绿：

```powershell
pytest -q
```

这也是后续判断“问题来自环境还是模型”的基准线。

---

## 3. 配置大模型

配置规则已统一到 `config.configuration.load_configuration()`。详细 precedence、provider/model 校验和 Developer 实例配置见 [`docs/configuration_reference.md`](configuration_reference.md) 与 [`docs/production_configuration.md`](production_configuration.md)。

验证配置解析可以使用：

```powershell
python -c "from config.model import resolve_role_llm_spec; print([resolve_role_llm_spec(r) for r in ('planner','developer')])"
```

真实 provider client 的凭据检查发生在实际使用时，不要把 API key 提交到 git。

---

## 4. CLI

基本运行：

```powershell
python main.py "Build a small personal expense tracker"
```

常用选项：

```powershell
python main.py "..." --projects-base F:\workspace\projects
python main.py "..." --dashboard runs\dashboard.html
python main.py "..." --output json
```

`--output json` 是稳定的机器可读输出入口，适合脚本和 CI；不要依赖默认文本输出进行机器解析。完整参数与输出 contract 见 [`docs/cli_reference.md`](cli_reference.md)。

---

## 5. 第一次真实运行

推荐从单任务、小工具、零外部依赖开始，例如：

```powershell
python main.py "开发一个摄氏度转华氏度的Python命令行小工具，所有文件放在 workspace/demo01/ 目录下，完成后运行它验证正确性"
```

运行后检查最终任务状态，并亲自验收产物。生成代码默认位于仓库之外的项目工作区，不应把运行产物误认为仓库源代码。

---

## 6. 工作区、安全与恢复

Developer 文件操作受 workspace sandbox 保护，路径逃逸会被拒绝。网络访问、工具调用、secret 隔离和 prompt-injection 防护均有独立安全边界。

任务恢复使用 checkpoint、lease 和 recovery policy。不要因为单个时间戳过期就手工接管任务；应遵循运行时 recovery contract。

完整运维排查见 [`docs/operational_troubleshooting.md`](operational_troubleshooting.md)。

---

## 7. Plugin API

AI-Team 提供 versioned、capability-scoped Plugin API。插件必须经过 host allow-list 和 runtime context capability 两层授权；声明 capability 本身不等于获得权限。

完整说明和示例见 [`docs/plugin_api.md`](plugin_api.md)。

---

## 8. 费用与时长

一次完整运行包含多个角色的模型调用，Developer 还可能进行多次工具往返。建议从小需求开始，观察模型调用、工具调用和运行时长后再增加项目规模。

---

## 9. 故障排查

优先按以下顺序隔离问题：

1. `pytest -q` 确认代码基线。
2. 检查 provider/model 配置。
3. 检查 workspace、tool 和 network security boundary。
4. 查看 workflow events、logs、metrics、traces 和 dashboard。
5. 对恢复/告警问题参考 [`docs/operational_troubleshooting.md`](operational_troubleshooting.md)。

不要通过关闭安全边界或放宽测试来“修复”运行失败。行为问题应按 DevPlan 建立最小修复增量。

---

## 10. 开发流程

每个 DevPlan 节点遵循：

1. 基于当前仓库状态制定计划。
2. 实施最小必要修改。
3. 运行 focused contract tests。
4. 运行 `pytest -q` 作为验收门禁。
5. 在 `DevPlan.md` 中记录接受结果和提交。
