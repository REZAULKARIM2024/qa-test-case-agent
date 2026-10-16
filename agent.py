"""
agent.py
Takes a user story / requirement and generates structured QA test cases
using Claude, then exports them as Zephyr/Jira-import-ready CSV + raw JSON.

The LLM output is treated as untrusted input: it is parsed defensively,
validated against the expected schema, and sanitized before being written
to CSV (so a cell can never be executed as a spreadsheet formula).

If the story has an "Acceptance Criteria:" section, each test case is also traced to the
criteria it covers, uncovered criteria trigger one follow-up request, and a coverage
report is written (see traceability.py).

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

import traceability

OUTPUT_DIR = Path(__file__).parent / "output"
CLAUDE_MODEL = "claude-sonnet-4-6"

REQUIRED_FIELDS = ("title", "priority", "type", "preconditions", "steps", "expected_result")
ALLOWED_PRIORITIES = ("High", "Medium", "Low")
ALLOWED_TYPES = ("Positive", "Negative", "Boundary", "Security")
MAX_CASES = 30  # hard cap on the merged test set, so a follow-up round cannot grow it without limit
CSV_COVERAGE_COLUMN = "Covers (Acceptance Criteria)"
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


TRACEABILITY_ADDENDUM = """

The requirement comes with numbered acceptance criteria (AC-1, AC-2, ...). In addition,
every test case must have a "covers" field: an array of the criterion IDs it verifies
(for example ["AC-2", "AC-4"]). Use ONLY the IDs you were given. Make sure every
criterion is verified by at least one test case, and give high-risk criteria a negative
or boundary test as well as a positive one. A test case that checks something outside the
listed criteria should use an empty array."""

GAP_SYSTEM_PROMPT = SYSTEM_PROMPT.split("Return between")[0].rstrip() + """

You are completing an existing test set. Generate ONLY additional test cases for the
acceptance criteria listed as NOT COVERED. Do not repeat existing test cases. Add the
field "covers": an array of the criterion IDs each new test case verifies (use only the
IDs given). Return between 1 and 6 test cases."""


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


def validate_test_cases(test_cases: list[dict], criteria: list[dict] | None = None) -> list[str]:
    """
    Returns a list of human-readable problems (empty list = all good).
    Checks required fields, allowed enum values, and that steps is a
    non-empty list of strings. The optional "covers" field must be a list of
    strings; when `criteria` is given, every id in it must exist.
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
        if "covers" in tc:
            covers = tc["covers"]
            if not isinstance(covers, list) or not all(isinstance(c, str) for c in covers):
                issues.append(f"{label}: 'covers' must be a list of criterion IDs.")
            elif criteria is not None:
                known = {c["id"] for c in criteria}
                for bad in (c for c in covers if c not in known):
                    issues.append(f"{label}: 'covers' names '{bad}', which is not an acceptance criterion.")
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

