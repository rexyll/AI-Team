# AI-Team Local MCP Bridge 详细任务计划

> 文件名：`mcp_bridge_taskplan.md`
>
> 目标：为 AI-Team 建立一个安全、可审计、受项目边界约束的本地 MCP Bridge，使 ChatGPT/其他 MCP Client 能够稳定访问本地 AI-Team 工作区，并逐步具备读取、搜索、修改、测试、Git 操作和 AI-Team 项目自检能力。
>
> 设计原则：
> 1. Local MCP 是 AI-Team 的本地适配层，不重新发明第二套安全模型。
> 2. 默认最小权限，先只读、后写入、最后开放高风险操作。
> 3. 所有文件操作必须限制在明确的 workspace root 内。
> 4. 所有写操作必须可验证：`patch -> diff -> test -> verify`。
> 5. MCP 不得绕过 AI-Team 已有的 capability、workspace isolation、Host-owned Git、audit、tracing 等边界。
> 6. 不为了让测试通过而修改测试语义；新增测试只用于覆盖新增 MCP 契约。
> 7. 每个阶段都必须有明确的验收标准和回归测试。
> 8. Windows 11 是首要运行环境，同时尽量保持跨平台实现。
>
> 当前计划版本：v1.0
> 当前状态：未开始
> 推荐开发方式：按 Phase 顺序推进；每完成一个 Phase，运行对应测试并记录 Git commit。

---

# 1. 项目目标

## 1.1 总体目标

建立如下工作链路：

```text
ChatGPT / MCP Client
        |
        | MCP
        v
Local MCP Bridge
        |
        +--> Workspace Boundary
        +--> Capability / Policy
        +--> Audit
        |
        v
AI-Team Workspace
        |
        +--> source code
        +--> tests
        +--> benchmarks
        +--> DevPlan.md
        +--> git repository
```

最终支持：

```text
READ
  |
SEARCH
  |
ANALYZE
  |
PATCH
  |
DIFF
  |
TEST
  |
VERIFY
  |
COMMIT
```

## 1.2 第一阶段不追求的目标

V1 不做：

- 任意电脑文件系统访问
- 任意 PowerShell 执行
- 任意 shell 注入
- 自动删除文件
- 自动修改 Git 历史
- 自动 push remote
- 自动修改 MCP 自身权限配置
- 绕过 AI-Team 安全策略的“超级工具”
- 无限制 Docker / npm / pip / 网络命令执行

---

# 2. 推荐目录结构

建议最终形成：

```text
ai-dev-team/
├── mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── config.py
│   ├── errors.py
│   ├── models.py
│   ├── policy.py
│   ├── workspace.py
│   ├── search.py
│   ├── terminal.py
│   ├── git.py
│   ├── audit.py
│   ├── ai_team.py
│   └── transport.py
│
├── tests/
│   └── mcp/
│       ├── test_config.py
│       ├── test_workspace.py
│       ├── test_path_security.py
│       ├── test_search.py
│       ├── test_patch.py
│       ├── test_git.py
│       ├── test_terminal_policy.py
│       ├── test_audit.py
│       ├── test_ai_team_inspect.py
│       └── test_server_contract.py
│
└── docs/
    └── mcp/
        ├── architecture.md
        ├── security.md
        └── client-setup.md
```

> 如果项目现有架构已经有更合适的 `runtime/`、`security/` 或 `tools/` 扩展点，应优先复用已有 canonical boundary，而不是复制实现。

---

# 3. 总体阶段计划

| Phase | 内容 | 优先级 | 状态 |
|---|---|---:|---|
| 0 | 需求、架构与边界冻结 | P0 | ⬜ |
| 1 | MCP 基础运行框架 | P0 | ⬜ |
| 2 | Workspace Root 与路径安全 | P0 | ⬜ |
| 3 | 只读 Workspace API | P0 | ⬜ |
| 4 | Search API | P0 | ⬜ |
| 5 | Git Read API | P0 | ⬜ |
| 6 | Audit / Trace | P0 | ⬜ |
| 7 | AI-Team Inspect | P1 | ⬜ |
| 8 | 安全 Patch 写入 | P0 | ⬜ |
| 9 | Python / Project Test | P1 | ⬜ |
| 10 | Terminal Policy | P1 | ⬜ |
| 11 | Git Write / Commit | P1 | ⬜ |
| 12 | MCP Client 配置 | P1 | ⬜ |
| 13 | 全面安全回归 | P0 | ⬜ |
| 14 | 性能与稳定性 | P1 | ⬜ |
| 15 | 文档与运维 | P1 | ⬜ |
| 16 | V1 Production Readiness | P0 | ⬜ |

