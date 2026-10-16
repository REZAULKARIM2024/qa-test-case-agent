"""traceability.py is deterministic, so every rule is tested directly: no model, no network."""
import pytest

import traceability as tr


def case(title="t", type_="Positive", covers=None, steps=("step",), expected="ok", pre="p"):
    tc = {"title": title, "priority": "High", "type": type_, "preconditions": pre,
          "steps": list(steps), "expected_result": expected}
    if covers is not None:
        tc["covers"] = covers
    return tc


CRITERIA = [{"id": "AC-1", "text": "The reset link expires after 30 minutes."},
            {"id": "AC-2", "text": "Existing sessions are invalidated after reset."}]


# ---- extract_criteria -------------------------------------------------------

def test_sample_story_yields_six_criteria():
    text = open("sample_input/user_story.txt", encoding="utf-8").read()
    got = tr.extract_criteria(text)
    assert [c["id"] for c in got] == [f"AC-{i}" for i in range(1, 7)]
    assert got[0]["text"].startswith("User can request a password reset")


def test_wrapped_lines_are_joined_to_their_criterion():
    got = tr.extract_criteria("Acceptance Criteria:\n- first part\n  second part\n- other")
    assert got[0]["text"] == "first part second part" and got[1]["text"] == "other"


def test_numbered_and_star_and_dot_bullets():
    got = tr.extract_criteria("Acceptance criteria\n1. one\n2) two\n* three\n• four")
    assert [c["text"] for c in got] == ["one", "two", "three", "four"]


def test_given_when_then_blocks_start_a_criterion_each():
    text = "AC:\nGiven a user\nWhen they log in\nThen they see home\nGiven bad pw\nThen error"
    got = tr.extract_criteria(text)
    assert len(got) == 2 and got[0]["text"].startswith("Given a user When they log in")


def test_next_section_header_ends_the_criteria():
    got = tr.extract_criteria("Acceptance Criteria:\n- keep me\nNotes:\n- not a criterion")
    assert [c["text"] for c in got] == ["keep me"]


def test_story_without_criteria_gives_empty_list():
    assert tr.extract_criteria("As a user I want things.") == []
    assert tr.extract_criteria("") == [] and tr.extract_criteria(None) == []


def test_criteria_are_capped_in_number_and_length():
    many = "Acceptance Criteria:\n" + "\n".join(f"- c{i}" for i in range(100))
    assert len(tr.extract_criteria(many)) == tr.MAX_CRITERIA
    long = tr.extract_criteria("Acceptance Criteria:\n- " + "x" * 5000)[0]["text"]
    assert len(long) == tr.MAX_CRITERIA_CHARS


# ---- build_coverage ---------------------------------------------------------

def test_status_covered_thin_and_uncovered():
    cases = [case("link expires after 30 minutes", "Negative", ["AC-1"]),
             case("sessions invalidated", "Positive", ["AC-2"])]
    rows = {r["id"]: r for r in tr.build_coverage(cases, CRITERIA)["rows"]}
    assert rows["AC-1"]["status"] == "covered" and rows["AC-1"]["tests"] == ["TC-001"]
    assert rows["AC-2"]["status"] == "thin"           # only a Positive case

    gap = tr.build_coverage(cases[:1], CRITERIA)
    assert gap["summary"]["uncovered"] == 1 and gap["summary"]["percent"] == 50
    assert [g["id"] for g in tr.uncovered_criteria(gap)] == ["AC-2"]


def test_two_case_types_make_a_criterion_covered_not_thin():
    cases = [case("expires", "Positive", ["AC-1"]), case("expired link", "Boundary", ["AC-1"])]
    assert tr.build_coverage(cases, CRITERIA)["rows"][0]["status"] == "covered"


def test_unknown_reference_is_reported_not_counted():
    rep = tr.build_coverage([case("x", covers=["AC-9"])], CRITERIA)
    assert rep["unknown_refs"] == [{"test": "TC-001", "criterion": "AC-9"}]
    assert rep["summary"]["covered"] == 0 and rep["untraced"] == ["TC-001"]


def test_case_without_covers_is_untraced_and_never_crashes():
    rep = tr.build_coverage([case("x"), {"not": "a case"}, "junk"], CRITERIA)
    assert rep["untraced"] == ["TC-001", "TC-002", "TC-003"]


def test_bad_covers_values_are_ignored():
    rep = tr.build_coverage([case("expires 30 minutes", covers="AC-1"), case("e", covers=[1, None, "AC-1", "AC-1"])], CRITERIA)
    assert rep["rows"][0]["tests"] == ["TC-002"]      # string covers ignored; duplicates collapsed


def test_link_with_no_shared_vocabulary_is_suspect():
    cases = [case("Login with valid credentials", covers=["AC-1"], steps=["Open page"], expected="Dashboard shown")]
    rep = tr.build_coverage(cases, CRITERIA)
    assert rep["suspect_links"] == [{"test": "TC-001", "criterion": "AC-1"}]


def test_plural_and_tense_variants_still_share_vocabulary():
    assert tr.shares_vocabulary("The link expires after 30 minutes", case("Expired links are rejected"))


def test_empty_criteria_list():
    rep = tr.build_coverage([case("x")], [])
    assert rep["rows"] == [] and rep["summary"]["percent"] == 0


# ---- render_markdown --------------------------------------------------------

def test_markdown_report_lists_gaps_and_caveat():
    cases = [case("expires after 30 minutes", "Negative", ["AC-1"]), case("extra", covers=[])]
    md = tr.render_markdown(tr.build_coverage(cases, CRITERIA), cases)
    assert "Covered by at least one test case: **1** (50%)" in md
    assert "AC-2: Existing sessions are invalidated after reset." in md
    assert "TC-002: extra" in md
    assert "claimed by the model" in md


def test_markdown_table_cells_cannot_break_the_table():
    crit = [{"id": "AC-1", "text": "a | b\nc"}]
    md = tr.render_markdown(tr.build_coverage([], crit), [])
    assert "| AC-1 | a \\| b c |" in md


def test_example_with_coverage_is_internally_consistent():
    import json
    cases = json.load(open("sample_output/example_with_coverage.json", encoding="utf-8"))
    crit = tr.extract_criteria(open("sample_input/user_story.txt", encoding="utf-8").read())
    rep = tr.build_coverage(cases, crit)
    assert rep["summary"]["uncovered"] == 0 and not rep["unknown_refs"]
    assert rep["untraced"] == ["TC-010"]
    assert rep["suspect_links"] == []
