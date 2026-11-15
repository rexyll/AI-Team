# T21.7 供应链与质量门禁现状评审

日期：2026-11-15  
基线：`main`，提交 `0bf336745a900c523e54dbb93f5951817f99bb42`

## 结论

T21.7 尚未整体完成。T21.7.1 已完成 Python 3.14 Linux/Windows 生产/开发依赖锁与哈希安装闭环；T21.7.2 已完成 CycloneDX 1.6 SBOM/provenance；T21.7.3 已落地 line/branch coverage 基线与模块门槛，但固定硬件绝对性能预算仍待受控 runner；T21.7.4 漏洞数据库扫描和许可证策略门禁已完成；项目许可证现采用 PolyForm Noncommercial 1.0.0 + PolyForm Small Business 1.0.0 双许可方案，明确授予任何个人免费非商业使用，并为符合条件的小企业保留 PolyForm Small Business 1.0.0 商业许可路径。不能把现有性能回归测试或 requirements 顶层 pin 描述为完整供应链治理。

## 已有能力（经代码核对）

| 领域 | 当前实现 | 证据与边界 |
|---|---|---|
| 性能回归 | workflow event 性能/吞吐与扩展性测试，规模覆盖 32/128/512 个事件或任务；10k-task 与真实 Provider 基准 opt-in | `tests/test_workflow_event_performance_contract.py`、`tests/test_workflow_event_performance_regression_contract.py`；断言为宽松相对退化保护，不是跨机器绝对 SLA；没有固定性能 runner，绝对预算暂缓 |
| 依赖声明 | 顶层输入 `requirements.txt` / `requirements-dev.txt`；四份 Python 3.14 平台锁包含完整解析依赖与 SHA-256 hashes | Linux/Windows 分别解析；CI 使用对应开发锁与 `--require-hashes`；顶层输入本身仍不是安装锁 |
| 离线依赖检查 | `runtime/dependency_scan.py` 解析交付物 requirements，检查未声明第三方 import，并记录 vulnerability lookup unavailable | 不是 SPDX/CycloneDX SBOM；requirements parser 不解析完整 PEP 508/requirements include 语义；不会查询漏洞库或许可证 |
| 安全回归 | CI 单独运行 `tools/run_security_regression.py` | 安全测试覆盖不等于依赖漏洞/许可证扫描 |
| CI | Ubuntu Python 3.14 全量、安全回归与独立 line/branch coverage 门禁；Windows production terminal smoke | pip 25.3 固定；分别消费 Linux/Windows 开发锁并强制哈希；覆盖率 JSON/HTML artifact 归档并执行模块风险门槛；漏洞/许可证扫描 job 尚未接入 |

## 已确认缺口

1. **性能预算**：现有测试提供相对扩展性保护，但没有稳定 runner 上的基线采集、历史比较、预算版本化和噪声处理。当前测试不得被包装成性能 SLA；无固定 runner 时不设绝对预算。
2. **依赖可复现性**：T21.7.1 已补齐 Python 3.14 Linux/Windows 生产与开发锁，CI 已固定 pip 25.3 并强制哈希安装。后续仍需为其他 Python 版本/平台（若支持矩阵扩展）生成独立锁，并维护受控 resolver 更新策略。
4. **漏洞与许可证**：尚未实现漏洞数据库查询、漏洞匹配或许可证 allow/deny policy。当前网络出口策略为 deny-by-default；不得在应用运行时偷偷联网，也不得把 scanner unavailable 记作 clean。

## 推荐实施顺序

### T21.7.1 可复现依赖输入
- 盘点生产、开发、可选 extra 与平台条件依赖。
- 生成解释器/平台范围明确的完整锁文件，优先采用哈希校验；更新依赖必须有显式审查流程。
- CI 使用锁文件安装，不再依赖无约束的临时解析结果；升级 pip 等构建工具也应固定版本或记录受控更新策略。
- 验收：干净环境通过受控 PyPI index 与 `--require-hashes` 安装；缺包、哈希不符、平台不匹配 fail-closed。当前已在 Ubuntu/Windows Python 3.14 clean venv 验证。

#### T21.7.1 锁文件生成与验收细则（实施决策）

当前 CI 同时运行 Ubuntu 与 Windows，解释器固定为 Python 3.14。由于依赖可能发布平台专属 wheel，单一在 Linux 上解析的哈希集合不能未经验证就视为 Windows 可安装集合。因此锁定流程应按 CI 运行平台分别解析，而不是复制一份 Linux 输出给所有平台。

