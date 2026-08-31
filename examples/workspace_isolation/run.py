from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security.workspace import WorkspaceSandbox


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-team-workspace-") as temp_root:
        base = Path(temp_root)
        project_a = WorkspaceSandbox(base / "project-a")
        project_b = WorkspaceSandbox(base / "project-b")

        project_a.resolve("src").mkdir(parents=True)
        project_b.resolve("src").mkdir(parents=True)
        project_a.resolve("src/result.txt").write_text("project-a", encoding="utf-8")
        project_b.resolve("src/result.txt").write_text("project-b", encoding="utf-8")

        a_result = project_a.require_file("src/result.txt").read_text(encoding="utf-8")
        b_result = project_b.require_file("src/result.txt").read_text(encoding="utf-8")

        try:
            project_a.resolve(project_b.resolve("src/result.txt"))
        except PermissionError:
            cross_workspace_blocked = True
        else:
            cross_workspace_blocked = False

        assert a_result == "project-a"
        assert b_result == "project-b"
        assert cross_workspace_blocked

        print("workspace-a=project-a")
        print("workspace-b=project-b")
        print("cross-workspace-access=blocked")


if __name__ == "__main__":
    main()
