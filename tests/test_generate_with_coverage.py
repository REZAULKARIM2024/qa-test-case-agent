"""generate_with_coverage with a fake model: offline, instant, free."""
import json
from types import SimpleNamespace

import pytest

import agent

STORY = """Title: Reset

As a user I want to reset my password.

Acceptance Criteria:
- The reset link expires after 30 minutes.
- Existing sessions are invalidated after reset.
- A confirmation email is sent after reset.
"""


def case(title, covers, type_="Negative"):
    return {"title": title, "priority": "High", "type": type_, "preconditions": "p",
            "steps": ["s"], "expected_result": "r", "covers": covers}


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    def __init__(self, *replies):
        self.messages = FakeMessages(replies)


FIRST = [case("Link expires after 30 minutes", ["AC-1"]), case("Old sessions invalidated", ["AC-2"])]
SECOND = [case("Confirmation email is sent after reset", ["AC-3"])]


def test_criteria_and_traceability_instructions_reach_the_model():
    client = FakeClient(FIRST + SECOND)
    agent.generate_with_coverage(client, STORY)
    call = client.messages.calls[0]
    assert "covers" in call["system"] and "AC-1: The reset link expires after 30 minutes." in call["messages"][0]["content"]


def test_story_without_criteria_uses_the_original_single_call():
    client = FakeClient([{k: v for k, v in case("a", []).items() if k != "covers"}])
    out = agent.generate_with_coverage(client, "As a user I want X.")
    assert len(client.messages.calls) == 1 and out["report"] is None and out["criteria"] == []
    assert client.messages.calls[0]["system"] == agent.SYSTEM_PROMPT


def test_gap_is_followed_up_once_with_only_the_uncovered_criteria():
    client = FakeClient(FIRST, SECOND)
    out = agent.generate_with_coverage(client, STORY)
    gap_call = client.messages.calls[1]
    sent = gap_call["messages"][0]["content"]
    assert "AC-3: A confirmation email" in sent and "AC-1:" not in sent and "AC-2:" not in sent
    assert "Link expires after 30 minutes" in sent       # existing titles listed so they are not repeated
    assert out["followups"] == 1 and len(out["cases"]) == 3
    assert out["report"]["summary"]["uncovered"] == 0


def test_no_followup_when_everything_is_covered():
    client = FakeClient(FIRST + SECOND)
    out = agent.generate_with_coverage(client, STORY)
    assert len(client.messages.calls) == 1 and out["followups"] == 0


def test_followups_are_capped_even_if_gap_remains():
    client = FakeClient(FIRST, [case("Unrelated", ["AC-1"])], [case("never asked", ["AC-3"])])
    out = agent.generate_with_coverage(client, STORY, max_followups=1)
    assert len(client.messages.calls) == 2 and out["report"]["summary"]["uncovered"] == 1


def test_max_followups_zero_skips_the_second_round():
    client = FakeClient(FIRST)
    out = agent.generate_with_coverage(client, STORY, max_followups=0)
    assert len(client.messages.calls) == 1 and out["report"]["summary"]["uncovered"] == 1


def test_duplicate_titles_from_followup_are_dropped():
    client = FakeClient(FIRST, [case("link expires AFTER 30 minutes", ["AC-3"]), case("New one", ["AC-3"])])
    out = agent.generate_with_coverage(client, STORY)
    assert [c["title"] for c in out["cases"]].count("Link expires after 30 minutes") == 1
    assert len(out["cases"]) == 3


def test_case_limit_caps_the_merged_set():
    client = FakeClient(FIRST, [case(f"extra {i}", ["AC-3"]) for i in range(10)])
    out = agent.generate_with_coverage(client, STORY, case_limit=4)
    assert len(out["cases"]) == 4


def test_failed_followup_keeps_the_first_result():
    client = FakeClient(FIRST, "I cannot do that")
    out = agent.generate_with_coverage(client, STORY)
    assert len(out["cases"]) == 2 and out["followup_error"] and out["report"]["summary"]["uncovered"] == 1


def test_first_call_failure_still_raises_a_clear_error():
    with pytest.raises(agent.ModelOutputError):
        agent.generate_with_coverage(FakeClient("nope"), STORY)


def test_model_cannot_invent_criteria_ids():
    client = FakeClient([case("x", ["AC-99"])] + [], )
    out = agent.generate_with_coverage(client, STORY, max_followups=0)
    assert out["report"]["unknown_refs"] == [{"test": "TC-001", "criterion": "AC-99"}]
    issues = agent.validate_test_cases(out["cases"], out["criteria"])
    assert any("AC-99" in i for i in issues)


# ---- validation of the new field, CSV --------------------------------------

def test_covers_must_be_a_list_of_strings(good_case):
    good_case["covers"] = "AC-1"
    assert any("covers" in i for i in agent.validate_test_cases([good_case]))
    good_case["covers"] = [1]
    assert any("covers" in i for i in agent.validate_test_cases([good_case]))


def test_covers_is_optional_so_old_outputs_still_validate(good_case, example_cases):
    assert agent.validate_test_cases([good_case]) == []
    assert agent.validate_test_cases(example_cases) == []


def test_default_csv_is_unchanged_and_coverage_column_is_opt_in(good_case):
    good_case["covers"] = ["AC-1", "AC-2"]
    default = agent.to_csv_string([good_case]).splitlines()[0]
    assert default == ",".join(agent.CSV_FIELDNAMES)
    with_cov = agent.to_csv_string([good_case], include_coverage=True)
    assert with_cov.splitlines()[0].endswith(agent.CSV_COVERAGE_COLUMN)
    assert "AC-1, AC-2" in with_cov


def test_coverage_column_is_formula_safe(good_case):
    good_case["covers"] = ["=HYPERLINK(1)"]
    assert "'=HYPERLINK(1)" in agent.to_csv_string([good_case], include_coverage=True)
