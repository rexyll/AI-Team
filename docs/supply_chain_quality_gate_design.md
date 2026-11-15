# T21.7 供应链与质量门禁现状评审

日期：2026-11-15  
基线：`main`，提交 `0bf336745a900c523e54dbb93f5951817f99bb42`

## 结论

T21.7 尚未完成。仓库已有部分质量基线和离线依赖声明检查，但尚无可验证的覆盖率阈值、依赖锁文件/哈希闭环、标准化 SBOM、漏洞数据库扫描或许可证策略门禁。不能把现有性能回归测试或 requirements 直接 pin 描述为完整供应链治理。

## 已有能力（经代码核对）

| 领域 | 当前实现 | 证据与边界 |
|---|---|---|
| 性能回归 | workflow event 性能/吞吐与扩展性测试，规模覆盖 32/128/512 个事件或任务 | `tests/test_workflow_event_performance_contract.py`、`tests/test_workflow_event_performance_regression_contract.py`；断言为宽松相对退化保护，不是跨机器绝对 SLA，也没有独立 benchmark 历史基线 |
| 依赖声明 | 顶层输入 `requirements.txt` / `requirements-dev.txt`；四份 Python 3.14 平台锁包含完整解析依赖与 SHA-256 hashes | Linux/Windows 分别解析；CI 使用对应开发锁与 `--require-hashes`；顶层输入本身仍不是安装锁 |
| 离线依赖检查 | `runtime/dependency_scan.py` 解析交付物 requirements，检查未声明第三方 import，并记录 vulnerability lookup unavailable | 不是 SPDX/CycloneDX SBOM；requirements parser 不解析完整 PEP 508/requirements include 语义；不会查询漏洞库或许可证 |
| 安全回归 | CI 单独运行 `tools/run_security_regression.py` | 安全测试覆盖不等于依赖漏洞/许可证扫描 |
| CI | Ubuntu Python 3.14 全量与安全回归；Windows production terminal smoke | pip 25.3 固定；分别消费 Linux/Windows 开发锁并强制哈希；仍没有 coverage 上传/阈值或供应链扫描 job |

## 已确认缺口

1. **覆盖率门槛**：仓库未声明 coverage 工具、统一测量范围、排除规则或阈值。应先生成可复现基线，检查关键模块覆盖，再按风险分层设置阈值；不能先拍脑袋设置数字。
2. **性能预算**：现有测试提供相对扩展性保护，但没有稳定 runner 上的基线采集、历史比较、预算版本化和噪声处理。当前测试不得被包装成性能 SLA。
3. **依赖可复现性**：T21.7.1 已补齐 Python 3.14 Linux/Windows 生产与开发锁，CI 已固定 pip 25.3 并强制哈希安装。后续仍需为其他 Python 版本/平台（若支持矩阵扩展）生成独立锁，并维护受控 resolver 更新策略。
4. **标准化 SBOM**：现有扫描输出是内部摘要，不含标准格式、组件 PURL、许可证表达式、来源/构建元数据，也未覆盖所有分发依赖来源。
5. **漏洞与许可证**：没有数据库查询、漏洞匹配或许可证 allow/deny policy。当前网络出口策略为 deny-by-default；不得在应用运行时偷偷联网，也不得把 scanner unavailable 记作 clean。
6. **制品来源**：尚未形成依赖锁、SBOM、构建来源、测试证据和发布制品摘要之间的统一可验证绑定。

## 推荐实施顺序

### T21.7.1 可复现依赖输入
- 盘点生产、开发、可选 extra 与平台条件依赖。
- 生成解释器/平台范围明确的完整锁文件，优先采用哈希校验；更新依赖必须有显式审查流程。
- CI 使用锁文件安装，不再依赖无约束的临时解析结果；升级 pip 等构建工具也应固定版本或记录受控更新策略。
- 验收：干净环境可离线/受控安装；缺包、哈希不符、平台不匹配 fail-closed。

#### T21.7.1 锁文件生成与验收细则（实施决策）

当前 CI 同时运行 Ubuntu 与 Windows，解释器固定为 Python 3.14。由于依赖可能发布平台专属 wheel，单一在 Linux 上解析的哈希集合不能未经验证就视为 Windows 可安装集合。因此锁定流程应按 CI 运行平台分别解析，而不是复制一份 Linux 输出给所有平台。