---

# 4. Phase 0：需求、架构与边界冻结

## 4.1 任务

- [ ] 阅读现有 AI-Team 架构
- [ ] 确认现有 workspace isolation 实现
- [ ] 确认现有 capability / permission 模型
- [ ] 确认现有 Host-owned Git boundary
- [ ] 确认现有 ToolInvocation boundary
- [ ] 确认现有 Audit / Trace API
- [ ] 确认现有测试组织方式
- [ ] 确认 Python MCP SDK / transport 方案
- [ ] 确定 MCP server 进程生命周期
- [ ] 确定 stdio 是否作为 V1 默认 transport
- [ ] 明确 MCP Server 只允许访问 workspace root
- [ ] 明确高风险操作需要显式 policy / confirmation

## 4.2 架构决策

必须形成：

```text
MCP Transport
      |
      v
MCP Tool Adapter
      |
      v
AI-Team Canonical Boundary
      |
      +--> Security
      +--> Workspace
      +--> Tool Invocation
      +--> Audit
      |
      v
Host / OS
```

## 4.3 验收

- [ ] 架构文档完成
- [ ] 安全边界文档完成
- [ ] 工具清单冻结
- [ ] 权限矩阵冻结
- [ ] 不存在重复安全模型的设计

---

# 5. Phase 1：MCP 基础运行框架

## 5.1 目标

建立最小可运行 MCP Server。

## 5.2 任务

- [ ] 引入 MCP Python SDK
- [ ] 创建 `mcp/server.py`
- [ ] 实现 server 初始化
- [ ] 实现 stdio transport
- [ ] 实现 server metadata
- [ ] 实现 tool registration
- [ ] 实现统一异常转换
- [ ] 实现 structured tool result
- [ ] 实现日志输出
- [ ] 日志不得污染 stdio MCP protocol channel
- [ ] 增加 server startup / shutdown 生命周期
- [ ] 增加最小 smoke test

## 5.3 第一批工具

第一阶段只注册：

```text
workspace.list
workspace.read
workspace.stat
workspace.search
git.status
git.diff
git.log
ai_team.inspect
```

暂不开放：

```text
workspace.apply_patch
terminal.exec
git.commit
```

## 5.4 验收

```text
MCP Client
    |
    v
Local MCP
    |
    +--> list
    +--> read
    +--> stat
    +--> search
    +--> git status
    +--> git diff
    +--> git log
    +--> inspect
```

全部可以正常调用。

---

# 6. Phase 2：Workspace Root 与路径安全

这是整个项目最高优先级的安全阶段。

## 6.1 配置

支持：

```text
AI_TEAM_WORKSPACE
```

例如：

```text
F:\workspace\_coding_workspace\AI-Team\ai-dev-team
```

## 6.2 任务

- [ ] workspace root 必须是绝对路径
- [ ] 启动时 canonicalize root
- [ ] 检查 root 存在
- [ ] 检查 root 是目录
- [ ] 所有请求路径统一 canonicalize
- [ ] 拒绝 `..` 越界
- [ ] 拒绝绝对路径逃逸
- [ ] 拒绝 UNC 越界
- [ ] 处理 Windows drive letter
- [ ] 处理大小写差异
- [ ] 处理 symlink / junction
- [ ] 防止 TOCTOU 类路径绕过
- [ ] `.git` 目录访问策略明确
- [ ] workspace root 本身访问策略明确

## 6.3 错误语义

所有越界必须统一：

```text
PermissionError
```

不得泄漏：

```text
pathlib.Path.relative_to()
```

等内部实现细节。

## 6.4 测试

必须覆盖：

