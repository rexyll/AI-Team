from runtime.task import Task


VALID_STATUSES = {
    "pending",
    "ready",
    "running",
    "review_pending",
    "reviewing",
    "revision",
    "completed",
    "failed",
    "blocked",
}


class TaskManager:

    def __init__(self, tasks: list[Task]):
        self.tasks = {
            task.id: task
            for task in tasks
        }

    def get_task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def get_all_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    def get_ready_tasks(self) -> list[Task]:
        """
        找出当前可以执行的任务。

        规则：

        1. 只有 pending 任务才能进入 ready
        2. 缺少依赖 -> blocked
        3. 任意依赖 failed / blocked -> blocked
        4. 所有依赖 completed -> ready
        """
        ready = []

        for task in self.tasks.values():

            if task.status != "pending":
                continue

            # 检查依赖是否存在
            missing_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if dependency_id not in self.tasks
            ]

            if missing_dependencies:
                task.status = "blocked"
                task.error = (
                    "Missing dependencies: "
                    + ", ".join(missing_dependencies)
                )
                continue

            # 检查依赖是否失败
            failed_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if self.tasks[dependency_id].status
                in {"failed", "blocked"}
            ]

            if failed_dependencies:
                task.status = "blocked"
                task.error = (
                    "Blocked by dependencies: "
                    + ", ".join(failed_dependencies)
                )
                continue

            # 检查依赖是否全部完成
            dependencies_completed = all(
                self.tasks[dependency_id].status
                == "completed"
                for dependency_id in task.dependencies
            )

            if dependencies_completed:
                task.status = "ready"
                ready.append(task)

        return ready

    def mark_ready(self, task_id: str) -> None:
            """
            将 pending 任务标记为 ready。

            一般情况下推荐使用 get_ready_tasks()，
            不建议 Workflow 直接调用此方法。
            """

            task = self.get_task(task_id)

            if task.status != "pending":
                raise ValueError(
                    f"Task {task_id} cannot become ready "
                    f"from status {task.status}"
                )

            task.status = "ready"
    
    def mark_running(self, task_id: str) -> None:
        """
        ready -> running
        """
        task = self.get_task(task_id)

        if task.status != "ready":
            raise ValueError(
                f"Task {task_id} is not ready"
            )

        task.status = "running"
         # 清理上一次执行可能留下的错误信息
        task.error = None

    def mark_completed(
            self,
            task_id: str,
            result: dict | None = None,
        ) -> None:
            """
            running -> completed

            Developer 完成任务后调用。

            注意：
            Reviewer 不应该通过这个方法直接覆盖 Developer
            的执行状态，而应该在审核通过之后确认任务完成。
            """

            task = self.get_task(task_id)

            if task.status != "running":
                raise ValueError(
                    f"Task {task_id} is not running"
                )

            task.status = "completed"

            task.error = None

            if result is not None:
                task.result = result

    def mark_reviewing(self, task_id: str) -> None:

        task = self.get_task(task_id)

        if task.status != "review_pending":
            raise ValueError(
                f"Task {task_id} is not review_pending"
            )

        task.status = "reviewing"
        
    def mark_review_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
    ) -> None:

        task = self.get_task(task_id)

        if task.status != "reviewing":
            raise ValueError(
                f"Task {task_id} is not reviewing"
            )

        if review_result is not None:
            task.review_result = review_result
            task.review_round += 1

            task.context["reviewer_feedback"] = review_result
            task.status = "running"    
    
    def mark_revision(
        self,
        task_id: str,
        review: dict,
    ) -> None:

        task = self.get_task(task_id)

        if task.status != "reviewing":
            raise ValueError(
                f"Task {task_id} is not reviewing"
            )

        task.status = "revision"
        task.review = review
    
    def mark_revision_required(
        self,
        task_id: str,
        review_result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """
        Reviewer 要求 Developer 修改。

        状态：

            completed
                ↓
             pending
                ↓
              ready
                ↓
             running
                ↓
           Developer
                ↓
            completed
                ↓
           Reviewer

        也就是说：

        REVISION_REQUIRED 不应该把任务直接标记为 failed。

        它代表：

        Developer 已经完成了一轮实现，
        但 Reviewer 要求重新修改。

        因此应该回到 pending，
        让任务重新进入正常调度流程。
        """
        task = self.get_task(task_id)

        if task.status != "completed":
            raise ValueError(
                f"Task {task_id} cannot require revision "
                f"from status {task.status}"
            )

        if review_result is not None:

            if not isinstance(review_result, dict):
                raise TypeError(
                    "review_result must be a dict"
                )

            task.result["review"] = review_result

        task.status = "pending"

        task.error = error
    
    def mark_review_pending(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:

        task = self.get_task(task_id)

        if task.status != "running":
            raise ValueError(
                f"Task {task_id} is not running"
            )

        task.status = "review_pending"

        if result is not None:
            task.result = result
        
    def mark_review_approved(
        self,
        task_id: str,
        review_result: dict,
    ) -> None:
        """
        Reviewer 审核通过。

        Developer 已经 completed 的情况下：

            completed
                ↓
             approved

        Task 本身继续保持 completed。

        Reviewer 的审核结果保存到：

            task.result["review"]
        """
        task = self.get_task(task_id)

        if task.status != "reviewing":
            raise ValueError(
            f"Task {task_id} is not reviewing"
        )

        if review_result is not None:

            if not isinstance(review_result, dict):
                raise TypeError(
                    "review_result must be a dict"
                )

            task.result["review"] = review_result

        task.error = None
    
    def apply_review_result(
        self,
        task_id: str,
        review_result: dict,
    ) -> str:
        """
        根据 ReviewerAgent 的结果自动推进 Task 状态。

        ReviewerAgent 当前返回：

            {
                "status": "approved",
                ...
            }

        或：

            {
                "status": "revision",
                ...
            }

        返回最终 Task 状态。
        """

        if not isinstance(review_result, dict):
            raise TypeError(
                "review_result must be a dict"
            )

        review_status = review_result.get("status")

        if review_status == "approved":

            self.mark_review_approved(
                task_id,
                review_result,
            )

            return "completed"

        if review_status == "revision":

            self.mark_revision_required(
                task_id,
                review_result,
            )

            return "pending"

        raise ValueError(
            f"Unknown reviewer status: {review_status}"
        )
    
    def retry_revision(self, task_id: str) -> None:

        task = self.get_task(task_id)

        if task.status != "revision":
            raise ValueError(
                f"Task {task_id} is not in revision"
            )

        task.status = "ready"
        
    def mark_developer_completed(
        self,
        task_id: str,
        result: dict | None = None,
    ) -> None:

        task = self.get_task(task_id)

        if task.status != "running":
            raise ValueError(
                f"Task {task_id} is not running"
            )

        task.status = "review_pending"

        if result:
            task.result = result

    def mark_failed(
        self,
        task_id: str,
        error: str,
    ) -> None:
        """
        running -> failed
        """
        task = self.get_task(task_id)

        if task.status != "running":
            raise ValueError(
                f"Task {task_id} is not running"
            )

        task.status = "failed"
        task.error = error
  
    def get_blocked_tasks(self) -> list[Task]:

        return [
            task
            for task in self.tasks.values()
            if task.status == "blocked"
        ]
    
    def get_failed_tasks(self) -> list[Task]:
        return [
            task
            for task in self.tasks.values()
            if task.status == "failed"
        ]
    
    def has_failed_tasks(self) -> bool:

        return any(
            task.status in {"failed", "blocked"}
            for task in self.tasks.values()
        )
    
    def is_finished(self) -> bool:
        return all(
            task.status == "completed"
            for task in self.tasks.values()
        )