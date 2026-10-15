# Production Readiness Gate

AI-Team 的 Production Readiness Gate 是 Phase 18.5 的统一验收入口：

```powershell
python tools/run_production_readiness.py
```

## Gate 顺序

1. `security` — 执行 `tools/run_security_regression.py`，覆盖依赖、网络出口、secret、prompt injection、evidence 和 plugin extension security 回归。
2. `extension-boundary` — 验证 `tools / agents / workflow` 三类 plugin extension adapter 边界及示例契约。
3. `observability` — 自动收集并执行 tracing、metrics、dashboard、alerting 相关回归测试。
4. `persistence-recovery` — 验证 workflow event projection、query、recovery 和 rehydration 一致性。
5. `full-regression` — 执行完整 `pytest -q`。

## Fail-fast 语义

Gate 按固定顺序执行。任一子命令返回非零状态时立即停止，并输出：

```text
gate_failed=<name> exit_code=<code>
```

只有所有 gate 都成功时才输出：

```text
production_readiness=passed
```

因此不能使用“部分 gate 通过”作为生产就绪结论。

## 运行环境

Gate 使用当前 Python 解释器 (`sys.executable`) 执行子测试，工作目录固定为仓库根目录。这样可以保证 gate 使用与开发环境相同的虚拟环境和依赖集合。

## 变更原则

Production Readiness Gate 只应引用已有的权威回归测试和安全 runner，不应为了让 gate 通过而降低测试约束、修改默认安全策略或绕过现有 runtime boundary。

新增 extension 或 runtime boundary 后，应先添加对应 focused regression，再把它纳入适当 gate。