- [ ] `../`
- [ ] 多级 `../../`
- [ ] Windows 绝对路径
- [ ] 其他 drive
- [ ] UNC path
- [ ] symlink
- [ ] junction
- [ ] root 本身
- [ ] root 下合法路径
- [ ] 不存在路径
- [ ] 文件作为目录
- [ ] 大小写变化

## 6.5 验收标准

任何工具都不能访问：

```text
workspace_root 外部
```

---

# 7. Phase 3：只读 Workspace API

## 7.1 `workspace.list`

输入：

```text
path?: string
```

输出：

```text
{
  "path": "...",
  "entries": [
    {
      "name": "...",
      "type": "file|directory"
    }
  ]
}
```

## 7.2 `workspace.read`

要求：

- [ ] UTF-8 默认
- [ ] 编码错误有明确错误
- [ ] 大文件有大小限制
- [ ] 支持按行读取
- [ ] 可选 start/end range
- [ ] 不允许读取 workspace 外文件
- [ ] 二进制文件默认拒绝或明确标识

## 7.3 `workspace.stat`

返回：

- [ ] 文件/目录类型
- [ ] size
- [ ] modified time
- [ ] relative path

不要泄漏不必要的 OS 信息。

## 7.4 测试

- [ ] 正常文件
- [ ] 空文件
- [ ] Unicode
- [ ] 大文件
- [ ] 目录
- [ ] 不存在
- [ ] 越界
- [ ] 权限拒绝

---

# 8. Phase 4：Search API

## 8.1 `workspace.search`

输入：

```text
query
path?
file_pattern?
max_results?
```

## 8.2 目标

解决：

```text
GitHub Code Search
```

不可用时无法继续开发的问题。

## 8.3 功能

- [ ] 文本搜索
- [ ] 文件过滤
- [ ] 目录过滤
- [ ] 行号返回
- [ ] 匹配文本返回
- [ ] 最大结果数
- [ ] 单文件大小限制
- [ ] 忽略 `.git`
- [ ] 忽略缓存目录
- [ ] 忽略 `.venv`
- [ ] 可配置 ignore rules

## 8.4 安全

Search 也必须经过 workspace boundary。

## 8.5 性能

- [ ] 小项目 benchmark
- [ ] AI-Team 当前仓库 benchmark
- [ ] 大文件处理 benchmark
- [ ] 二进制跳过
- [ ] 不产生无限扫描

## 8.6 验收

典型调用：

```text
workspace.search("supports_tool_continuation")
```

能够定位：

```text
runtime/llm/provider.py
tests/...
```

---

# 9. Phase 5：Git Read API

## 9.1 工具

```text
git.status
git.diff
git.log
git.branch
```

## 9.2 原则

Git 操作必须复用 AI-Team 已有 Host-owned Git boundary。

不得重新创建第二套 Git security implementation。

## 9.3 `git.status`

返回：

- [ ] branch
- [ ] staged
- [ ] modified
- [ ] untracked
- [ ] deleted

## 9.4 `git.diff`

支持：

```text
working tree
staged
specific path
```

## 9.5 `git.log`

支持：

```text
limit
path
```

## 9.6 `git.branch`

支持只读 branch inspection。

## 9.7 验收

可以完整执行：

```text
git.status
git.diff
git.log
git.branch
```

而不需要 GitHub API。

---

# 10. Phase 6：Audit / Trace

所有 MCP 请求必须可以审计。

## 10.1 Audit Record

建议：

```text
timestamp
request_id
tool
operation
relative_path
result
duration_ms
error_type
```

必要时关联：

```text
task_id
agent_id
execution_id
```

## 10.2 任务

- [ ] MCP request ID
- [ ] tool invocation ID
- [ ] duration
- [ ] success/failure
- [ ] policy decision
- [ ] path decision
- [ ] exception category
- [ ] 不记录 secrets
- [ ] 不记录 API keys
- [ ] 不记录完整敏感环境变量

## 10.3 验收

一次：

```text
workspace.read
```

可以追踪：

```text
request
 -> authorization
 -> operation
 -> result
```

---

# 11. Phase 7：AI-Team Inspect

## 11.1 `ai_team.inspect`

目标：让 ChatGPT 一次获得项目状态。

## 11.2 输出

建议包含：

```text
project
version
workspace
branch
git_clean
python_version
test_status
devplan_status
available_capabilities
```