def _text_of(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text")


def _criteria_block(criteria: list[dict]) -> str:
    return "\n".join(f"{c['id']}: {c['text']}" for c in criteria)


def call_claude(client: Anthropic, requirement_text: str, criteria: list[dict] | None = None) -> list[dict]:
    """Without `criteria` this is the original call. With them, the model must also trace each case to criterion IDs."""
    system = SYSTEM_PROMPT
    content = f"Requirement:\n\n{requirement_text}"
    if criteria:
        system += TRACEABILITY_ADDENDUM
        content += f"\n\nAcceptance criteria (use these IDs):\n{_criteria_block(criteria)}"
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3500 if criteria else 2000,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return parse_model_output(_text_of(response))


def call_claude_for_gaps(client: Anthropic, requirement_text: str, gaps: list[dict],
                         existing_cases: list[dict]) -> list[dict]:
    """Second pass: ask only for test cases covering the criteria that no existing case claims."""
    titles = "\n".join(f"- {tc.get('title', '')}" for tc in existing_cases if isinstance(tc, dict))
    content = (f"Requirement:\n\n{requirement_text}\n\n"
               f"Existing test case titles (do not repeat):\n{titles}\n\n"
               f"NOT COVERED acceptance criteria:\n{_criteria_block(gaps)}")
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2000, system=GAP_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return parse_model_output(_text_of(response))


def generate_with_coverage(client: Anthropic, requirement_text: str, max_followups: int = 1,
                           case_limit: int = MAX_CASES) -> dict:
    """
    Generates test cases; if the story has acceptance criteria, traces them and asks once more
    for any criterion that no test case claims. Returns
    {"criteria", "cases", "report", "followups", "followup_error"}. A failed follow-up never loses
    the first result.
    """
    criteria = traceability.extract_criteria(requirement_text)
    cases = call_claude(client, requirement_text, criteria or None)
    followups, followup_error = 0, None

    if criteria:
        for _ in range(max_followups):
            gaps = traceability.uncovered_criteria(traceability.build_coverage(cases, criteria))
            if not gaps or len(cases) >= case_limit:
                break
            followups += 1
            try:
                extra = call_claude_for_gaps(client, requirement_text, gaps, cases)
            except ModelOutputError as e:
                followup_error = str(e)
                break
            have = {str(tc.get("title", "")).strip().lower() for tc in cases if isinstance(tc, dict)}
            fresh = [tc for tc in extra if isinstance(tc, dict)
                     and str(tc.get("title", "")).strip().lower() not in have]
            cases = cases + fresh[: max(0, case_limit - len(cases))]

    report = traceability.build_coverage(cases, criteria) if criteria else None
    return {"criteria": criteria, "cases": cases, "report": report,
            "followups": followups, "followup_error": followup_error}


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


def write_csv(file_obj, test_cases: list[dict], include_coverage: bool = False):
    """include_coverage adds a final column listing the acceptance criteria each case claims to cover."""
    fieldnames = CSV_FIELDNAMES + ([CSV_COVERAGE_COLUMN] if include_coverage else [])
    writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
    writer.writeheader()
    for i, tc in enumerate(test_cases, start=1):
        steps = tc.get("steps", [])
        numbered_steps = "\n".join(f"{j}. {s}" for j, s in enumerate(steps, start=1))
        row = {
            "Test Case ID": f"TC-{i:03d}",
            "Title": _safe_cell(tc.get("title", "")),
            "Priority": _safe_cell(tc.get("priority", "")),
            "Type": _safe_cell(tc.get("type", "")),
            "Preconditions": _safe_cell(tc.get("preconditions", "")),
            "Steps": _safe_cell(numbered_steps),
            "Expected Result": _safe_cell(tc.get("expected_result", "")),
        }
        if include_coverage:
            covers = tc.get("covers") if isinstance(tc.get("covers"), list) else []
            row[CSV_COVERAGE_COLUMN] = _safe_cell(", ".join(str(c) for c in covers))
        writer.writerow(row)


def to_csv_string(test_cases: list[dict], include_coverage: bool = False) -> str:
    buffer = io.StringIO()
    write_csv(buffer, test_cases, include_coverage)
    return buffer.getvalue()


def save_json(test_cases: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, ensure_ascii=False, indent=2)


def save_csv(test_cases: list[dict], path: Path, include_coverage: bool = False):
    with open(path, "w", newline="", encoding="utf-8") as f:
        write_csv(f, test_cases, include_coverage)


def main():
    parser = argparse.ArgumentParser(description="Generate QA test cases from a user story.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=str, help="Path to a .txt file with the requirement")
    group.add_argument("--text", type=str, help="Requirement text passed directly")
    parser.add_argument("--max-followups", type=int, default=1,
                        help="extra model rounds allowed to cover criteria that no test case claims (default 1)")
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
        result = generate_with_coverage(client, requirement_text, max_followups=args.max_followups)
    except ModelOutputError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    test_cases, criteria, report = result["cases"], result["criteria"], result["report"]

    issues = validate_test_cases(test_cases, criteria or None)
    if issues:
        print("WARNING: the model's output has problems:")
        for issue in issues:
            print(f"  - {issue}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "test_cases.csv"
    json_path = OUTPUT_DIR / "test_cases.json"

    save_csv(test_cases, csv_path, include_coverage=bool(criteria))
    save_json(test_cases, json_path)

    print(f"Generated {len(test_cases)} test cases.")
    print(f"Coverage: {coverage_summary(test_cases)}")
    print(f"Saved to {csv_path}")
    print(f"Saved to {json_path}")

    if report:
        s = report["summary"]
        report_path = OUTPUT_DIR / "coverage_report.md"
        report_path.write_text(traceability.render_markdown(report, test_cases), encoding="utf-8")
        print(f"Acceptance criteria covered: {s['covered']}/{s['criteria']} ({s['percent']}%), "
              f"{s['uncovered']} not covered, {len(report['suspect_links'])} link(s) to check by hand "
              f"(follow-up rounds used: {result['followups']})")
        if result["followup_error"]:
            print(f"NOTE: the follow-up round failed and was skipped: {result['followup_error']}")
        print(f"Saved to {report_path}")
    else:
        print("No 'Acceptance Criteria:' section found, so no coverage report was produced.")


if __name__ == "__main__":
    main()