- 输入清单与解析输出分离：保留可审查的生产/开发顶层输入；锁文件由 resolver 生成，不手工维护传递依赖版本。
- 在 Ubuntu Python 3.14 与 Windows Python 3.14 上分别生成并验证对应锁文件；锁文件应包含完整传递依赖、环境 marker 和允许安装文件的哈希。
- 生产与开发依赖的边界保持清晰；开发锁可以引用/包含生产依赖，但 CI 的测试环境必须由一份完整、可校验的开发锁安装，避免两次无约束解析。
- resolver 与 bootstrap 工具（pip、pip-tools）自身也必须固定版本；具体版本须在生成任务中实际安装并验证后再提交，不在设计文档中猜测。
- 生成任务输出平台独立 artifacts（lock diff 与 Python、OS、resolver 版本元数据）；只有 Linux/Windows 候选都通过 clean `--require-hashes` 安装后，聚合 job 才将四份锁文件提交到 main。该流程不自动修改顶层依赖输入，也不自动升级依赖。
- CI 消费端使用 `pip install --require-hashes -r <platform-lock>`；不得先无约束升级 pip。锁文件缺项、哈希不匹配、平台不匹配或 resolver 失败均应阻断。
- **已验收（2026-11-15）**：GitHub Actions run `43698973027` 在 Ubuntu/Windows Python 3.14 分别生成生产/开发锁；每个平台都在全新 venv 中对两份锁执行 `pip install --require-hashes` 成功。四份锁已提交到仓库根目录（`requirements-linux-py314.lock`、`requirements-dev-linux-py314.lock`、`requirements-windows-py314.lock`、`requirements-dev-windows-py314.lock`）。CI 已固定 pip 25.3 并按平台使用开发锁；迁移后的全量回归、安全回归和 Windows smoke 均通过，见 CI run `43699240235`。
- 锁生成工作流固定 pip 25.3 / pip-tools 7.5.2，顶层输入变更时重新解析；只有两个平台候选均通过 clean install 后，聚合 job 才将锁文件提交到 main。
- 依赖更新仍需显式修改顶层输入并审查锁文件 diff；禁止手工猜测传递版本或哈希。

### T21.7.2 标准化 SBOM 与制品绑定
- 从实际锁定安装集合和交付物依赖清单生成 SPDX 或 CycloneDX JSON，组件身份使用 PURL，无法确定的许可证/来源明确标为 unknown。
- SBOM 纳入交付清单并与 artifact digest、lock digest、scanner/tool version 绑定。
- 验收：格式/schema 校验、确定性输出、缺失组件/伪造摘要/未知字段测试。

#### T21.7.2 SBOM 与制品证据绑定设计（实施决策）

现状边界：`runtime/dependency_scan.py` 当前的 `sbom` 字段只是对交付物顶层 `requirements.txt` 的内部摘要；它不生成 SPDX/CycloneDX，不包含 PURL、分发文件哈希、依赖闭包或许可证结论。交付流水线在 DocWriter 阶段调用该扫描，之后才生成 `DELIVERY_MANIFEST.md` 与 ZIP，因此需要明确 SBOM 与最终制品摘要之间的顺序。

采用 CycloneDX 1.6 JSON，约定如下：

- 交付目录内生成 `DELIVERY_SBOM.cdx.json`。优先从交付物显式指定的平台 lock 解析完整组件、版本、PyPI PURL 和 lock 中允许的 SHA-256 分发文件哈希；只有顶层 requirements 时允许生成 declared-only SBOM，但必须标记 `partial`，不得声称包含传递依赖。存在但格式错误/缺哈希的 lock 必须 fail-closed，不得退回 requirements 伪装完整。
- 每个组件的许可证当前无法可靠推断时，使用自定义 property 明确标记 `license-status=unknown`；不填入猜测许可证。SBOM metadata properties 记录 dependency scope、requirements SHA-256、lock SHA-256（若存在）和 build-evidence SHA-256。
- 在交付目录生成规范化的 `DELIVERY_BUILD_EVIDENCE.json`，只包含 integration、QA、安全、acceptance 等结构化结果摘要，不复制原始日志、提示词或秘密；其 SHA-256 被 SBOM 引用。
- ZIP 的 SHA-256 不能写入 ZIP 内的 SBOM，否则形成自引用循环。故在 ZIP 完成后，ZIP 同级生成 `<archive>.provenance.json` sidecar，绑定 archive SHA-256、ZIP 内 SBOM/manifest/build-evidence/lock 成员 SHA-256。该 sidecar 是可验证的完整性记录，不带签名，不声称来源真实性或不可抵赖。
- SBOM 与 build evidence 在 manifest 生成前写入交付目录，因此随 ZIP 一起交付并受 manifest 校验；provenance sidecar 在 ZIP 生成后输出，不加入自身所描述的 ZIP。
- 验收覆盖 CycloneDX 结构字段、PURL/name normalization、lock hash 全量保留、缺 lock 的 partial 标记、坏 lock fail-closed、确定性输出、archive/成员篡改检测与 build-evidence digest 绑定。漏洞数据库和许可证策略扫描仍归 T21.7.4，不在此节点伪装成已执行。