## 11.3 DevPlan

读取：

```text
DevPlan.md
```

但只解析结构，不擅自改变计划状态。

## 11.4 测试状态

可以读取最近一次 MCP 自己执行的测试记录。

## 11.5 验收

能够得到：

```text
Project: AI-Team
Branch: ...
Git: clean/dirty
Tests: ...
DevPlan: ...
```

---

# 12. Phase 8：安全 Patch 写入

这是第一个允许修改源代码的阶段。

## 12.1 工具

```text
workspace.apply_patch
```

## 12.2 原则

优先 patch，不提供：

```text
write_file(entire_content)
```

作为默认 AI 写入接口。

## 12.3 Patch 流程

```text
request patch
      |
      v
path validation
      |
      v
file validation
      |
      v
patch validation
      |
      v
apply
      |
      v
git diff
      |
      v
audit
```

## 12.4 必须防止

- [ ] workspace escape
- [ ] patch 修改 `.git`
- [ ] patch 修改 MCP policy
- [ ] patch 删除大量文件
- [ ] patch 超大
- [ ] patch 目标文件突然变化
- [ ] patch fuzz 导致非预期修改

## 12.5 Optimistic Concurrency

建议支持：

```text
expected_sha256
```

流程：

```text
read file
   |
calculate hash
   |
patch(expected_hash)
   |
hash mismatch?
   |
  yes -> reject
```

防止 AI 基于旧代码覆盖新代码。

## 12.6 验收

成功：

```text
read
 -> patch
 -> diff
```

失败：

```text
hash mismatch
 -> no modification
```

---

# 13. Phase 9：Python / Project Test

## 13.1 `python.run`

不要默认接受任意 shell string。

优先：

```text
args: list[str]
```

例如：

```text
python.run(
  args=["-m", "pytest", "tests/test_x.py", "-q"]
)
```

## 13.2 `project.test`

提供高层接口：

```text
project.test(target="tests/test_x.py")
project.test(target="full")
```

## 13.3 Python executable

优先使用项目 venv：

```text
.venv\Scripts\python.exe
```

同时做启动时检查。

## 13.4 测试限制

- [ ] timeout
- [ ] stdout limit
- [ ] stderr limit
- [ ] process count policy
- [ ] working directory固定
- [ ] environment allowlist
- [ ] secrets 不自动注入

## 13.5 验收

能够执行：

```text
targeted test
full regression
```

并得到：

```text
exit_code
duration
stdout
stderr
summary
```

---

# 14. Phase 10：Terminal Policy

这是高风险阶段。

## 14.1 原则

`terminal.exec` 默认关闭。

只有明确启用 policy 后才能使用。

## 14.2 Allowlist

初期允许：

```text
python
pytest
git
```

以及必要的项目脚本。

## 14.3 禁止

默认拒绝：

```text
del
rmdir
format
diskpart
reg
shutdown
powershell 下载执行
cmd /c 任意拼接
curl | ...
wget | ...
```

同时考虑：

```text
&&
||
;
|
>
>>
```

等 shell composition。

## 14.4 推荐实现

优先：

```text
executable + args
```

而不是：

```text
raw shell string
```

## 14.5 Windows

必须测试：

- [ ] cmd
- [ ] PowerShell
- [ ] `.exe`
- [ ] `.bat`
- [ ] `.ps1`
- [ ] path quoting
- [ ] Unicode path

## 14.6 验收

允许：

```text
python -m pytest ...
git status
```

拒绝危险命令。

---

# 15. Phase 11：Git Write / Commit

## 15.1 第一原则

读 Git：

```text
自动允许
```

写 Git：

```text
显式 policy
```

## 15.2 工具

```text
git.stage
git.unstage
git.commit
```

## 15.3 `git.commit`

默认要求 confirmation。

## 15.4 禁止 V1

```text
git push --force
git reset --hard
git clean -fd
rebase destructive operations
```

除非以后建立独立高风险 capability。

## 15.5 Commit 前检查

自动：

```text
git diff
git status
```

可选：

```text
targeted test
```

## 15.6 验收

完整流程：

```text
patch
 -> diff
 -> test
 -> commit
```

---

# 16. Phase 12：MCP Client 配置

## 16.1 Windows 启动方式

