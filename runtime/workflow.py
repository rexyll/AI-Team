from runtime.task import Task
from runtime.task_manager import TaskManager
from runtime.agent_router import AgentRouter


MAX_REVIEW_ROUNDS = 3


class TaskWorkflow:

    def __init__(
        self,
        task_manager: TaskManager,
        developer,
        reviewer,
        agent_router: AgentRouter,
        max_review_rounds: int = MAX_REVIEW_ROUNDS,
    ):
        if max_review_rounds <= 0:
            raise ValueError(
                "max_review_rounds must be greater than 0"
            )

        self.task_manager = task_manager
        self.agent_router = agent_router
        self.developer = developer
        self.reviewer = reviewer
        self.max_review_rounds = max_review_rounds

    def execute(self, task_id: str) -> Task:

        task = self.task_manager.get_task(task_id)

        # ============================================================
        # Developer -> Reviewer -> Developer -> Reviewer ...
        # ============================================================

        for _ in range(self.max_review_rounds):

            # --------------------------------------------------------
            # 1. Task 必须处于 ready 状态
            # --------------------------------------------------------

            if task.status == "pending":
                self.task_manager.get_ready_tasks()
            
            if task.status not in {"ready", "running"}:
                raise ValueError(
                    f"Task {task_id} is not ready or running: "
                    f"{task.status}"
                )
            
            if task.status == "ready":
                self.task_manager.mark_running(task_id)

            # --------------------------------------------------------
            # 2. Developer 开始执行
            # --------------------------------------------------------

            # self.task_manager.mark_running(task_id)

            # developer = self.agent_router.get_agent(
            #     "developer"
            # )

            try:

                developer_result = self.developer.run(task)

            except Exception as exc:

                self.task_manager.mark_failed(
                    task_id,
                    (
                        "Developer execution failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

                raise

            # --------------------------------------------------------
            # 3. Developer 完成
            #
            # 注意：
            #
            # Developer 完成 ≠ Task 完成
            #
            # 此时进入 review_pending
            # --------------------------------------------------------

            self.task_manager.mark_developer_completed(
                task_id,
                developer_result,
            )
            
            # self.task_manager.mark_review_pending(
            #     task_id,
            #     result,
            # )
            
            if task.status != "review_pending":
                raise RuntimeError(
                    f"Developer did not move task "
                    f"{task_id} to review_pending"
                )

            # --------------------------------------------------------
            # 4. Reviewer 开始审核
            # --------------------------------------------------------

            self.task_manager.mark_reviewing(
                task_id
            )

            # reviewer = self.agent_router.get_agent(
            #     "reviewer"
            # )

            try:

                review_result = self.reviewer.run(task)

            except Exception as exc:

                self.task_manager.mark_failed(
                    task_id,
                    (
                        "Reviewer execution failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )

                raise

            # --------------------------------------------------------
            # 5. 保存 Reviewer 结果
            # --------------------------------------------------------

            task.review_result = review_result

            # task.review_round += 1

            # --------------------------------------------------------
            # 6. Reviewer APPROVED
            #
            # Task 真正完成
            # --------------------------------------------------------

            if review_result.get("status") == "approved":

                self.task_manager.mark_review_approved(
                    task_id,
                    review_result,
                )

                return task

            # --------------------------------------------------------
            # 7. Reviewer REVISION_REQUIRED
            #
            # Developer 下一轮重新执行
            # --------------------------------------------------------

            if review_result.get("status") == "revision":

                self.task_manager.mark_review_revision_required(
                    task_id,
                    review_result,
                )

                # 如果已经达到最大审核次数，
                # 不再继续循环
                if task.review_round >= self.max_review_rounds:

                    self.task_manager.mark_failed(
                        task_id,
                        (
                            "Task failed review after "
                            f"{self.max_review_rounds} rounds"
                        ),
                    )

                    return task

                # ----------------------------------------------------
                # 继续下一轮 Developer
                #
                # review_result 已经保存在 task.review_result
                # Developer 可以在 _build_messages() 中读取
                # ----------------------------------------------------

                continue

            # --------------------------------------------------------
            # 8. Reviewer 返回非法状态
            # --------------------------------------------------------

            self.task_manager.mark_failed(
                task_id,
                (
                    f"Maximum review rounds exceeded: "
                    f"{self.max_review_rounds}"
                ),
            )

            return task

        # 理论上不会走到这里
        # 因为循环内部已经处理 completed / failed

        if task.status != "completed":

            self.task_manager.mark_failed(
                task_id,
                (
                    "Task workflow ended without "
                    "successful review"
                ),
            )

        return task