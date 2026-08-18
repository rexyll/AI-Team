from abc import ABC, abstractmethod

from runtime.task import Task


class BaseAgent(ABC):

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    @abstractmethod
    def run(self, task: Task):
        """
        Execute one AI Team task.

        All agents must receive a runtime.task.Task object.
        """
        pass