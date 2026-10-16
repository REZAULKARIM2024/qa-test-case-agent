"""Smoke tests for the Streamlit UI using Streamlit's built-in AppTest (no browser, no API key)."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def _run():
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def test_app_loads_without_errors_and_shows_example():
    at = _run()
    assert not at.exception
    assert any("Example output" in s.value for s in at.subheader)


def test_example_validation_passes():
    at = _run()
    assert any("Validation passed" in s.value for s in at.success)


def test_generate_without_key_shows_a_warning_not_a_crash(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = _run()
    generate = next(b for b in at.button if "Generate" in b.label)
    generate.click().run()
    assert not at.exception
    assert any("API key" in w.value for w in at.warning)


def test_example_shows_requirement_coverage_without_a_key():
    at = _run()
    assert not at.exception
    assert any("Requirement coverage" in s.value for s in at.subheader)
    labels = [m.label for m in at.metric]
    assert "Criteria" in labels and "Not covered" in labels
    covered = next(m for m in at.metric if m.label == "Covered")
    assert covered.value.startswith("6 (100%)")


def test_simulating_removed_test_cases_reveals_a_gap():
    at = _run()
    at.multiselect[0].set_value(["TC-003"]).run()   # the only case covering AC-3
    assert not at.exception
    assert any("AC-3 is not covered" in w.value for w in at.warning)
    assert next(m for m in at.metric if m.label == "Not covered").value == "1"


def test_story_without_criteria_says_so_before_generating():
    at = _run()
    at.text_area[0].set_value("As a user I want to log in.").run()
    assert not at.exception
    assert any("No 'Acceptance Criteria:' section" in c.value for c in at.caption)
