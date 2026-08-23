import sys
from pathlib import Path

# Bootstrap repository-root imports so the file runs standalone
# (``python examples/persistence_query.py``) as well as via pytest.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.workflow_event import WorkflowEvent  # noqa: E402
from runtime.workflow_event_persistence import WorkflowEventPersistenceAdapter  # noqa: E402
from runtime.workflow_event_query import WorkflowEventQueryService  # noqa: E402


PROJECT_ID = "PROJECT-EXAMPLE-001"


def run_example(root: str | Path = "./data/example-events") -> dict:
    adapter = WorkflowEventPersistenceAdapter(root)
    event = WorkflowEvent(
        event_id="EVENT-EXAMPLE-001",
        event_type="project.resumed",
        project_id=PROJECT_ID,
        occurred_at="2026-08-22T12:00:00Z",
        payload={},
    )
    adapter.save_if_absent(event)

    query = WorkflowEventQueryService.from_persistence(
        adapter,
        project_id=PROJECT_ID,
    )
    return {
        "lifecycle": query.lifecycle(),
        "last_event": query.last_event,
    }


if __name__ == "__main__":
    print(run_example())
