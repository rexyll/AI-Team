# OpenClaw 工作流与工程化设计调研 —— 面向「AI 开发团队自动交付管线」的可迁移机制

- 调研日期：2026-11-02
- 调研对象：开源项目 OpenClaw（GitHub 组织 `openclaw`，仓库 [openclaw/openclaw](https://github.com/openclaw/openclaw)，MIT 协议），原名 Clawdbot，曾短暂更名 Moltbot，2026-01-29 定名 OpenClaw
- 调研方法：以官方文档站 docs.openclaw.ai 的一手材料为主，GitHub 仓库 README 与 issue 为辅，第三方报道仅用于名称沿革与时间线
- 证据等级标注：【官方文档】= docs.openclaw.ai 一手材料；【官方仓库】= GitHub README/issue；【二手】= 第三方博客/媒体，仅作线索

---

## 0. 结论摘要

OpenClaw 是一个自托管的通用个人 AI 助手框架：一个常驻 **Gateway**（控制平面）把 20+ 聊天渠道、多 agent、工具执行、调度与记忆统一编排，核心是**按 session 串行化的 agent loop**，外围用**四层正交的权限/隔离体系**（tool policy → elevated → exec approvals 审批门 → sandbox）控制工具执行的破坏力，用 **SKILL.md 技能包、插件钩子、持久化 automation job、分层 Markdown 记忆**做扩展。它不解决研发管线问题，但它的**审批门分层、sub-agent announce 复核、写者围栏式的会话持久化、心跳自检任务、不可变技能包版本、记忆分层的门控晋升**六类机制对「需求→开发→测试→发布」全自动管线项目有直接借鉴价值（详见第 4 节 P1–P10）。整体置信度：**高**（结论全部落在一手官方文档与官方仓库上）。

---

## 1. 项目概况与名称沿革

**事实陈述**
- OpenClaw 定位：运行在自己电脑上的开源 AI 助手，"meets you in the channels you already use"——Discord、iMessage、Slack、Teams、Telegram、WhatsApp 等 20+ 渠道，另有 macOS/iOS/Android/Windows/Linux 原生应用；一个 Gateway 既可跑个人助理也可跑共享团队部署，"configuration is the only difference"。模型与 agent harness（Claude、Codex、本地模型）是可替换插件；状态、记忆、凭据全部留在用户硬件上。【官方仓库：README】
- 治理：OpenClaw Foundation（独立 501(c)(3)）雇佣核心团队并签署发布；无付费层、无托管服务。作者 Peter Steinberger，"built for Molty, a space lobster AI assistant"。【官方仓库：README】
- 名称沿革：2026-01-27 因 Anthropic 商标问题由 Clawdbot 改名 Moltbot；2026-01-29 再次主动更名为 OpenClaw。【二手：Forbes 2026-01-30、hyperight 2026-02-02、lumadock 2026-01-30】
- 文档站当前版本：v2026.10.6（docs 站导航栏 "Latest release"）。【官方文档】

**来源**
- https://github.com/openclaw/openclaw （README：定位、治理、安全模型一句话概括 "trusted gateway, untrusted execution, policy enforced by code"）
- https://www.forbes.com/sites/ronschmelzer/2026/01/30/moltbot-molts-again-and-becomes-openclaw-pushback-and-concerns-grow （改名时间线）
- https://hyperight.com/openclaw-ai-assistant-rebrand-security-guide （2026-01-27 Clawdbot→Moltbot、2026-01-29 Moltbot→OpenClaw）

---

## 2. 整体架构

### 2.1 Gateway / daemon：单例控制平面

**事实陈述**
- "The Gateway is the local control plane for sessions, tools, events, and channel connections. The Control UI, CLI, and TUI connect to the Gateway. Channels bring the assistant to … Companion apps and nodes add voice, Canvas, camera, screen, and device-local actions."【官方仓库：README "How it fits together"】
- Gateway 以 daemon 方式安装运行（`openclaw onboard --install-daemon`），有 `gateway status / restart / health / logs` 运维命令组；存在 **Gateway lock**：state 目录同一时刻只允许一个 Gateway 或 `openclaw agent --local` 进程持有，防止双写。【官方文档：Gateway architecture、agent-loop（"the Gateway state-directory lock prevents another Gateway or `openclaw agent --local` process from owning the same state directory concurrently"）】
- 对外协议是 WebSocket（Gateway protocol：transport / handshake / presence / RPC methods / session control / approval methods / versioning / auth），第三方可编写 Gateway client 或用 OpenAI chat completions 兼容 API、Tools invoke API 接入。【官方文档：Gateway protocol 目录】
- 官方对架构安全模型的一句话：**"trusted gateway, untrusted execution, policy enforced by code"**（可信网关、不可信执行、策略由代码执行）。【官方仓库：README】

**借鉴点**：管线编排器应做成"单例控制平面 + 多种客户端（Web/CLI/IM）+ 显式协议"，而不是把编排逻辑散在脚本里。Gateway lock 的"状态目录单写者"约束值得照抄到管线的任务队列/状态库上。

**来源**
- https://docs.openclaw.ai/concepts/architecture （Gateway architecture）
- https://docs.openclaw.ai/gateway/protocol （Gateway protocol）
- https://github.com/openclaw/openclaw （README）

### 2.2 Agent loop：按 session 串行化的运行循环

**事实陈述**（以下均出自【官方文档：Agent loop】https://docs.openclaw.ai/concepts/agent-loop）
- 定义原文："The agent loop is the serialized, per-session run that turns a message into actions and a reply: intake, context assembly, model inference, tool execution, streaming, persistence."
- 入口：Gateway RPC `agent` / `agent.wait`；CLI `openclaw agent`。`agent` RPC 校验参数、解析 session（`sessionKey`/`sessionId`）、持久化 session 元数据后**立即返回 `{ runId, acceptedAt }`**，执行异步进行；`agent.wait` 按 runId 等终态 `{ status: ok|error|timeout, startedAt, endedAt }`，终态结果可重放（duplicate request after a terminal wait result can replay that outcome）。
- 队列与并发：**session controller 先按物理 session 身份把 turn 串行化，然后才进入全局容量准入**；消息渠道在同一有序输入上选择 queue mode（**steer / followup / collect / interrupt** 四种）。
- **写者围栏（writer-claim fence）**："an admitted run records its durable `activeWriterRunId` claim. Every transcript append or rewrite supplies `expectedWriterRunId`, and the synchronous commit transaction verifies that it still matches the active claim. A superseded run therefore cannot commit stale transcript data." 每agent 的变更由 SQLite writer queue 排序。
- 会话/工作区准备：解析并创建 workspace（沙箱 run 可重定向到沙箱 workspace root）→ 加载 skills 快照注入 env 与 prompt → 解析 bootstrap/context 文件注入 system prompt → 先准备好 transcript 目标与 writer claim 再开始流式输出。
- **必达回复语义**：必答 turn 结束若无答案，会做一次 tool-free finalization pass；空输出记为 failed outcome，"admitted user request receives one short system notice that no answer was returned, **rather than a fabricated assistant answer in history**"；外部 turn 可显式以 `NO_REPLY` 结束（静默令牌）。
- 重试与压缩：有界重试预算（bounded session retry budget）、auto-compaction 触发重试时重置内存缓冲与工具摘要防重复输出、模型 fallback 链；失败尝试的诊断保留在 raw transcript，展示层按 run 归并。
- 事件流：`lifecycle`（phase: start|finishing|end|error）、`assistant`、`tool` 三条流；终态发布后抑制后续重复终态事件。
- **审计台账**："The Gateway projects lifecycle and tool start/terminal events into the bounded, metadata-only **audit ledger**. This projection records provenance and result codes without copying prompts, messages, tool arguments, tool results, or raw errors." —— 即只记"发生了什么/结果码/出处"，不复制内容本体。

**借鉴点**：见第 4 节 P3（会话可恢复/事件溯源）、P9（失败如实上报）。

**来源**
- https://docs.openclaw.ai/concepts/agent-loop

### 2.3 Session 管理

**事实陈述**
- session 是一等实体：agent RPC 以 `sessionKey`/`sessionId` 解析；每个 agent 的会话历史与路由状态存于 `<agentDir>/openclaw-agent.sqlite`（SQLite）。【官方文档：Agent loop、Multi-agent routing】
- 直聊默认折叠到 per-agent 主会话：`agent:<agentId>:main`；群组/线程可映射到独立 session。【官方文档：Multi-agent routing（"Direct chats collapse to `agent:<agentId>:main` by default"）】
- 文档目录中有专门体系：Session management / Session controller / Session synchronization / Session search / **Session pruning** / Session state awareness / Session tools；`sessions_search`、`sessions_history` 提供"有界、脱敏"的历史摘录工具（memory 页明确：transcript 命中只是引用路径，读取须经 `sessions_history` 的 sanitized excerpt）。【官方文档：docs 目录与 Memory 页】
- 收到 chat `final` 后客户端可请求 **compaction、fork、rewind**（会话分叉/回退），与活跃 turn 冲突时返回 active-run 错误。【官方文档：Agent loop】

**借鉴点**：管线每个任务=一个可寻址 session（key 含 agent 与任务 ID），历史入库可检索、可分叉重跑、可修剪；读历史一律走有界脱敏 API 而非裸文件。

**来源**
- https://docs.openclaw.ai/concepts/agent-loop
- https://docs.openclaw.ai/concepts/multi-agent

### 2.4 Channel 接入（IM/Web）

**事实陈述**
- 渠道矩阵：WhatsApp、Telegram、Discord、Slack、Microsoft Teams、Google Chat、Signal、iMessage、Matrix、IRC、Mattermost、Feishu、QQ bot、WeChat、WeCom、LINE、Zalo 等 20+，每渠道有 setup / access control / message behavior / threads and sessions / **approvals** / troubleshooting 系列文档页。【官方文档：Channels 目录】
- **bindings 声明式路由**："A **binding** maps a channel account (a Slack workspace, a WhatsApp number, etc.) to one of those agents"；匹配键 `(channel, accountId, peer)`，可加 guild/team 维度，多字段 AND 语义；**固定层级顺序、最具体优先**（exact peer > parent peer > peer wildcard > guild+roles > guild > team > account > channel > fallback owner）；同层多条按配置顺序第一条胜出。【官方文档：Multi-agent routing】
- **无主消息的兜底**："a message that matches no binding is not given to an arbitrary first-listed agent"——有 systemAgent/owner 兜底则交给它，否则**不入派发**；可重试消息在"尝试上限 + 最小年龄（默认 24 小时）"双条件满足后 **dead-letter**。【官方文档：Multi-agent routing】
- 渠道级访问控制：`dmPolicy: allowlist | pairing`（陌生人默认走 pairing 配对码，`openclaw pairing approve <channel> <code>` 人工批准）、群组 mention 门控、bot loop protection。【官方仓库：README Security 节；官方文档：Configuration 目录】
- **审批走渠道卡片**：Discord 有 "components and approvals"、Slack 有 "charts, tables, and approvals"、Matrix/Telegram 有 "rich messages and approvals"——exec 审批提示可以渲染成渠道内的交互卡片。不同渠道能力不同：如 Feishu 不支持 chat 内 exec approvals，需到 Web UI 批准（GitHub issue #55639 印证）。【官方文档：Channels 目录；官方仓库：issue #55639】

**借鉴点**：见第 4 节 P7（声明式路由 + dead-letter）。

**来源**
- https://docs.openclaw.ai/concepts/multi-agent
- https://docs.openclaw.ai/channels （渠道总览）
- https://github.com/openclaw/openclaw/issues/55639

### 2.5 工具执行与审批门（Exec approvals）

**事实陈述**（以下均出自【官方文档：Exec approvals】https://docs.openclaw.ai/tools/exec-approvals，v2026.10 快照）
- 定位原文："Exec approvals are the companion app / node host guardrail for letting a sandboxed agent run commands on a real host (`gateway` or `node`). **Commands run only when policy + allowlist + (optional) user approval all agree.** Approvals stack on top of tool policy and elevated gating."——即四层正交：工具面（tool policy）→ 提权门（elevated）→ 宿主审批（exec approvals）→ 沙箱隔离（sandbox）。
- **五档 mode**（`tools.exec.mode`，规范化后的一档式开关）：
  | 值 | 行为 |
  | --- | --- |
  | `deny` | 阻断宿主执行 |
  | `allowlist` | 仅白名单命令直接放行 |
  | `ask` | 白名单策略 + 未命中时询问 |
  | `auto` | 白名单命中直接跑；未命中走 `allow`(一次)/`deny`(原因返回给 agent)/`ask`(人工) 评审 |
  | `full` | 无常规审批（受 strictInlineEval 等例外约束） |
- **白名单 per-agent、绑定到身份而非字符串**：条目含 `pattern`（可执行文件路径 glob）、`argPattern`（**argv 的 sha256**）、`source: allow-always`、`lastUsedAt`、`lastResolvedPath`；裸命令名只匹配经 PATH 调用的形式，`./rg`、`/tmp/rg` 不匹配。
- **TOCTOU 防护**："Gateway approval-backed commands bind every resolved command-segment executable before review and re-check it before launch."——批准后到启动前可执行文件身份（real-path，可写文件加内容 hash）变化即拒绝；shell 脚本/解释器直接调用还尝试绑定一个具体文件操作数，"If that file changes after approval but before execution, the run is denied instead of executing drifted content"；无法唯一确定操作数时"OpenClaw refuses to mint an approval-backed run rather than pretend full coverage"（宁可不批，不假装全覆盖）。
- **askFallback**：需要弹审批但 UI 不可达/超时时的兜底策略，缺省 `deny`（fail-closed）。
- **strictInlineEval**：`python -c`、`node -e`、`ruby -e`、`perl -e`、`php -r`、`osascript -e`、`awk/sed/find -exec/xargs` 等内联求值形式在严格模式下视为 approval-only——防止用解释器一行代码绕过白名单。
- **预设**：`openclaw exec-policy preset yolo | cautious | deny-all`；cautious = allowlist + on-miss + fallback deny。
- **策略存储与 CAS**：审批策略存共享状态库的 `exec_approvals_config` 单例行；"Saving a policy requires the last observed hash; a stale save fails and must be reloaded"（乐观锁）；最终提交在锁定事务内**对当前生效策略重新鉴权**。
- **审批界面与阻塞语义**："For native chat approval surfaces, a node exec **waits for the decision within the originating tool call** and returns the command output there. Closing or cancelling that turn invalidates its pending authority. A late approval cannot restart it."（审批在原工具调用内阻塞等待；回合取消则待批授权作废，迟到批准无效）。早期版本的 exec 审批是 fire-and-forget（issue #2402 记录了旧行为与修复诉求），现行文档为阻塞语义。
- **会话级请求**：`/exec security=full ask=off <task>` 只对当前消息请求策略；`/elevated full` 是 break-glass 快捷方式，且只有当请求策略与宿主审批文件**双方**都解析为 full/off 才跳过审批——更严的宿主文件仍然赢（"the stricter host policy still wins"）。

**已知缺陷（官方 issue，一手）**——说明审批门的实现边界，值得引以为戒：
- #10992（2026-02-07）：经 `sessions_spawn` 创建的子代理曾可绕过 exec approvals 执行命令（含写文件）；
- #2402（2026-01-26）：旧版审批流 fire-and-forget，工具先返回后审批；
- #46573（2026-03-14）：node 上 "Always allow" 白名单条目不生效；
- #42619（2026-03-10）：配置变更触发 Gateway 重启可把 exec 审批静默重置为受限模式；
- #1672（2026-01-24）：`tools.exec.ask: "off"` 未被尊重。

**借鉴点**：见第 4 节 P1。**核心教训**：审批门必须 ① 分层（工具面/提权/宿主/沙箱各自独立）② 绑定到"可执行文件身份 + argv 哈希"而非命令字符串 ③ fail-closed（UI 不在=拒绝）④ 阻塞等待决定且取消即作废 ⑤ 子进程必须继承策略（OpenClaw 曾在此处翻车）。

**来源**
- https://docs.openclaw.ai/tools/exec-approvals
- https://github.com/openclaw/openclaw/issues/10992 、/issues/2402 、/issues/46573 、/issues/42619 、/issues/1672

### 2.6 沙箱机制

**事实陈述**（【官方文档：Sandboxing】https://docs.openclaw.ai/gateway/sandboxing）
- 原文要点："OpenClaw can run tool execution inside a sandbox backend to limit the damage tools can cause. **Sandboxing is off by default** and controlled by `agents.defaults.sandbox` (global), `agents.entries.*.sandbox` (per-agent), or a required creator-role sandbox policy. **The Gateway process always stays on the host; only tool execution moves into the sandbox when enabled.**"
- 后端可插拔，按能力矩阵选型：**Docker（默认本地后端，可启用沙箱化浏览器）、Podman、SSH（把沙箱执行卸载到远程机器）、OpenShell（托管远程环境）、Crabbox（云盒租用，agent 留在本地）**；支持镜像定制与一次性 `setup` 容器初始化。
- workspace 访问粒度可调：沙箱能看到 agent workspace 的哪些部分、一个 agent 挂多个文件夹，均有专门页。
- **三概念正交**："Sandbox vs Tool Policy vs Elevated" 独立成页，用于调试"为什么这个操作被拦"——隔离（能跑在哪）、策略（允许跑什么）、提权（何时要求更强许可）互不替代。
- 与审批门的关系：`sandbox` 宿主默认 `security: deny`（比 gateway/node 的默认 `full` 严得多）——进沙箱的会话默认禁宿主执行。

**借鉴点**：见第 4 节 P8。

**来源**
- https://docs.openclaw.ai/gateway/sandboxing
- https://docs.openclaw.ai/security/sandbox （Sandbox vs Tool Policy vs Elevated，docs 目录页名）

---

## 3. 扩展机制设计要点

### 3.1 Automation（heartbeat / cron）

**事实陈述**（【官方文档：Automation】https://docs.openclaw.ai/automation 及 Automations 页 https://docs.openclaw.ai/automation/cron-jobs、Heartbeat migration https://docs.openclaw.ai/gateway/heartbeat）
- 原文："Automations are OpenClaw's built-in scheduler for all recurring and one-shot work, including periodic monitors. **The scheduler persists jobs, wakes the agent at the right time, and can deliver output to a chat channel or webhook endpoint.** It supports one-shot reminders, recurring intervals and cron expressions, and inbound webhook triggers."
- **heartbeat 已被"降维"成普通 job**：每个心跳监控迁移为"ordinary editable job with their own scratch, execution policies, and delivery settings"——调度、prompt、scratch（小清单状态）、模型、session、投递策略**全部归属 job 本身**，而不是全局一个心跳循环。机制选择页明确分工："Each independently scheduled task belongs in its own job."
- 防打扰与条件门：`activeHours`（安静时段）、`idleOnly`（前台忙时不跑）、scratch 清单 + `NO_REPLY`（"use scratch for a small checklist and `NO_REPLY` when nothing needs attention"）。
- 可观测：每个 job 有独立 run history（"automation run history to inspect scheduled work"）。
- 事件触发面：inbound webhooks、Gmail PubSub、IMAP email（sender-gated isolated reader sessions）、MCP Events（signed callbacks）、Hooks。
- **standing orders**：给 agent 的持久上下文与权限边界（"Standing orders give the agent persistent context and authority boundaries"）——与定时任务、事件钩子并列的第三种"后台机制"。
- 设计取向（负证据也有一手）：v2026.8.1 移除了"从对话推断 follow-up 并经 heartbeat 递送"的实验（inferred commitments），明确".reminders or scheduled work, create an **explicit** automation"——**隐式意图被显式任务替代**。【官方文档：Automation 页移除公告】

**借鉴点**：见第 4 节 P4。

### 3.2 Skills / Plugins

**事实陈述**（【官方文档：Skills】https://docs.openclaw.ai/tools/skills）
- 原文："Skills are markdown instruction files that teach the agent how and when to use tools. Each skill lives in a directory containing a `SKILL.md` file with YAML frontmatter and a markdown body."遵循 **AgentSkills 规范**；frontmatter 最少 `name` + `description`；正文可用 `{baseDir}` 引用随包脚本/资源。
- **加载时门控（gating）**："filters them at load time based on environment, config, and binary presence"——按环境变量、配置、本机二进制是否存在过滤技能；`metadata.openclaw.requires` 声明依赖。
- **层级与优先级**：bundled → managed `~/.openclaw/skills` → agent workspace → 个人库；同名校验优先级固定；per-agent allowlist：`agents.defaults.skills` 共享基线，`agents.entries.*.skills` 显式**替换**而非合并。
- **不可变 revision**："Saving publishes a complete immutable revision: `SKILL.md` and every supporting file. **The revision hash includes portable file paths, exact content, sizes, and executable flags.** Editing only a helper script still changes the revision."——库存于 `state/openclaw.sqlite`，不可变包存 `skill-library/<skill-id>/revisions/<revision-hash>/`。
- **安装策略门**：`security.installPolicy` 在任何技能安装继续之前运行可信本地策略命令，覆盖 ClawHub、上传、Git、本地、更新与依赖安装器路径，策略命令不给结论就阻断安装。
- 运行时注入：每 run 加载 skills snapshot 注入 env 与 system prompt（agent-loop 页）；slash command 即技能；单条消息最多引用 8 个技能，超限报错而非静默忽略。
- **Plugins**（区别于 skills：skills 是指令，plugins 是运行时能力）：类型含 feature / tool / **channel** / **provider** / CLI backend 插件；类型化钩子（plugin hooks）覆盖 agent loop 与 Gateway 管线全生命周期：`before_model_resolve`、`before_prompt_build`、`before_agent_reply`、`before_tool_call` / `after_tool_call`、`tool_result_persist`、`message_received/sending/sent`、`session_start/end`、`gateway_start/stop`、`before_install`；**块决策语义**：`before_tool_call` 返回 `{ block: true }` 是终态且短路低优先级处理器，`{ block: false }` 是 no-op 且**不能清除**先前 block。MCP 服务器可接入（含 node-hosted MCP）。【官方文档：Plugin hooks 目录与 agent-loop 页钩子表】
- 市场：ClawHub（发布、skill format、遥测、安全扫描）。【官方文档：ClawHub 目录】

**借鉴点**：见第 4 节 P5。

### 3.3 Memory

**事实陈述**（【官方文档：Memory】https://docs.openclaw.ai/concepts/memory）
- 设计原则原文："OpenClaw remembers things by writing plain Markdown files in your agent's workspace. **The model only remembers what gets saved to disk; there is no hidden state.**"
- **四文件分层**：
  - `USER.md`：稳定偏好/用户模型，指令式条目 + observed-date + active/superseded 元数据（偏好变更**原地作废旧条目**而非追加矛盾条目）；
  - `MEMORY.md`：持久事实与决策的精选层，session 开始注入；超出 bootstrap 预算时磁盘文件保持完整、注入副本截断（提示该瘦身了）；
  - `memory/YYYY-MM-DD.md`：每日工作层，索引供检索但**不每次注入**；
  - `DREAMS.md`：后台巩固的人审面。
- 工具三件套：`memory_search`（**混合检索**：向量相似 + 关键词，后端 SQLite 默认/可选 PostgreSQL `ts_rank` + pg_trgm + vector）、`memory_get`（按文件+行范围读）、`intent`（**事件条件的 standing intents**，时间类提醒仍走 scheduled tasks）。
- **Dreaming（后台巩固）**：默认开启，`memory-core` 自动管理一个周期 cron job 做 full dreaming sweep；晋升 MEMORY.md 必须过**分数、召回频次、查询多样性三重门**；"**Taint gated**: untrusted and system-derived candidates never enter the consolidation prompt or durable promotion path"；合并/作废决策经无工具的 completion 从已验证源证据合成，非法决策退回 **append-only** 兜底；全程写 `DREAMS.md` 供人审。文档自述该模式遵循 sleep-time compute（arXiv:2504.13171）与 Generative Agents 的持久记忆经验。
- **压缩前自动记忆冲刷**：compaction 摘要会话前，跑一个 silent turn 提醒 agent 把重要上下文写入持久记忆；冲刷用**私有会话副本**，家务消息不进后续用户回合；`write` 只允许追加新文本，整篇重放/复制段落被拒。
- **行动敏感记忆（action-sensitive memories）**：涉及审批/临时约束/交接/过期的记忆要写明"何时才可安全行动"；同时明确边界："**Memory can preserve approval context, but it does not enforce policy.** Use OpenClaw approval settings, sandboxing, and scheduled tasks for hard operational controls."（记忆可保存审批上下文，但策略执行必须靠硬控制）。
- **来源信任（provenance）**：标记为不可信/无有效读取来源身份的文件**不注入** bootstrap 上下文。

**借鉴点**：见第 4 节 P6。

### 3.4 多 agent 路由与 Sub-agents

**事实陈述**
- **多 agent**（【官方文档：Multi-agent routing】https://docs.openclaw.ai/concepts/multi-agent）："Run multiple *isolated* agents in one Gateway process, each with its own workspace, state directory (`agentDir`), and SQLite-backed session history, plus multiple channel accounts."
  - **agent = workspace + agentDir + session store**：workspace 放 `AGENTS.md`/`SOUL.md`/`USER.md` 与笔记；agentDir 放 auth profiles、model registry、per-agent 配置；session store 是 `<agentDir>/openclaw-agent.sqlite`。警告原文："**Never reuse `agentDir` across agents** — it causes auth/session state collisions."（OAuth 刷新材料默认不可跨 agent 复制）。
  - skills 从本 agent workspace + 共享根（`~/.openclaw/skills`）加载，再按 per-agent allowlist 过滤。
  - agent 间调用有独立开关：`tools.agentToAgent.allow: ["home","work"]`（缺省放行全部，可枚举限制）。
  - 每 agent 可绑定不同模型（示例：日常用 Sonnet、深度工作用 Opus，按渠道/对端路由）。
- **Sub-agents**（【官方文档：Sub-agents】https://docs.openclaw.ai/tools/subagents）：原文："Sub-agents are background agent runs spawned from an existing agent run. Each one runs in its own session (`agent:<agentId>:subagent:<uuid>`) and, **by default, announces its result back to the requester for review.** Subagent runs are tracked by the native subagent lifecycle owner."
  - 工具面：`sessions_spawn`（派生）、`sessions_yield`（让出/等待）、`subagents`（列管）；派生的会话可 `visible: true` 变成会话树中的普通会话（可输入、可转向），隐藏 helper 走 announce 链回报。
  - **子代理默认丢工具**：专门的 Sub-agent tool policy 页维护"tools a sub-agent always loses"清单，且可进一步收窄（hard deny 保持有效）。
  - 编排约束：嵌套深度上限（Nested sub-agents 页：depth caps）、并发/重启恢复/子树停止（Sub-agent concurrency, recovery, and stopping 页）、announce 超时 `announceTimeoutMs`、`allowAgents`/`requireAgentId` 派发限制。
  - 前述缺陷 #10992（子代理绕过 exec approvals）即发生在这条机制上——隔离与审批必须显式覆盖子代理。
- 并行专家道（Parallel specialist lanes）、委托架构（Delegate architecture）、presence 在 docs 多 agent 章节下各有专页（本轮未逐页展开，列为待证项）。

**借鉴点**：见第 4 节 P2、P7。

---

## 4. 对「AI 开发团队自动交付管线」最有借鉴价值的设计模式

> 项目背景：ai-dev-team 要实现「需求→AI 自主分析→架构设计→输出文档→分配 Developer 开发→单元测试→集成联调→打包→提交测试团队测试→回归→输出测试报告→发布」全流程自动化。OpenClaw 是通用助手框架，以下只取**可迁移机制**，不取表面功能。

**P1. 人在环审批门：分层准入 + 身份绑定 + fail-closed**（支撑强度：最高）
- OpenClaw 做法：四层正交（工具面→提权→宿主审批→沙箱）；`deny/allowlist/ask/auto/full` 五档；白名单绑定**可执行文件 real-path + argv sha256 + 文件操作数**，批准后启动前复查，漂移即拒；`askFallback` 缺省 deny（审批人不在=拒绝）；strictInlineEval 堵解释器 `-c/-e` 绕过；审批在原工具调用内**阻塞等待**，回合取消授权作废；宿主策略比配置严时宿主赢。
- 出处：https://docs.openclaw.ai/tools/exec-approvals
- 管线映射：Developer agent 的 `git push`、依赖安装、打包发布、环境清理按档位分级——打包/单测走 allowlist 直接跑，push/发布走 ask，生产发布走 auto+人审；无审批人在线一律挂起而非放行；命令白名单存"程序身份+参数哈希"，不接受字符串匹配。

**P2. 计划-执行-复核分离：sub-agent 独立会话 + announce 回报**
- OpenClaw 做法：子任务在独立 session（`agent:<agentId>:subagent:<uuid>`）后台运行，**默认把结果 announce 回请求者"for review"**；子代理工具面默认收窄（hard deny 清单）+ 深度上限 + 并发/恢复/子树停止；visible 派生会话可人工接管转向。
- 出处：https://docs.openclaw.ai/tools/subagents
- 管线映射：分析/架构/开发/测试各阶段作为 sub-agent 独立会话执行，产出必须经主控（或人）复核 announce 后才流入下一阶段；子代理天然无发布权（工具面收窄），与 P1 的审批门叠加。

**P3. 会话可恢复：写者围栏 + runId 终态重放 + fork/rewind**
- OpenClaw 做法：准入 run 记录持久 `activeWriterRunId`，每条 transcript 写入带 `expectedWriterRunId`，SQLite 同步提交事务校验——被取代的 run 无法提交陈旧数据；`agent.wait` 终态可重放；final 后可请求 compaction/fork/rewind；失败尝试诊断留在 raw transcript。
- 出处：https://docs.openclaw.ai/concepts/agent-loop
- 管线映射：管线状态机每次迁移持久化（阶段、runId、产物摘要、writer 声明）；崩溃后从 last-known-good 恢复；并发恢复的旧任务写不进状态库（围栏）；需要重跑某阶段用 fork 而不是手工改库。

**P4. 心跳自检：持久化 job + 安静时段 + 静默回报**
- OpenClaw 做法：automation job 持久化，调度/prompt/scratch/模型/session/投递策略**归属 job 本身**（heartbeat 已迁移为普通 job）；`activeHours`/`idleOnly` 门控；无事时 `NO_REPLY` 静默；每 job 有 run history；standing orders 给持久权限边界；v2026.8.1 刻意移除"从对话推断任务"改为**显式创建** automation。
- 出处：https://docs.openclaw.ai/automation 、https://docs.openclaw.ai/automation/cron-jobs 、https://docs.openclaw.ai/gateway/heartbeat
- 管线映射：守护进程每 N 分钟自检——停滞任务、超时未决审批、失败重试队列、当日构建窗口（activeHours 限定夜间跑回归）；无事不打扰 IM；每个定时检查是可编辑、可查历史的显式 job，不藏在代码里。

**P5. 技能包机制：SKILL.md + 不可变 revision + 安装门**
- OpenClaw 做法：技能=Markdown 指令包（YAML frontmatter: name/description + 正文），加载时按环境/配置/二进制存在性门控；保存即发布**不可变 revision**（哈希覆盖路径、内容、大小、可执行位）；安装前过 `security.installPolicy` 策略命令；per-agent allowlist 控制分发；市场（ClawHub）+ 工作台（Skill Workshop）。
- 出处：https://docs.openclaw.ai/tools/skills
- 管线映射：把"如何跑单元测试、如何出测试报告、如何打包、如何写架构文档"做成可版本化技能包挂到对应 agent；revision 哈希让每次交付可回答"当时用的是哪版流程规范"；技能按 agent allowlist 分发（Developer 拿编码技能，Tester 拿测试技能）。

**P6. 显式记忆分层 + 门控晋升 + 人审**
- OpenClaw 做法：USER/MEMORY/daily/DREAMS 四层；daily 层只索引不注入；dreaming 后台巩固过三重门才晋升 MEMORY.md，不可信来源永不进入晋升路径，DREAMS.md 人审；compaction 前自动记忆冲刷；**"Memory can preserve approval context, but it does not enforce policy"**。
- 出处：https://docs.openclaw.ai/concepts/memory
- 管线映射：项目长期决策/接口契约进"项目 MEMORY 层"（每阶段注入），过程日志进 daily 层（检索用不占 prompt）；AI 自主分析的结论必须经人审/测试通过才晋升为"项目事实"，防止幻觉固化为需求；审批上下文只作记录，硬约束仍靠审批门与沙箱。

**P7. 声明式路由 + 无主消息 dead-letter**
- OpenClaw 做法：binding = `(channel, accountId, peer) → agentId`，固定层级最具体优先；"a message that matches no binding is not given to an arbitrary first-listed agent"，无兜底则不入派发，重试超"上限+24h 最小年龄"后 dead-letter。
- 出处：https://docs.openclaw.ai/concepts/multi-agent
- 管线映射：需求单→分析 agent、模块→指定 Developer、测试报告→Tester 的路由全部写成声明式规则（最具体优先），禁止"顺手给第一个空闲 agent"；无主工单挂起+告警，超时进死信队列人工处理。

**P8. 沙箱与宿主分离：控制面在宿主、执行面在容器**
- OpenClaw 做法：Gateway 常驻宿主，仅工具执行移入沙箱；后端可插拔（Docker/Podman/SSH/OpenShell/Crabbox）；沙箱宿主默认 `security: deny`；"Sandbox vs Tool Policy vs Elevated" 正交分调。
- 出处：https://docs.openclaw.ai/gateway/sandboxing
- 管线映射：编排器/状态库在宿主（可信），构建、单测、集成联调全部在一次性容器执行（不可信）；"为什么被拦"三类原因（隔离/策略/提权）分开排查，不做一个大而全的开关。

**P9. 必达回复与失败如实上报**
- OpenClaw 做法：必答 turn 无答案时做 tool-free finalization pass，仍无则记 failed outcome 并发系统通知——"rather than a fabricated assistant answer in history"；`NO_REPLY` 是显式静默协议；重试有界且可取消。
- 出处：https://docs.openclaw.ai/concepts/agent-loop
- 管线映射：每个阶段必须有"完成/失败/显式跳过"三态终态，禁止超时后把中间产物当交付物；失败如实写进阶段报告并触发 P4 的自检告警。

**P10. 审计台账：metadata-only 事件溯源**
- OpenClaw 做法："The Gateway projects lifecycle and tool start/terminal events into the bounded, metadata-only audit ledger. This projection records provenance and result codes without copying prompts, messages, tool arguments, tool results, or raw errors."；审批策略保存走 CAS 哈希；技能/审批白名单条目都带时间戳（lastUsedAt/addedAt）。
- 出处：https://docs.openclaw.ai/concepts/agent-loop（Event streams 节）、https://docs.openclaw.ai/tools/exec-approvals
- 管线映射：事件溯源日志只记"谁、何时、批准/执行了什么命令（身份+哈希）、结果码"，正文留在各自存储——日志可长期保留可合规审计，又不含敏感内容本体。

---

## 5. 风险与边界（一手 issue 佐证）

1. **审批门不是自动成立的**：子代理曾绕过 exec approvals（#10992）——管线里子任务/子进程必须显式继承审批策略并测试验证。
2. **审批语义要阻塞**：旧版 fire-and-forget 审批（#2402）使"先执行后批准"成为可能——管线审批必须同步阻塞且取消即作废（现行文档语义）。
3. **配置漂移会回退权限**：重启静默重置审批模式（#42619）、allow-always 不生效（#46573）——审批白名单需要"启动时校验 + doctor 类自检"（OpenClaw 用 `openclaw approvals get` 与 Doctor 机制应对）。
4. **渠道能力不齐**：部分渠道不支持聊天内审批（#55639，Feishu）——多渠道接入时审批面要设计降级路径（Web UI 兜底）。

---

## 6. 待证项（本轮未展开，值得跟进）

- Gateway protocol 各 RPC 方法与 approval methods 的具体报文（建议读 https://docs.openclaw.ai/gateway/protocol 子页）——若管线要做 Web 审批台可直接对齐其 approval RPC 形状。
- Parallel specialist lanes / Delegate architecture / Presence 三页（docs 多 agent 章节）——并行道与委托架构对"多 Developer 并行开发"可能有更细的模式。
- Session pruning / Compaction 具体策略（长期运行管线的上下文治理）。
- Lobster（"runs local pipelines with resumable approvals"，Automation 页提及）——**可恢复审批的本地管线执行器**，与本项目最相关，建议专项调研（https://docs.openclaw.ai/tools/lobster，docs 目录出现 The Lobster 页）。
- Workboard plugin（docs 出现 Workboard CLI/插件）——任务板与管线的结合方式。

## 7. 来源 URL 总表

**官方文档（一手，docs.openclaw.ai，快照版本 v2026.10.6，访问日期 2026-11-02）**
1. https://docs.openclaw.ai/ （文档站首页）
2. https://docs.openclaw.ai/concepts/architecture （Gateway architecture）
3. https://docs.openclaw.ai/concepts/agent-loop （Agent loop：运行序列/队列/写者围栏/钩子/重试/事件流/审计台账）
4. https://docs.openclaw.ai/tools/exec-approvals （Exec approvals：五档 mode/白名单绑定/askFallback/strictInlineEval/CAS 存储）
5. https://docs.openclaw.ai/gateway/sandboxing （Sandboxing：默认关闭/多后端/正交分层）
6. https://docs.openclaw.ai/concepts/multi-agent （Multi-agent routing：agent 组成/bindings 路由/dead-letter）
7. https://docs.openclaw.ai/tools/subagents （Sub-agents：独立会话/announce/工具收窄/深度上限）
8. https://docs.openclaw.ai/automation （Automation 总览：机制选型/heartbeat 迁移/standing orders）
9. https://docs.openclaw.ai/automation/cron-jobs （Automations：调度类型/投递/条件）
10. https://docs.openclaw.ai/gateway/heartbeat （Heartbeat migration：心跳任务迁移）
11. https://docs.openclaw.ai/tools/skills （Skills：SKILL.md 格式/门控/revision/install policy/ClawHub）
12. https://docs.openclaw.ai/concepts/memory （Memory：四文件分层/检索工具/dreaming/行动敏感记忆/provenance）

**官方仓库（一手，github.com/openclaw/openclaw）**
13. https://github.com/openclaw/openclaw （README：定位/How it fits together/Security/Governance）
14. https://github.com/openclaw/openclaw/issues/10992 （子代理绕过 exec approvals）
15. https://github.com/openclaw/openclaw/issues/2402 （审批 fire-and-forget 旧行为）
16. https://github.com/openclaw/openclaw/issues/46573 （allow-always 在 node 不生效）
17. https://github.com/openclaw/openclaw/issues/42619 （重启静默重置审批）
18. https://github.com/openclaw/openclaw/issues/55639 （Feishu 不支持聊天内审批）

**二手来源（仅名称沿革与背景线索）**
19. https://www.forbes.com/sites/ronschmelzer/2026/01/30/moltbot-molts-again-and-becomes-openclaw-pushback-and-concerns-grow （Forbes，2026-01-30，改名时间线）
20. https://hyperight.com/openclaw-ai-assistant-rebrand-security-guide （2026-02-02，Clawdbot→Moltbot 2026-01-27、→OpenClaw 2026-01-29）
21. https://lumadock.com/blog/clawdbot-moltbot-openclaw-rebrand （2026-01-30，改名动机）

（附注：本次调研仅写入本文件，未改动项目其他文件；未运行任何项目测试。）
