import json

import pytest

import main


def write(tmp_path, name, content, encoding="utf-8"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)
    return path


def test_single_file_is_read_as_utf8_with_bom_stripped(tmp_path):
    path = write(tmp_path, "req.md", "\ufeff开发一个工具\n细节说明")
    assert main.load_requirement_input(str(path)) == "开发一个工具\n细节说明"


def test_directory_merges_text_files_in_path_order_with_headers(tmp_path):
    write(tmp_path, "b-补充.md", "补充说明")
    write(tmp_path, "a-主需求.md", "主需求正文")
    write(tmp_path, "子目录/规格.txt", "子目录规格")

    merged = main.load_requirement_input(str(tmp_path))

    assert merged.startswith("===== 需求文件：a-主需求.md =====\n\n主需求正文")
    assert "===== 需求文件：b-补充.md =====\n\n补充说明" in merged
    assert "===== 需求文件：子目录/规格.txt =====\n\n子目录规格" in merged
    assert merged.index("a-主需求.md") < merged.index("b-补充.md") < merged.index("子目录/规格.txt")


def test_directory_skips_hidden_tool_and_nontext_files(tmp_path):
    write(tmp_path, "需求.md", "有效需求")
    write(tmp_path, ".隐藏.md", "不应出现")
    write(tmp_path, "__pycache__/junk.md", "不应出现")
    write(tmp_path, "node_modules/pkg.md", "不应出现")
    write(tmp_path, "binary.dat", "不应出现")

    merged = main.load_requirement_input(str(tmp_path))

    assert "有效需求" in merged
    for noise in ("隐藏", "junk", "pkg", "binary"):
        assert noise not in merged


def test_directory_without_text_files_is_rejected(tmp_path):
    write(tmp_path, "only.dat", "x")
    with pytest.raises(ValueError, match="no .md/.markdown/.txt"):
        main.load_requirement_input(str(tmp_path))


@pytest.mark.parametrize("name, content", [("空.md", "   \n\t"), ("空.txt", "")])
def test_empty_file_or_section_is_rejected(tmp_path, name, content):
    path = write(tmp_path, name, content)
    with pytest.raises(ValueError, match="is empty"):
        main.load_requirement_input(str(path))


def test_missing_path_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        main.load_requirement_input(str(tmp_path / "nope.md"))


def test_invalid_utf8_is_rejected(tmp_path):
    path = tmp_path / "bad.md"
    path.write_bytes(b"\xff\xfe\xff")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        main.load_requirement_input(str(path))


def test_directory_over_character_budget_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_MAX_REQUIREMENT_CHARS", 10)
    write(tmp_path, "long.md", "x" * 30)
    with pytest.raises(ValueError, match="exceeds 10 characters"):
        main.load_requirement_input(str(tmp_path))


def test_cli_passes_loaded_requirement_text_to_delivery(tmp_path, monkeypatch, capsys):
    requirement_file = write(tmp_path, "req.txt", "开发一个词频统计工具")
    captured: dict = {}

    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

    class FakeTaskManager:
        def get_all_tasks(self):
            return []

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
            pass

        def create_plan(self, requirement):
            captured["requirement"] = requirement
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: object())
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", [
        "main.py", "--requirement-input", str(requirement_file), "--output", "json",
    ])

    assert main.main() == 0
    assert captured["requirement"] == "开发一个词频统计工具"
    assert json.loads(capsys.readouterr().out)["result"]["success"] is True


def test_cli_directory_input_flows_through(tmp_path, monkeypatch):
    write(tmp_path / "docs", "main.md", "来自目录的需求")
    captured: dict = {}

    class FakeProjectResult:
        success = True
        status = "completed"
        total_tasks = 1
        completed_tasks = 1

    class FakeTaskManager:
        def get_all_tasks(self):
            return []

    class FakeProjectOrchestrator:
        def __init__(self, agent_router, deliverable_dir=None, clarifications=None, **kwargs):
            pass

        def create_plan(self, requirement):
            captured["requirement"] = requirement
            return {"project": "demo", "summary": "s", "tasks": []}

        def build_task_manager(self, plan):
            return FakeTaskManager()

        def execute(self, task_manager):
            return FakeProjectResult()

    monkeypatch.setattr(main, "create_agent_router", lambda **kwargs: object())
    monkeypatch.setattr(main, "ProjectOrchestrator", FakeProjectOrchestrator)
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--requirement-input", str(tmp_path / "docs")])

    assert main.main() == 0
    assert "来自目录的需求" in captured["requirement"]


@pytest.mark.parametrize("extra", [["也用位置参数"], ["--apply-change", "c.md", "--from-state", "s", "--save-state", "d"]])
def test_cli_rejects_requirement_input_conflicts(tmp_path, monkeypatch, extra):
    requirement_file = write(tmp_path, "req.md", "文本需求")
    argv = ["main.py", "--requirement-input", str(requirement_file), *extra]
    monkeypatch.setattr(main.sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


def test_cli_missing_requirement_input_reports_error_not_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main.sys, "argv", ["main.py", "--requirement-input", str(tmp_path / "gone.md")])
    assert main.main() == 1
    assert "does not exist" in capsys.readouterr().err