建议提供：

```text
scripts/run_mcp_bridge.ps1
scripts/run_mcp_bridge.cmd
```

## 16.2 配置

明确：

```text
workspace root
python executable
log level
policy profile
audit location
```

## 16.3 MCP Client

提供客户端配置示例。

要求：

- [ ] stdio 启动
- [ ] workspace root 显式配置
- [ ] 不依赖当前 shell working directory
- [ ] 启动失败有明确错误
- [ ] 日志可定位

## 16.4 验收

重启电脑后仍可稳定启动 MCP。

---

# 17. Phase 13：全面安全回归

## 17.1 Path Security

- [ ] 所有工具统一走 path boundary
- [ ] 所有 escape 测试通过
- [ ] symlink/junction 测试通过
- [ ] Windows path 测试通过

## 17.2 Command Security

- [ ] allowlist
- [ ] denylist
- [ ] shell injection
- [ ] argument injection
- [ ] redirection
- [ ] pipeline
- [ ] environment injection

## 17.3 MCP Protocol

- [ ] malformed request
- [ ] missing arguments
- [ ] invalid types
- [ ] oversized request
- [ ] unknown tool
- [ ] tool exception
- [ ] server restart

## 17.4 Audit

- [ ] 每个敏感操作有 audit
- [ ] 失败也有 audit
- [ ] 不泄露 secret

## 17.5 AI-Team Regression

必须运行：

```text
pytest -q
```

并确保：

```text
existing tests == unchanged behavior
```

---

# 18. Phase 14：性能与稳定性

## 18.1 Benchmark

测量：

```text
workspace.read latency
workspace.search latency
git.status latency
git.diff latency
project.test overhead
MCP request overhead
```

## 18.2 Search

重点测试：

```text
100 files
1,000 files
10,000 files
large file
binary files
```

## 18.3 长时间稳定性

执行：

```text
1000 requests
```

观察：

- [ ] memory growth
- [ ] file descriptor
- [ ] process leak
- [ ] latency degradation
- [ ] audit growth

## 18.4 验收

MCP overhead 不得明显影响 AI-Team 本身测试与 benchmark。

---

# 19. Phase 15：文档与运维

## 19.1 文档

建立：

```text
docs/mcp/architecture.md
docs/mcp/security.md
docs/mcp/client-setup.md
```

## 19.2 必须记录

- [ ] 安装方式
- [ ] 启动方式
- [ ] 配置
- [ ] 工具清单
- [ ] 权限矩阵
- [ ] 安全模型
- [ ] 故障排查
- [ ] Windows 注意事项
- [ ] 日志位置
- [ ] audit 查询方式

## 19.3 Troubleshooting

覆盖：

```text
MCP 无法启动
workspace 不存在
权限错误
pytest 失败
Git 错误
stdio 协议错误
client 无法连接
```

---

# 20. Phase 16：V1 Production Readiness

最终执行：

```text
security regression
extension boundary regression
observability regression
persistence/recovery regression
full regression
MCP smoke test
MCP security test
MCP performance test
```

## 20.1 V1 Gate

必须满足：

- [ ] Workspace escape = 0
- [ ] Command policy bypass = 0
- [ ] Audit loss = 0
- [ ] Existing AI-Team regression = 0 failures
- [ ] MCP contract tests = 100% pass
- [ ] Server restart recovery = pass
- [ ] Git boundary = pass
- [ ] Patch concurrency = pass
- [ ] Performance threshold = pass
- [ ] Documentation = complete

最终状态：

```text
mcp_bridge_v1=passed
```

---

# 21. 工具权限矩阵

| Tool | Read | Write | Execute | Git | 默认 |
|---|---:|---:|---:|---:|---|
| workspace.list | ✓ | - | - | - | ON |
| workspace.read | ✓ | - | - | - | ON |
| workspace.stat | ✓ | - | - | - | ON |
| workspace.search | ✓ | - | - | - | ON |
| git.status | ✓ | - | - | ✓ | ON |
| git.diff | ✓ | - | - | ✓ | ON |
| git.log | ✓ | - | - | ✓ | ON |
| git.branch | ✓ | - | - | ✓ | ON |
| ai_team.inspect | ✓ | - | - | - | ON |
| workspace.apply_patch | ✓ | ✓ | - | - | OFF → Phase 8 |
| python.run | ✓ | - | ✓ | - | OFF → Phase 9 |
| project.test | ✓ | - | ✓ | - | OFF → Phase 9 |
| terminal.exec | ✓ | potentially | ✓ | potentially | OFF |
| git.stage | - | ✓ | - | ✓ | OFF |
| git.commit | - | ✓ | - | ✓ | OFF |

