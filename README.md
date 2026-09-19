# QA Test Case Generator Agent

An AI agent that takes a user story / requirement (plain text) and automatically
generates a structured set of test cases — positive, negative, edge, and boundary
scenarios — formatted so they can be imported straight into **Jira/Zephyr** (CSV).

Built to demonstrate "AI-augmented QA Engineering" — combining real QA domain
knowledge (test design technique, Zephyr fields) with LLM automation.

## How it works

```
requirement text (.txt) or pasted in terminal
        │
        ▼
  agent.py ──► builds a QA-expert prompt ──► sends to Claude
        │
        ▼
  Claude returns structured JSON test cases
        │
        ▼
  agent.py validates + writes:
     - output/test_cases.csv   (Zephyr/Jira import-ready)
     - output/test_cases.json  (raw structured data)
```

The prompt explicitly asks Claude to apply standard test design techniques —
equivalence partitioning, boundary value analysis, negative testing, and
common QA fields (Priority, Preconditions, Steps, Expected Result) — so the
output looks like something a QA engineer would actually write, not generic text.

## Setup

```bash
cd qa-test-case-agent
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key-here"
```

## Usage

**Option A — from a file:**

```bash
python agent.py --file sample_input/user_story.txt
```

**Option B — paste directly:**

```bash
python agent.py --text "As a user, I want to reset my password via email so that I can regain account access if I forget my credentials."
```

Output:

```
Generated 9 test cases.
Saved to output/test_cases.csv
Saved to output/test_cases.json
```

Open `output/test_cases.csv` — it has columns matching common Zephyr import
fields: `Test Case ID, Title, Priority, Type, Preconditions, Steps, Expected Result`.

## Project structure

```
qa-test-case-agent/
├── agent.py                     # main CLI agent
├── sample_input/user_story.txt  # example requirement to try it on
├── output/                      # generated CSV/JSON (gitignored)
├── requirements.txt
└── README.md
```

## What this demonstrates 

- Prompt engineering for structured, domain-specific output (JSON schema)
- Applying real QA test-design techniques (boundary, negative, equivalence)
- Building a practical LLM-powered internal tool, not just a chat demo
- Output formatted for direct integration into existing QA tools (Jira/Zephyr)

## Possible extensions

- Pull user stories directly from Jira via its REST API instead of a text file
- Auto-create the generated cases as Zephyr test cases via their API
- Add a second agent pass that also generates Selenium/Playwright test stubs
  from the generated test cases (this would tie directly into your existing
  automation framework skills)
