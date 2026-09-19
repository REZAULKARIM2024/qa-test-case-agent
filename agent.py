"""
agent.py
Takes a user story / requirement and generates structured QA test cases
using Claude, then exports them as Zephyr/Jira-import-ready CSV + raw JSON.

Usage:
    python agent.py --file sample_input/user_story.txt
    python agent.py --text "As a user, I want to ..."
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic

OUTPUT_DIR = Path(__file__).parent / "output"
CLAUDE_MODEL = "claude-sonnet-4-6"

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


def call_claude(client: Anthropic, requirement_text: str) -> list[dict]:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Requirement:\n\n{requirement_text}"}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")

    # Defensive parsing: strip accidental markdown fences if the model adds them
    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    try:
        test_cases = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print("ERROR: Could not parse model output as JSON.")
        print("Raw output was:\n", raw_text)
        raise e

    return test_cases


def save_json(test_cases: list[dict], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(test_cases, f, ensure_ascii=False, indent=2)


def save_csv(test_cases: list[dict], path: Path):
    fieldnames = [
        "Test Case ID",
        "Title",
        "Priority",
        "Type",
        "Preconditions",
        "Steps",
        "Expected Result",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, tc in enumerate(test_cases, start=1):
            steps = tc.get("steps", [])
            numbered_steps = "\n".join(f"{j}. {s}" for j, s in enumerate(steps, start=1))
            writer.writerow({
                "Test Case ID": f"TC-{i:03d}",
                "Title": tc.get("title", ""),
                "Priority": tc.get("priority", ""),
                "Type": tc.get("type", ""),
                "Preconditions": tc.get("preconditions", ""),
                "Steps": numbered_steps,
                "Expected Result": tc.get("expected_result", ""),
            })


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
    test_cases = call_claude(client, requirement_text)

    OUTPUT_DIR.mkdir(exist_ok=True)
    csv_path = OUTPUT_DIR / "test_cases.csv"
    json_path = OUTPUT_DIR / "test_cases.json"

    save_csv(test_cases, csv_path)
    save_json(test_cases, json_path)

    print(f"Generated {len(test_cases)} test cases.")
    print(f"Saved to {csv_path}")
    print(f"Saved to {json_path}")


if __name__ == "__main__":
    main()