**实施与验收结果（2026-11-15）**：`runtime/delivery_sbom.py` 已接入 `core/project_orchestrator.py`。交付根目录生成 `DELIVERY_BUILD_EVIDENCE.json` 与 `DELIVERY_SBOM.cdx.json`，之后由现有 manifest/ZIP 纳入交付；ZIP 旁生成 `.provenance.json` sidecar。无锁项目明确返回 `partial`；不支持的 requirements include/direct URL 和坏锁均拒绝生成。四份仓库真实 lock（Linux/Windows × production/dev）均通过组件解析测试。CI run `43700797699` 全绿：2507 passed / 10 skipped，security 234 passed / 9 skipped，Windows smoke 1 passed。sidecar 无签名，当前只提供摘要完整性校验；许可证状态保持 unknown，漏洞扫描仍未执行。
### T21.7.3 覆盖率与性能预算
- 在固定 Python 3.14 CI 环境采集 line + branch coverage 基线，按模块风险定义阈值；新增代码不得通过缩小测量范围规避门槛。
- 覆盖率工具 `coverage.py` 纳入开发依赖并由 Linux/Windows Python 3.14 hash lock 固定；CI 新增独立 `coverage-baseline` job，上传 JSON/HTML/metadata artifact（保留 30 天）。测量范围为 `agents, core, integration, runtime, security, tools`。独立覆盖率测量排除 6 个机器时间敏感 benchmark/performance 测试文件，避免 instrumentation 改变吞吐/并行断言；这些测试仍由原有全量 regression job 正常执行，不是跳过测试。
- 已验证 coverage artifact（run `43704277710`，提交 `dab1d7f`，artifact `14158465325`）测得总 line coverage 84.40%（15,795/17,991 statements）、branch coverage 74.99%（4,861/6,482 branches）。对应 CI 全绿：全量回归 2,526 passed / 10 skipped，覆盖率测量 2,506 passed / 10 skipped，安全回归 237 passed / 9 skipped，Windows smoke 1 passed。coverage source 排除 6 个机器时间敏感 benchmark 测试文件和 3 个 CI-only helper source；helper 的单元测试仍执行。此前引入 coverage 后发现开发 lock 组件数断言过时（Linux 30→31、Windows 31→32），已更新为当前四份锁的真实组件数量，并在该全绿 run 中复验。
- 按首次测量设置保守的模块风险门槛，配置位于 `config/coverage_thresholds.json`，由 `tools/check_coverage_thresholds.py` 对 coverage JSON 聚合并 fail-closed（缺失/新增未配置模块均失败）：

  | 模块 | 初始 line | 初始 branch | 最低 line | 最低 branch |
  |---|---:|---:|---:|---:|
  | agents | 86.68% | 74.32% | 80% | 68% |
  | core | 90.05% | 74.66% | 85% | 68% |
  | runtime | 88.67% | 75.70% | 83% | 70% |
  | security | 74.02% | 66.22% | 70% | 60% |
  | tools | 67.92% | 63.56% | 65% | 58% |

