from runtime.agent_router import AgentRouter
from runtime.context_builder import build_task_context
from runtime.task_manager import TaskManager


class Orchestrator:
    """
    AI Team 核心协调器。

    负责：

    Planner
        ↓
    TaskManager
        ↓
    AgentRouter
        ↓
    Agent
        ↓
    TaskManager
    """

    def __init__(
        self,
        task_manager: TaskManager,
        agent_router: AgentRouter,
    ):
        self.task_manager = task_manager
        self.agent_router = agent_router

    def run(self) -> None:
        print()
        print("=" * 60)
        print("AI TEAM START")
        print("=" * 60)

        total = len(
            self.task_manager.get_all_tasks()
        )

        print(f"任务总数：{total}")

        while not self.task_manager.is_finished():

            ready_tasks = (
                self.task_manager.get_ready_tasks()
            )

            if not ready_tasks:

                self._handle_no_ready_tasks()

                if self.task_manager.has_failed_tasks():
                    break

                break

            for task in ready_tasks:
                self._execute_task(task)

        print()
        print("=" * 60)

        if self.task_manager.is_finished():
            print("AI TEAM FINISHED")
        else:
            print("AI TEAM STOPPED")

        print("=" * 60)

    def _execute_task(self, task) -> None:

        print()
        print("-" * 60)
        print(
            f"{task.id} | "
            f"{task.role} | "
            f"{task.title}"
        )
        print("-" * 60)

        try:
            agent = self.agent_router.get_agent(task.role)

            context = build_task_context(
                task,
                self.task_manager.tasks,
            )

            task.context = context

            self.task_manager.mark_running(task.id)

            print(f"[Agent] {task.role}")

            result = agent.run(task)

            self.task_manager.mark_completed(
                task.id,
                result,
            )

            print(f"[Completed] {task.id}")

        except Exception as e:

            self.task_manager.mark_failed(
                task.id,
                str(e),
            )

            print(
                f"[Failed] {task.id}: {e}"
            )


    def _handle_no_ready_tasks(self) -> None:

        tasks = self.task_manager.get_all_tasks()

        print()
        print(
            "[ERROR] 没有可以执行的任务。"
        )

        print()
        print("当前任务状态：")

        for task in tasks:

            error = ""

            if task.error:
                error = f" | {task.error}"

            print(
                f"{task.id:<10}"
                f"{task.status:<12}"
                f"{task.role:<12}"
                f"{task.title}"
                f"{error}"
            )