- 输入清单与解析输出分离：保留可审查的生产/开发顶层输入；锁文件由 resolver 生成，不手工维护传递依赖版本。
- 在 Ubuntu Python 3.14 与 Windows Python 3.14 上分别生成并验证对应锁文件；锁文件应包含完整传递依赖、环境 marker 和允许安装文件的哈希。
- 生产与开发依赖的边界保持清晰；开发锁可以引用/包含生产依赖，但 CI 的测试环境必须由一份完整、可校验的开发锁安装，避免两次无约束解析。
- resolver 与 bootstrap 工具（pip、pip-tools）自身也必须固定版本；具体版本须在生成任务中实际安装并验证后再提交，不在设计文档中猜测。
- 生成任务应输出可审阅的 lock diff 和构建环境元数据（Python、OS、resolver 版本、输入清单摘要）；生成过程不自动提交或升级依赖。
- CI 消费端使用 `pip install --require-hashes -r <platform-lock>`；不得先无约束升级 pip。锁文件缺项、哈希不匹配、平台不匹配或 resolver 失败均应阻断。
- **已验收（2026-11-15）**：GitHub Actions run `43698973027` 在 Ubuntu/Windows Python 3.14 分别生成生产/开发锁；每个平台都在全新 venv 中对两份锁执行 `pip install --require-hashes` 成功。四份锁已提交到仓库根目录（`requirements-linux-py314.lock`、`requirements-dev-linux-py314.lock`、`requirements-windows-py314.lock`、`requirements-dev-windows-py314.lock`）。CI 已固定 pip 25.3 并按平台使用开发锁；迁移后的全量回归、安全回归和 Windows smoke 均通过，见 CI run `43699240235`。
- 锁生成工作流固定 pip 25.3 / pip-tools 7.5.2，顶层输入变更时重新解析；只有两个平台候选均通过 clean install 后，聚合 job 才将锁文件提交到 main。
- 依赖更新仍需显式修改顶层输入并审查锁文件 diff；禁止手工猜测传递版本或哈希。

### T21.7.2 标准化 SBOM 与制品绑定
- 从实际锁定安装集合和交付物依赖清单生成 SPDX 或 CycloneDX JSON，组件身份使用 PURL，无法确定的许可证/来源明确标为 unknown。
- SBOM 纳入交付清单并与 artifact digest、lock digest、scanner/tool version 绑定。
- 验收：格式/schema 校验、确定性输出、缺失组件/伪造摘要/未知字段测试。

### T21.7.3 覆盖率与性能预算
- 在固定 Python 3.14 CI 环境采集覆盖率基线，按模块风险定义阈值；新增代码不得通过缩小测量范围规避门槛。
- 将现有性能测试定位为结构/扩展性回归；如增加绝对预算，必须在受控 runner 上采集多次样本、记录环境和分位数，并对噪声/基线变更留痕。
- 压力测试保持 opt-in，默认 CI 有界；不可因超时或资源压力静默跳过。

### T21.7.4 漏洞与许可证策略
- 仅在 CI 明确声明的网络出口白名单中运行锁文件扫描；应用交付运行时继续保持无隐式网络查询。
- scanner 版本、数据库更新时间、扫描目标、豁免责任人/期限与结果必须入证据；scanner unavailable、数据库过期、解析失败不能等同无漏洞。
- 许可证策略按项目配置；未知许可证和冲突必须显式报告，不可默认批准。

## 安全与范围约束

- 不添加自动修复/自动升级依赖；扫描只提供证据与门禁结论。
- 不引入隐式公网出口；所有在线扫描只能在 CI 显式白名单步骤中执行。
- 不把工具不可用、无数据库或未识别许可证降级为 clean。
- 不用任意覆盖率百分比或机器相关的绝对性能数字作为门槛。
- 每个子节点独立提交到 main，并在 CI 全绿后记录完成；未完成的子节点保持未勾选。

## 与 T21.6.3 的边界

T21.6.3 的 reconciliation mutation 仍受可信 host 身份认证、独立双人审批、独立完整性锚和真实 provider/route read-back 约束。当前只有数据契约与设计文档，未实现安全执行接口；Local Docker rollback 继续 unsupported。供应链工作不会改变该状态。
