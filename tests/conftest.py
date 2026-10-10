import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def example_cases():
    path = ROOT / "sample_output" / "example_test_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def good_case():
    return {
        "title": "Login with valid credentials",
        "priority": "High",
        "type": "Positive",
        "preconditions": "User exists.",
        "steps": ["Open login page", "Enter credentials", "Submit"],
        "expected_result": "User lands on the dashboard.",
    }