---

# 22. 推荐的最终工具分类

```text
READ
├── workspace.list
├── workspace.read
├── workspace.stat
├── workspace.search
├── git.status
├── git.diff
├── git.log
└── git.branch

WRITE
├── workspace.apply_patch
├── git.stage
└── git.commit

EXECUTE
├── python.run
├── project.test
└── terminal.exec

AI-TEAM
└── ai_team.inspect
```

---

# 23. MCP 与 AI-Team 现有架构的关系

必须保持：

```text
             MCP Client
                  |
                  v
            Local MCP Bridge
                  |
                  v
       +------------------------+
       | AI-Team Canonical APIs |
       +------------------------+
          |       |       |
          v       v       v
      Security  Tools   Audit
          |
          v
      Workspace
          |
          v
        Host
```

不能形成：

```text
MCP
 |
 +-- 自己的 Security
 |
 +-- 自己的 Tool Registry
 |
 +-- 自己的 Git boundary
 |
 +-- 自己的 Audit
 |
 +-- 自己的 Workspace boundary
```

否则长期一定会产生行为分叉。

---

# 24. 与 AI-Team DevPlan 的协同

MCP Bridge 开发过程中：

- [ ] 不修改 AI-Team 原有 DevPlan 阶段状态，除非 MCP 本身已经纳入正式开发计划
- [ ] MCP 自己使用 `mcp_bridge_taskplan.md`
- [ ] 每个 Phase 完成后记录 commit
- [ ] 每个 Phase 记录测试结果
- [ ] 每个安全修复记录 regression test
- [ ] 每个架构决策记录原因
- [ ] 性能优化必须有 benchmark evidence
- [ ] 不以“测试通过”作为唯一完成标准

推荐每个阶段记录：

```text
Phase:
Date:
Commit:
Tests:
Security:
Performance:
Known limitations:
Decision:
```

---

# 25. 推荐 Git 提交策略

每个逻辑阶段一个 commit。

例如：

```text
feat: add local mcp bridge skeleton
feat: add workspace boundary
feat: add workspace read tools
feat: add workspace search
feat: add host git read bridge
feat: add mcp audit
feat: add ai team inspect
feat: add safe patch tool
feat: add project test bridge
feat: add terminal capability policy
feat: add git write capability
docs: add local mcp setup guide
test: add mcp security regression suite
```

不要把：

```text
security
feature
refactor
docs
tests
```

全部塞进一个大 commit。

---

# 26. 推荐开发顺序

严格按照：

```text
Phase 0
  ↓
Phase 1
  ↓
Phase 2
  ↓
Phase 3
  ↓
Phase 4
  ↓
Phase 5
  ↓
Phase 6
  ↓
Phase 7
  ↓
Phase 8
  ↓
Phase 9
  ↓
Phase 10
  ↓
Phase 11
  ↓
Phase 12
  ↓
Phase 13
  ↓
Phase 14
  ↓
Phase 15
  ↓
Phase 16
```

其中最重要的安全 Gate：

```text
Phase 2 ── Path Security
     ↓
Phase 8 ── Write Security
     ↓
Phase 10 ─ Command Security
     ↓
Phase 11 ─ Git Write Security
     ↓
Phase 13 ─ Full Security Regression
```

---

# 27. 第一版 MVP 定义

MVP 不要求全部功能。

MVP 只需要：

```text
workspace.list
workspace.read
workspace.stat
workspace.search
git.status
git.diff
git.log
ai_team.inspect
```

并达到：

```text
MCP client
    ↓
Local MCP
    ↓
AI-Team workspace
```

稳定工作。

MVP 验收：