- 门槛是相对当前实测基线留出波动余量的模块底线，不是声称这些数值代表充分测试；后续应优先补强低覆盖高风险路径（例如 `security/process_sandbox.py`、`tools/terminal.py`），并在基线变化时审查阈值变更。暂不使用单一全局百分比。覆盖率测量明确排除 6 个机器时间敏感 benchmark 测试文件和 3 个 CI-only helper source（`tools/check_coverage_thresholds.py`、`tools/check_trivy_license_policy.py`、`tools/check_osv_db_freshness.py`）；helper 对应的 unit tests 仍在全量 regression/coverage pytest 执行中运行，只是不计入产品模块的 coverage 分母。
- 性能现状复核：`tests/test_workflow_event_performance_contract.py` 与 `tests/test_workflow_event_performance_regression_contract.py` 检查任务/事件语义、吞吐随规模扩展的宽松比例；`tests/test_large_project_benchmark.py` 在默认 CI 中运行确定性 1,000/5,000-task 结构与 5,000-task 测量。`benchmarks/large_project_benchmark.py` 的 10,000-task 全量基准通过脚本入口 opt-in；`benchmarks/real_developer/live.py` 仅在显式调用时构造真实 Provider executor，不会被默认 CI 隐式触发。`benchmarks/multi_developer/statistics.py` 已提供重复样本 mean/median/stddev/CV 描述统计。
- 现有性能测试定位为结构/扩展性回归，使用宽松比例/正确性断言，不是绝对 SLA。GitHub-hosted runner 不视为受控性能硬件；当前没有已配置的固定 self-hosted performance runner，因此本节点不设机器相关绝对时间/吞吐预算。后续需在固定 runner 上多次采样，记录 CPU/OS/Python/负载、median/p95 与波动，再决定是否设置门槛。
- 压力测试保持 opt-in，默认 CI 有界；不可因超时或资源压力静默跳过。


#### T21.7.4 扫描工具与网络边界（实施决策）

