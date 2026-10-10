"""
agent.py
Takes a user story / requirement and generates structured QA test cases
using Claude, then exports them as Zephyr/Jira-import-ready CSV + raw JSON.

The LLM output is treated as untrusted input: it is parsed defensively,
validated against the expected schema, and sanitized before being written
to CSV (so a cell can never be executed as a spreadsheet formula).

Usage:
    python agent.py --file sample_input/user_story.txt
    python agent.py --text "As a user, I want to ..."
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic

OUTPUT_DIR = Path(__file__).parent / "output"
CLAUDE_MODEL = "claude-sonnet-4-6"

REQUIRED_FIELDS = ("title", "priority", "type", "preconditions", "steps", "expected_result")
ALLOWED_PRIORITIES = ("High", "Medium", "Low")
ALLOWED_TYPES = ("Positive", "Negative", "Boundary", "Security")
CSV_FIELDNAMES = [
    "Test Case ID",
    "Title",
    "Priority",
    "Type",
    "Preconditions",
    "Steps",
    "Expected Result",
]

SYSTEM_PROMPT = """You are a senior QA Engineer with expertise in test design
techniques (equivalence partitioning, boundary value analysis, negative testing,
positive/happy-path testing) and experience writing test cases for Jira/Zephyr.

Given a user story or requirement, generate a thorough, non-redundant set of
test cases covering:
- Positive / happy-path scenarios
- Negative scenarios (invalid input, error handling)
- Boundary / edge cases
- At least one security or data-integrity consideration if relevant

Respond with ONLY a JSON array (no prose, no markdown fences) where each
element has exactly these fields:
  "title": short descriptive test case title
  "priority": one of "High", "Medium", "Low"
  "type": one of "Positive", "Negative", "Boundary", "Security"
  "preconditions": string describing setup needed before the test
  "steps": array of strings, each a numbered step's action
  "expected_result": string describing the expected outcome

Return between 6 and 12 test cases depending on the complexity of the
requirement. Be specific to the given requirement — do not write generic
placeholder steps."""


class ModelOutputError(ValueError):
    """The model's reply could not be turned into a list of test cases."""


# ---------------------------------------------------------------------------
# Parsing and validation of the model's output
# ---------------------------------------------------------------------------

def parse_model_output(raw_text: str) -> list[dict]:
    """
    Turns the raw model reply into a list of dicts. Tolerates markdown code
    fences and short prose before/after the JSON array; raises
    ModelOutputError if no JSON array can be recovered.
    """
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            raise ModelOutputError("Model output did not contain a JSON array.")
        try:
            data = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as e:
            raise ModelOutputError(f"Model output was not valid JSON: {e}") from e

    if not isinstance(data, list):
        raise ModelOutputError("Model output was JSON but not an array of test cases.")
    return data


def validate_test_cases(test_cases: list[dict]) -> list[str]:
    """
    Returns a list of human-readable problems (empty list = all good).
    Checks required fields, allowed enum values, and that steps is a
    non-empty list of strings.
    """
    issues = []
    if not test_cases:
        return ["No test cases were generated."]

    for i, tc in enumerate(test_cases, start=1):
        label = f"Test case {i}"
        if not isinstance(tc, dict):
            issues.append(f"{label}: is not an object.")
            continue
        for field in REQUIRED_FIELDS:
            if field not in tc or tc[field] in ("", None, []):
                issues.append(f"{label}: missing '{field}'.")
        if tc.get("priority") not in ALLOWED_PRIORITIES and "priority" in tc:
            issues.append(f"{label}: priority '{tc.get('priority')}' is not one of {ALLOWED_PRIORITIES}.")
        if tc.get("type") not in ALLOWED_TYPES and "type" in tc:
            issues.append(f"{label}: type '{tc.get('type')}' is not one of {ALLOWED_TYPES}.")
        steps = tc.get("steps")
        if "steps" in tc and (not isinstance(steps, list) or not all(isinstance(s, str) for s in steps)):
            issues.append(f"{label}: 'steps' must be a list of strings.")
    return issues


def coverage_summary(test_cases: list[dict]) -> dict:
    """Counts test cases per type, always including every allowed type."""
    counts = {t: 0 for t in ALLOWED_TYPES}
    for tc in test_cases:
        if isinstance(tc, dict) and tc.get("type") in counts:
            counts[tc["type"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Calling the model
# ---------------------------------------------------------------------------

def call_claude(client: Anthropic, requirement_text: str) -> list[dict]:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Requirement:\n\n{requirement_text}"}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")
    return parse_model_output(raw_text)


# ---------------------------------------------------------------------------
# Exporting
# ---------------------------------------------------------------------------

def _safe_cell(value) -> str:
    """
    Spreadsheet apps treat cells starting with = + - @ as formulas. Because
    the text comes from an LLM, prefix such cells with an apostrophe so an
    imported file can never run a formula (CSV/formula injection).
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def write_csv(file_obj, test_cases: list[dict]):
    writer = csv.DictWriter(file_obj, fieldnames=CSV_FIELDNAMES)
    writer.writeheader()
    for i, tc in enumerate(test_cases, start=1):
        steps = tc.get("steps", [])
        numbered_steps = "\n".join(f"{j}. {s}" for j, s in enumerate(steps, start=1))
        writer.writerow({
            "Test Case ID": f"TC-{i:03d}",
            "Title": _safe_cell(tc.get("title", "")),
            "Priority": _safe_cell(tc.get("priority", "")),
            "Type": _safe_cell(tc.get("type", "")),
            "Preconditions": _safe_cell(tc.get("preconditions", "")),
            "Steps": _safe_cell(numbered_steps),
            "Expected Result": _safe_cell(tc.get("expected_result", "")),
        })


def to_csv_string(test_cases: list[dict]) -> str:
    buffer = io.StringIO()
    write_csv(buffer, test_cases)
    return buffer.getvalue()


def save_json(test_cases: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, ensure_ascii=False, indent=2)


def save_csv(test_cases: list[dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        write_csv(f, test_cases)


def main():
    parser = argparse.ArgumentParser(description="Generate QA test cases from a user story.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=str, help="Path to a .txt file with the requirement")
    group.add_argument("--text", type=str, help="Requirement text passed directly")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: Set the ANTHROPIC_API_KEY environment variable first.")
        sys.exit(1)

    if args.file:
        requirement_text = Path(args.file).read_text(encoding="utf-8")
    else:
        requirement_text = args.text

    client = Anthropic(api_key=api_key)

    print("Generating test cases with Claude...")
    try:
        test_cases = call_claude(client, requirement_text)
    except ModelOutputError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    issues = validate_test_cases(test_cases)
    if issues:
        print("WARNING: the model's output has problems:")
        for issue in issues:
            print(f"  - {issue}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "test_cases.csv"
    json_path = OUTPUT_DIR / "test_cases.json"

    save_csv(test_cases, csv_path)
    save_json(test_cases, json_path)

    print(f"Generated {len(test_cases)} test cases.")
    print(f"Coverage: {coverage_summary(test_cases)}")
    print(f"Saved to {csv_path}")
    print(f"Saved to {json_path}")


if __name__ == "__main__":
    main()
