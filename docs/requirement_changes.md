# 需求变更回流

首次交付时显式保存状态，后续用变更文件驱动 Analyst 影响分析、Planner 重规划、任务执行和重新交付。

```bash
python main.py "开发一个统计工具" --projects-base ./products --save-state ./states/v1 --static-gate --strict-acceptance
python main.py --apply-change ./change.md --from-state ./states/v1 --save-state ./states/v2 --strict-acceptance --output json
```

`change.md` 是非空 UTF-8 文本，描述新增、修改或取消的需求及期望验收标准。`--save-state` 必须是尚不存在的新目录；不能覆盖源状态目录。旧运行未保存状态时，不能只凭交付文档恢复任务历史。

## 状态与执行契约

- `project.json` 保存原需求、澄清答复、最新规格、工作区路径、静态门禁设置和累计变更记录。
- `snapshots/<project_id>.json` 保存计划、任务历史和执行结果；执行过程通过已有状态检查点更新新快照。
- 变更分析包含原需求、已有变更、上一版规格和当前任务状态。分析质量检查未通过、计划不合法、图仍有活动任务时拒绝变更。
- 复用 `RecoveryReplanCoordinator` 的准备、校验和提交流程，但仅提交到分离的候选任务管理器。准备失败不修改原任务图，不创建目标状态目录。
- 已完成任务的定义和历史不可改写或丢弃。涉及已完成工作的返工必须使用新任务 ID，避免新需求被旧的 completed 状态误判为完成。
- 未修改的任务保留状态和证据；修改的未完成任务重新进入 pending；被替代任务 ID 明确记录，旧证据仍可从源快照读取。
- 变更记录包含 added_tasks、modified_tasks、superseded_tasks、preserved_tasks 和完整分析。`accepted` 仅表示候选计划通过检查，不表示实现或交付已经成功；交付结果以快照和 CLI result 为准。
- 沿用原工作区和静态门禁设置，不能通过变更命令切换工作区或关闭已有静态门禁。验收失败退出仍需 `--strict-acceptance`。

## 使用边界

源**状态文件**保持不变，但实现会修改同一个产品工作区；这不是源代码分支隔离或自动回滚。只应加载自己信任的本地状态目录，不支持对同一产品工作区并发执行多次变更。活动任务必须先正常结束；本入口不强制解锁中断的运行。

当前提供本地文件入口，不包含 issue 系统、审批界面、多版本发布规划或语义级影响分析的确定性证明。Analyst/Planner 的内容仍来自模型；确定性检查保证图结构及历史保留，不能代替人工确认需求理解。本轮使用假模型和真实持久化组件做离线回归，未新增付费模型端到端实测。
