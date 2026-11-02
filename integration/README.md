# integration/

面向集成验证的组件目录。

产品级「集成联调 + 全量回归」验证阶段由 `runtime/integration_verification.py` 实现
（在 `core/project_orchestrator.py` 的交付阶段中、文档生成与打包之前执行）；
本目录保留给未来的跨系统集成适配器（外部 CI、部署目标环境探测等）。

历史遗留的演示脚本 `test_real_team.py`（编码损坏且不被 pytest 收集）已于 2026-11-02
随仓库卫生清理（TaskPlan T0）移除。
