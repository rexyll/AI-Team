from runtime.context_tiers import TIER_NAMES, build_semantic_context_tiers


def test_semantic_context_tiers_have_stable_names_and_required_information():
    tiers = build_semantic_context_tiers(
        role="developer",
        task_id="TASK-1",
        task_title="Implement feature",
        task_description="Build the feature.",
        status="in_progress",
        dependencies=["TASK-0"],
        dependency_context={"TASK-0": {"result": "done"}},
        task_result={"changed_files": ["runtime/task.py"]},
        tester_feedback={"status": "passed"},
        reviewer_feedback={"status": "approved"},
        history=[{"status": "pending"}] * 10,
        test_history=[{"result": "passed"}],
        review_history=[{"result": "approved"}],
        metadata={"project_id": "PROJECT-1"},
    )

    assert TIER_NAMES == (
        "system_contract",
        "project_facts",
        "task_facts",
        "current_work_evidence",
        "recent_interaction",
        "historical_evidence",
    )
    assert tiers.task_facts["task_id"] == "TASK-1"
    assert tiers.task_facts["dependencies"] == ["TASK-0"]
    assert tiers.current_work_evidence["tester_feedback"]["status"] == "passed"
    assert len(tiers.recent_interaction) == 8
    assert tiers.historical_evidence["review_history"][0]["result"] == "approved"


def test_semantic_context_tiers_return_detached_data():
    metadata = {"project_id": "PROJECT-1"}
    tiers = build_semantic_context_tiers(
        role="developer",
        task_id="TASK-1",
        task_title="Feature",
        task_description="Description",
        status="pending",
        metadata=metadata,
    )

    output = tiers.to_dict()
    output["project_facts"]["project_id"] = "changed"
    output["task_facts"]["dependencies"].append("TASK-2")

    assert tiers.project_facts["project_id"] == "PROJECT-1"
    assert tiers.task_facts["dependencies"] == []
