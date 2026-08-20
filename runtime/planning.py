from dataclasses import dataclass, field


@dataclass
class PlannedTask:
    id: str
    title: str
    description: str
    role: str
    dependencies: list[str] = field(default_factory=list)


@dataclass
class PlanningResult:
    tasks: list[PlannedTask] = field(default_factory=list)