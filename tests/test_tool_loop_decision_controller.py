from runtime.tool_loop_decision_controller import ToolLoopDecisionController


def test_controller_preserves_failure_as_llm_decision():
    controller = ToolLoopDecisionController()

    decision = controller.classify(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        result="1 failed",
        status="failed",
        category="execution",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1 failed"}],
    )

    assert decision.requires_llm_decision is True
    assert decision.terminal is False
    assert controller.state.last_reason == "tool_failure_requires_recovery"
    assert controller.state.decisions == 1


def test_controller_marks_only_strict_full_suite_success_as_terminal():
    controller = ToolLoopDecisionController()

    decision = controller.classify(
        tool_name="run_command",
        arguments={"command": "pytest -q"},
        result="1104 passed",
        status="completed",
        category="verification",
        changed_files=["runtime/task.py"],
        command_results=[{"command": "pytest -q", "result": "1104 passed"}],
    )

    assert decision.requires_llm_decision is False
    assert decision.terminal is True
    assert controller.state.last_reason == "terminal_verification"


def test_controller_does_not_make_duplicate_evidence_terminal():
    controller = ToolLoopDecisionController()

    decision = controller.classify(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="same evidence",
        status="completed",
        category="exact_duplicate",
        duplicate_of="CALL-1",
        changed_files=[],
        command_results=[],
    )

    assert decision.requires_llm_decision is False
    assert decision.terminal is False
    assert decision.reason == "duplicate_evidence_reuse"


def test_controller_reset_clears_decision_state():
    controller = ToolLoopDecisionController()
    controller.classify(
        tool_name="read_file",
        arguments={"path": "runtime/task.py"},
        result="ok",
        status="completed",
        category="exploration",
        changed_files=[],
        command_results=[],
    )

    controller.reset()

    assert controller.state.last_reason is None
    assert controller.state.terminal is False
    assert controller.state.decisions == 0