- 采用混合扫描器：`pip-audit==2.10.1` 对 production hash lock 使用 OSV API 做漏洞查询（`--no-deps --disable-pip --require-hashes --strict`，不重新解析依赖）；Trivy `0.76.2` 只对独立 production venv 做离线 license scan。初次验证发现 GitHub-hosted runner 在 block egress 环境下无法连接 Trivy OCI DB registry（GHCR 与 Google mirror 均 connection refused），因此不再依赖 Trivy vulnerability DB，改用 OSV API。参考：[pip-audit usage and strict mode](https://github.com/pypa/pip-audit/blob/main/README.md)、[OSV data exports](https://google.github.io/osv.dev/data/)、[Trivy license scanner](https://trivy.dev/docs/latest/guide/scanner/license/)。
- pip-audit 版本由 Linux/Windows 开发 hash lock 固定；Trivy 使用固定版本 `0.76.2` 和不可变 setup action SHA。漏洞扫描不忽略 unfixed 项；license scan 将 `UNKNOWN`、`RECIPROCAL`、`RESTRICTED`、`FORBIDDEN` 视为阻断项，`NOTICE`、`PERMISSIVE`、`UNENCUMBERED` 允许。未知许可证不允许静默豁免。
- 在线扫描拆成两个 job：prepare job checkout、安装 production lock、安装 hash-locked pip-audit toolset 与固定 Trivy binary，并打包输入 artifact；scan job 不 checkout、不访问 PyPI，Harden-Runner 作为第一步启用 `egress-policy: block`，allowlist 仅包含 `api.osv.dev`、`osv-vulnerabilities.storage.googleapis.com` 和 GitHub Actions artifact/API/Python setup endpoints。扫描 job 从 artifact 读取已准备的 lock/production venv/scanner toolset/Trivy binary；不允许任意公网出口。Windows CI 继续只运行本地测试，不访问漏洞数据库。Harden-Runner Community block mode 只支持 GitHub-hosted Linux runner；当前固定 v2.21.1（不可变 SHA），高于 DoH/DNS-over-TCP egress bypass 的修复版本 v2.16.0，并包含 v2.21.1 对 GitHub Actions runner 新内部 endpoint 的隐式放行修复。参考：[Harden-Runner](https://github.com/step-security/harden-runner)、[GHSA-46g3-37rh-v698](https://github.com/step-security/harden-runner/security/advisories/GHSA-46g3-37rh-v698)。
- 每次扫描记录 UTC 时间、commit SHA、production lock SHA-256、pip-audit/Trivy 版本、OSV PyPI `modified_id.csv` 的 HTTP `Last-Modified`/ETag、最新 advisory ID/modified 时间，以及 OSV API 对该 advisory 的返回时间。数据库导出超过 24 小时、API 未包含最新 advisory revision、source/API unavailable、metadata 缺字段或 JSON 解析失败均 fail-closed；scanner unavailable 不得视为 clean。
- 首轮只生成报告并审查所有结果，不自动升级、不自动忽略漏洞、不自动批准未知许可证；任何豁免都需明确 ID、责任人、到期日和理由。

### T21.7.4 漏洞与许可证策略

**首轮实施结果（2026-11-15）**：

- 新增 `.github/workflows/dependency-security.yml`，拆分 prepare 与 scan jobs；scan job 使用 Harden-Runner v2.21.1 block mode，allowlist 只包含 OSV API/数据导出及 GitHub Actions 必需 endpoints。Trivy OCI DB 在 GitHub-hosted runner 上连接被拒绝后，漏洞扫描改用 `pip-audit 2.10.1` + OSV API；Trivy `0.76.2` 仅执行离线 license scan。
- 最新完整 scan run `43703756088`（commit `3631263`）扫描 production Linux lock 的 17 个包，pip-audit 返回 0 个已知漏洞；OSV PyPI export 的 `Last-Modified` 为 `2026-11-15T09:18:04Z`，最新 advisory `MAL-2026-19942` 的 API `modified` 与导出记录一致，数据库年龄约 1.09 小时，freshness gate 通过。lock SHA-256 `2a142d5843133f0dced3926ae2b423cebc5fe7c1480dc213099aa5374c04ea3c`。报告 artifact `14156674350`。
- Trivy 识别 17 个 production package licenses。`PSF-2.0` 从 Trivy `UNKNOWN` 经 SPDX 文本证据映射为 `NOTICE`（保留 notice）；唯一剩余阻断项最初为 `tqdm` 的 `MPL-2.0 AND MIT`，分类 `RECIPROCAL`。在项目 owner 批准后，已为 `tqdm==4.70.1` 增加精确、限期、附带义务的单包例外；该项仍保持原始 `RECIPROCAL` 分类，报告会单独标记 `exception_applied`，不伪装成 permissive。
- 许可证审查边界：锁文件显示 `tqdm==4.70.1` 是 `openai` 的传递依赖；仓库根目录未发现项目级 `LICENSE` 文件，因此不能假设项目采用 MIT 或其他兼容许可证。Mozilla 官方 FAQ 将 MPL 2.0 描述为 file-level copyleft：对 MPL 覆盖文件的修改需按 MPL 提供源代码与通知；独立的更大作品文件可按其他许可证分发，但可执行分发仍需提供 MPL 覆盖部分的源代码。参考：[Mozilla MPL 2.0 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)、[MPL 2.0 text](https://www.mozilla.org/en-US/MPL/2.0/)。项目 owner 于 2026-11-15 批准有条件接受该传递依赖。例外责任人记为仓库 owner/maintainer（GitHub `rexyll`），到期/复审日为 2027-02-13；义务包括保留上游版权/许可证/归属通知、再分发时提供 MPL-2.0 与 MIT 许可证文本或权威 URL，以及修改并分发 MPL 覆盖文件时按 MPL-2.0 提供对应源代码。例外严格匹配包名、版本、许可证表达式与阻断分类；到期、锁版本不符、表达式不符或义务字段缺失均 fail-closed。策略文件：`config/dependency_license_policy.json`；执行器：`tools/check_trivy_license_policy.py`。
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


### T21.7.4 项目许可证与有条件依赖例外（2026-11-15）

- 根目录 `LICENSE` 最初仅采用官方 PolyForm Small Business 1.0.0；该历史方案没有授予所有个人宽泛的非商业使用权。**该方案已于 2026-11-15 被两份原版官方 PolyForm 许可证的双许可方案取代**：非商业用途选择 PolyForm Noncommercial 1.0.0（其条款明确任何非商业目的均为 permitted purpose，并列出个人研究、实验、学习、私人娱乐、爱好和业余活动）；符合条件的小企业商业用途选择 PolyForm Small Business 1.0.0 并遵守其全部门槛和条件；其他商业用途须取得单独书面许可。
- 新增 `THIRD_PARTY_NOTICES.md`，记录 `tqdm==4.70.1`（`openai` 传递依赖）的 `MPL-2.0 AND MIT` 表达式、上游来源和再分发义务。项目许可证不改变任何第三方依赖许可证。
- 许可证例外只匹配 `tqdm`、`4.70.1`、精确表达式 `MPL-2.0 AND MIT` 与 `RECIPROCAL` 分类；责任人 `repository owner (rexyll)`，批准日期 2026-11-15，到期/复审日期 2027-02-13。保留原始分类并在报告中显式列出已应用例外，不把它改写为 NOTICE/PERMISSIVE；未知许可证、扫描器不可用和数据库过期仍 deny。
- policy evaluator 已验证例外 schema、生产锁版本、精确表达式、审批日期、到期日期和非空义务清单；新增测试覆盖精确匹配、版本/表达式不匹配及过期 fail-closed。例外不能覆盖其他版本/包/许可证，也不能豁免漏洞扫描。
- 法律边界：许可证文本按 PolyForm 官方版本原样采用并保留其条件；本仓库的项目许可证与第三方依赖许可证分别适用。许可证选择不是法律意见，商业分发前建议由专业律师审阅。


**T21.7.4 最终验证（2026-11-15）**：

- 依赖安全扫描 run `43706969720`（提交 `6f1e4e9946312cbe32a5bcaca7b8d86668d8f840`）成功；production Linux Python 3.14 lock 17/17 包完整匹配，pip-audit 2.10.1 报告 0 个已知漏洞；OSV PyPI 数据库状态 `fresh`，导出年龄 6,352 秒（小于 24h），最新 advisory `MAL-2026-19942` 与 API record 对齐；Trivy 0.76.2 识别全部 17 个包，license policy `passed`。状态文件四项均为 exit code 0。artifact `14159420157`。
- policy result 明确保留 `tqdm==4.70.1` 的 `RECIPROCAL` 分类，并将精确表达式 `MPL-2.0 AND MIT` 标记为 `exception_applied=true`；审批日期 2026-11-15，责任人 `repository owner (rexyll)`，到期/复审日期 2027-02-13，完整理由与再分发义务进入扫描报告。未放宽其他 reciprocal/unknown licenses。
- 同一提交主 CI run `43706969697` 全部 Job 成功：全量回归 2,530 passed / 10 skipped；安全回归 237 passed / 9 skipped；Windows toolchain smoke 成功；coverage baseline job 成功。T21.7.4 漏洞与许可证扫描节点完成。T21.7.3 的固定硬件绝对性能预算仍因缺少受控 runner 而未完成，不能将 T21.7 整体标记完成。


## 项目许可范围最终决定（2026-11-15）

仓库所有者确认：**任何个人都应能免费进行非商业使用**。因此，项目不再把官方 PolyForm Small Business 1.0.0 单独作为项目主许可证，而采用根目录 `LICENSE` 中的两份官方 PolyForm 许可证构成的双许可方案：

1. **非商业许可**：选择官方 PolyForm Noncommercial 1.0.0。任何非商业目的均为 permitted purpose；其 Personal Uses 条款明确包括个人研究、实验、测试、学习、私人娱乐、爱好和业余活动。该路径不授权商业用途。
2. **小企业商业许可**：选择官方 PolyForm Small Business 1.0.0，完整适用其定义、员工/承包人员数量、通胀调整收入门槛、通知、专利、终止及其他限制。
3. **其他商业许可**：不符合 Small Business 许可条件的商业或组织利益用途，必须事先取得权利人的单独书面许可。
4. **第三方组件**：项目主许可不改变第三方依赖的许可证；继续遵守 `THIRD_PARTY_NOTICES.md` 中记录的 MPL-2.0/MIT 等义务。

此方案是两份官方 PolyForm 许可证的独立授权路径，不是自定义或修改版 PolyForm 许可证；两份许可证均不是 OSI-approved open-source license。许可证选择不是法律意见；正式商业分发前建议由专业律师审阅。


### 最终采用官方双许可路径（2026-11-15）

为避免自行起草自定义许可带来的条款歧义，最终将根目录 `LICENSE` 调整为两份官方许可证的完整文本及选择说明：

- **个人及其他非商业用途**：PolyForm Noncommercial License 1.0.0。其官方条款第 Noncommercial Purposes 节规定任何非商业目的均为 permitted purpose；Personal Uses 节进一步明确研究、实验、测试、个人学习、私人娱乐、爱好和业余活动等用途。官方文本：https://polyformproject.org/licenses/noncommercial/1.0.0 。
- **符合条件的小企业商业用途**：PolyForm Small Business License 1.0.0。必须满足其公司员工/独立承包人员与通胀调整收入门槛，并遵守该许可证的全部其他条款。官方文本：https://polyformproject.org/licenses/small-business/1.0.0 。
- **其他商业用途**：不属于上述 Noncommercial 授权范围，也不满足 Small Business 条件时，必须另行取得权利人的书面商业许可。
- 两份许可证是独立授权路径；使用者应选择实际授权其使用目的的许可证并遵守全文。第三方依赖仍由各自许可证约束。

这不是自定义或修改版 PolyForm 许可。两份许可证均不是 OSI-approved open-source license；不得将项目宣传为无条件开源或允许所有企业免费商用。
