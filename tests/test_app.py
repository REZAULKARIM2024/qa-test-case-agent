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
