from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

from runtime.task import Task


T = TypeVar("T")


class TaskLayerExecutor:
    """Execute one dependency layer concurrently with bounded workers.

    The executor owns concurrency only. It does not inspect or mutate Task
    lifecycle state; callers remain responsible for lifecycle decisions and
    TaskManager remains the mutation boundary.
    """

    def __init__(self, max_workers: int = 4) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool):
            raise TypeError("max_workers must be an integer")
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers

    def run_layer(
        self,
        tasks: Iterable[Task],
        execute: Callable[[Task], T],
    ) -> list[T]:
        """Run all tasks in one dependency layer and wait for all results.

        Results preserve input task order, while task execution itself may be
        concurrent. A worker exception is re-raised only after all submitted
        futures have completed, so one failed task cannot cancel its peers.
        """
        task_list = list(tasks)
        if any(not isinstance(task, Task) for task in task_list):
            raise TypeError("all tasks must be Task instances")
        if not callable(execute):
            raise TypeError("execute must be callable")
        if not task_list:
            return []

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(task_list))) as pool:
            futures: list[Future[T]] = [
                pool.submit(execute, task)
                for task in task_list
            ]

            results: list[T] = []
            first_error: BaseException | None = None

            for future in futures:
                try:
                    results.append(future.result())
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
                    results.append(None)  # type: ignore[arg-type]

            if first_error is not None:
                raise first_error

            return results
