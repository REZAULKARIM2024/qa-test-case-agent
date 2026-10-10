# QA Test Case Generator Agent

[![CI](https://github.com/REZAULKARIM2024/qa-test-case-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/REZAULKARIM2024/qa-test-case-agent/actions/workflows/ci.yml)

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
  agent.py parses defensively, validates the schema, then writes:
     - output/test_cases.csv   (Zephyr/Jira import-ready, formula-safe)
     - output/test_cases.json  (raw structured data)
```

The model's reply is treated as **untrusted input**: markdown fences and stray
prose are tolerated, every test case is checked for required fields and allowed
values (priority, type), and CSV cells that start with `=`, `+`, `-` or `@` are
neutralised so an imported file can never run a spreadsheet formula.

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

## Web UI

```bash
streamlit run app.py
```

The app opens with a pre-generated example for the sample password-reset story
(no API key needed), showing the validation report, coverage per test type and
CSV/JSON downloads. Paste an Anthropic API key in the sidebar to generate cases
for your own user story.

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

## Testing

The agent is tested like any other piece of software. The suite runs offline
(the Anthropic client is replaced by a fake), so it is instant and costs nothing:

```bash
pip install -r requirements-dev.txt
pytest -v
```

| Area | What is verified |
|---|---|
| Output parsing | plain JSON, markdown fences, prose around the array, broken JSON, wrong shape |
| Schema validation | missing fields, empty steps, invalid priority/type, non-string steps |
| CSV export | header, sequential IDs, numbered steps, commas/quotes/newlines, Unicode, **formula injection** |
| Model call | requirement text and system prompt reach the model; bad replies raise a clear error |
| Web UI | the Streamlit app loads, shows the example and handles a missing API key (Streamlit `AppTest`) |

GitHub Actions runs the suite on every push and pull request. The key tests were
also checked by mutation: breaking the injection guard or the priority check
makes the suite fail.

## Project structure

```
qa-test-case-agent/
├── agent.py                     # CLI agent: prompt, parsing, validation, export
├── app.py                       # Streamlit web UI
├── sample_input/user_story.txt  # example requirement to try it on
├── sample_output/               # pre-generated example used by the UI and tests
├── tests/                       # pytest suite (offline)
├── .github/workflows/ci.yml     # CI
├── output/                      # generated CSV/JSON (gitignored)
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## What this demonstrates 

- Prompt engineering for structured, domain-specific output (JSON schema)
- Applying real QA test-design techniques (boundary, negative, equivalence)
- Building a practical LLM-powered internal tool, not just a chat demo
- Output formatted for direct integration into existing QA tools (Jira/Zephyr)
- Treating LLM output as untrusted: schema validation and CSV-injection protection
- Testing an LLM application offline with fakes, plus CI on every push

## Possible extensions

- Pull user stories directly from Jira via its REST API instead of a text file
- Auto-create the generated cases as Zephyr test cases via their API
- Add a second agent pass that also generates Selenium/Playwright test stubs
  from the generated test cases (this would tie directly into your existing
  automation framework skills)