- [ ] 可以读取 AI-Team 源码
- [ ] 可以搜索整个项目
- [ ] 可以读取 DevPlan.md
- [ ] 可以查看 Git 状态
- [ ] 可以查看 Git diff
- [ ] 可以查看 Git log
- [ ] 可以获取项目状态
- [ ] workspace 外访问全部拒绝
- [ ] AI-Team 原有测试全部通过
- [ ] MCP smoke tests 全部通过

---

# 28. V1 最终使用场景

完成全部计划后，典型开发任务应该可以直接执行：

```text
1. ai_team.inspect
2. git.status
3. workspace.search
4. workspace.read
5. 分析问题
6. workspace.apply_patch
7. git.diff
8. project.test(targeted)
9. workspace.search
10. workspace.read
11. project.test(full)
12. ai_team.inspect
13. git.diff
14. git.commit
```

最终形成：

```text
                 ┌───────────────┐
                 │   ChatGPT     │
                 └───────┬───────┘
                         │
                         ▼
                 ┌───────────────┐
                 │ Local MCP     │
                 │ Bridge        │
                 └───────┬───────┘
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
        AI-Team Boundary       Host Git Boundary
              │                     │
              └──────────┬──────────┘
                         ▼
                  Local Workspace
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
            Code       Tests       Git
```

---

# 29. 完成定义 Definition of Done

MCP Bridge 只有在下面全部满足时才认为 V1 完成：

- [ ] 所有核心工具都有 schema contract
- [ ] 所有工具都有单元测试
- [ ] 所有路径操作通过统一 boundary
- [ ] 所有高风险操作有 capability
- [ ] 所有写操作可审计
- [ ] 所有命令执行有 policy
- [ ] Git 操作不绕过 Host-owned Git boundary
- [ ] Patch 支持并发保护
- [ ] MCP protocol smoke test 通过
- [ ] Security regression 通过
- [ ] AI-Team full regression 通过
- [ ] Performance regression 通过
- [ ] Windows 11 验证通过
- [ ] MCP Client 配置文档完成
- [ ] 故障排查文档完成
- [ ] Git 工作树状态干净
- [ ] 最终 commit 可追溯
- [ ] `mcp_bridge_v1=passed`

---

# 30. 后续扩展路线（V2+）

V1 稳定后再考虑：

- [ ] benchmark 专用 MCP 工具
- [ ] production readiness MCP 工具
- [ ] security regression MCP 工具
- [ ] task-level execution
- [ ] dependency graph inspection
- [ ] runtime trace inspection
- [ ] evidence lineage inspection
- [ ] persistence/recovery inspection
- [ ] Reviewer 专用 MCP view
- [ ] Architect 专用 MCP view
- [ ] Developer 专用 MCP view
- [ ] Tester 专用 MCP view
- [ ] multi-workspace support
- [ ] remote development workspace
- [ ] containerized workspace
- [ ] MCP session persistence
- [ ] fine-grained capability profiles
- [ ] human approval workflow
- [ ] signed audit records

---

# 31. 当前执行入口

首次开始开发时，不直接实现所有工具。

第一轮只执行：

```text
Phase 0
Phase 1
Phase 2
```

然后验收：

```text
MCP server 能启动
+
workspace boundary 正确
+
MCP smoke tests 全部通过
+
AI-Team 原有 pytest 全部通过
```

确认这一基础层稳定后，再进入：

```text
Phase 3
Phase 4
Phase 5
Phase 6
Phase 7
```

即先完成完整的 **Read-only MCP MVP**。

---

# 32. 进度记录模板

每完成一个 Phase，在本文件对应章节后补充：

```text
### Progress Record

- 状态：完成 / 进行中 / 阻塞
- 完成日期：
- Commit：
- 测试命令：
- 测试结果：
- 安全验证：
- 性能验证：
- 已知问题：
- 下一步：
```

如果某 Phase 因外部依赖阻塞，必须记录：

```text
阻塞原因：
影响范围：
已验证内容：
临时方案：
是否允许进入下一 Phase：
```

---

# 33. 当前状态

```text
Project: AI-Team Local MCP Bridge

Plan:
mcp_bridge_taskplan.md

Current Phase:
Phase 0 — 未开始

Completed:
None

Next Action:
完成 Phase 0 架构与边界审查

MVP:
未开始

V1:
未开始

Production Readiness:
未开始
```
