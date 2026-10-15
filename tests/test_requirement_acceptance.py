from __future__ import annotations

from pathlib import Path

import pytest

from runtime.acceptance import (
    RequirementEntry,
    acceptance_verdict,
    build_traceability_matrix,
    parse_requirement_entries,
    render_acceptance_report,
    write_acceptance_report,
)


ANALYSIS = """# 需求规格说明（草案）

## 一、项目概述
词频统计工具。

## 二、功能需求清单
### REQ-001 词频统计（必须）
统计文本文件中每个单词出现次数。
验收标准：给定样例输入，输出与预期一致。

### REQ-002 CSV 导出（可选）
支持导出 CSV。

### REQ-003 配置文件（应该）
支持配置文件。

## 三、非功能需求
-【假设】UTF-8 输入。
"""


def test_parse_extracts_priorities_and_acceptance():
    entries = parse_requirement_entries(ANALYSIS)

    assert [entry.req_id for entry in entries] == ["REQ-001", "REQ-002", "REQ-003"]
    assert entries[0].priority == "必须"
    assert entries[0].has_acceptance_criteria is True
    assert entries[0].title == "词频统计"
    assert entries[1].priority == "可选"
    assert entries[1].has_acceptance_criteria is False
    assert entries[2].priority == "应该"


def test_parse_ignores_non_requirement_markdown():
    entries = parse_requirement_entries("# 需求规格说明（草案）\n\n## 一、项目概述\n无编号内容")

    assert entries == []


def test_matrix_reports_reference_presence_per_source():
    entries = parse_requirement_entries(ANALYSIS)
    sources = {
        "requirements_doc": "REQ-001 词频统计\nREQ-002 CSV 导出\nREQ-003 配置文件",
        "design_doc": "模块 A 实现 REQ-001",
        "test_report": "REQ-001 已验证",
        "user_manual": "",
    }

    matrix = build_traceability_matrix(entries, sources=sources)

    row1 = matrix[0]
    assert row1["in_requirements_doc"] is True
    assert row1["in_design_doc"] is True
    assert row1["in_test_report"] is True
    assert row1["in_user_manual"] is False
    assert matrix[1]["in_requirements_doc"] is True
    assert matrix[1]["in_test_report"] is False


def test_verdict_fails_on_uncovered_must_requirement():
    entries = parse_requirement_entries(ANALYSIS)
    sources = {
        "requirements_doc": "REQ-001\nREQ-002\nREQ-003",
        "test_report": "REQ-001 已验证",
    }
    matrix = build_traceability_matrix(entries, sources=sources)

    verdict = acceptance_verdict(entries, matrix)

    # 可选/应该缺覆盖只是警告，不产生缺口
    assert verdict["verdict"] == "passed"
    assert verdict["gaps"] == []
    assert any("REQ-002" in warning for warning in verdict["warnings"])
    assert any("REQ-003" in warning for warning in verdict["warnings"])


def gaps_for(verdict, req_id):
    return [gap for gap in verdict["gaps"] if req_id in gap]


def test_verdict_passes_when_all_must_requirements_traceable():
    entries = [RequirementEntry("REQ-001", "必须", True, "词频统计")]
    matrix = build_traceability_matrix(entries, sources={
        "requirements_doc": "REQ-001",
        "test_report": "REQ-001 已验证",
    })

    verdict = acceptance_verdict(entries, matrix)

    assert verdict["verdict"] == "passed"
    assert verdict["gaps"] == []


def test_report_rendering_and_write(tmp_path: Path):
    entries = parse_requirement_entries(ANALYSIS)
    sources = {
        "requirements_doc": "REQ-001",
        "test_report": "REQ-001 已验证",
        "design_doc": "",
        "user_manual": "",
    }
    matrix = build_traceability_matrix(entries, sources=sources)
    verdict = acceptance_verdict(entries, matrix)

    report_path = write_acceptance_report(tmp_path / "docs", entries, matrix, verdict, project="wordcount")
    report = report_path.read_text(encoding="utf-8")

    assert report_path.name == "acceptance_report.md"
    assert "验收结论：**PASSED**" in report
    assert "| REQ-001 | 必须 | 是 |" in report


def test_rejects_non_string_analysis():
    with pytest.raises(TypeError):
        parse_requirement_entries(None)


def test_verdict_fails_when_must_requirement_uncovered():
    entries = [
        RequirementEntry("REQ-001", "必须", True, "词频统计"),
        RequirementEntry("REQ-002", "必须", False, "配置热更新"),
    ]
    sources = {
        "requirements_doc": "REQ-001\nREQ-002",
        "test_report": "REQ-001 已验证",  # REQ-002 无追溯
    }
    matrix = build_traceability_matrix(entries, sources=sources)

    verdict = acceptance_verdict(entries, matrix)

    assert verdict["verdict"] == "failed"
    assert "REQ-002 未在 test_report 中追溯" in verdict["gaps"]
    assert "REQ-002 缺少验收标准" in verdict["gaps"]


TABLE_DRAFT = """# 需求规格说明（草案）

## 一、项目概述
字符串反转工具。

## 二、功能需求清单
| REQ-001 | 字符串输入 | 提供文本输入【假设】 | 必须 |
| REQ-002 | 反转处理 | 逐字符反转【假设】 | 必须 |

## 三、非功能需求
- 无

## 四、验收标准

### REQ-001（必须）- 字符串输入
验收标准：给定样例输入，输出与预期一致。

### REQ-002（必须）- 反转处理
验收标准：反转 "abc" 得到 "cba"。

## 五、假设与约束
- 无

## 六、待确认问题
- 无
"""


def test_table_style_drafts_merge_criteria_from_later_sections():
    """Live failure: acceptance criteria lived in a separate section while the
    requirement rows were a table — the parser must merge blocks by id."""
    entries = parse_requirement_entries(TABLE_DRAFT)

    assert [entry.req_id for entry in entries] == ["REQ-001", "REQ-002"]
    assert all(entry.has_acceptance_criteria for entry in entries)
    assert all(entry.priority == "必须" for entry in entries)


AC_TABLE_DRAFT = """# 需求规格说明（草案）

## 一、项目概述
字符串反转工具。

## 二、功能需求清单
| REQ-001 | 字符串反转核心功能 | 接收字符串输出逆序 | 必须 |
| REQ-002 | 帮助信息 | 执行 --help 输出使用说明 | 可选 |

## 三、非功能需求
- 无

## 四、验收标准

| AC-001 | REQ-001 | 基本反转 | 输入 abc 输出 cba，退出码 0 |
| AC-002 | REQ-002 | 帮助输出 | 执行 --help 显示使用说明 |

## 五、假设与约束
- 无

## 六、待确认问题
- 无
"""


def test_ac_table_in_acceptance_section_counts_as_criteria():
    """Live probe: AC-table style drafts must be recognized — the AC rows
    live under a 验收标准 section and reference REQ ids."""
    entries = parse_requirement_entries(AC_TABLE_DRAFT)

    assert [entry.req_id for entry in entries] == ["REQ-001", "REQ-002"]
    assert all(entry.has_acceptance_criteria for entry in entries)
