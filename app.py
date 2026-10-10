"""
app.py
Streamlit web UI for the QA test case generator.

- Works instantly with no setup: it opens with a pre-generated example for
  the sample password-reset story, so a visitor can see the output format,
  the validation report and the CSV download without an API key.
- With an Anthropic API key in the sidebar, it generates fresh test cases for
  any user story you paste.

Run with:
    streamlit run app.py
"""

import json
import os
from pathlib import Path

import streamlit as st
from anthropic import Anthropic

import agent

ROOT = Path(__file__).parent
SAMPLE_STORY = (ROOT / "sample_input" / "user_story.txt").read_text(encoding="utf-8")
EXAMPLE_CASES = json.loads((ROOT / "sample_output" / "example_test_cases.json").read_text(encoding="utf-8"))

st.set_page_config(page_title="QA Test Case Generator", page_icon="🧪", layout="wide")

if "cases" not in st.session_state:
    st.session_state.cases = EXAMPLE_CASES
    st.session_state.source = "example"

with st.sidebar:
    st.header("🔑 Generate your own")
    api_key = st.text_input(
        "Anthropic API key",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Used only for this session to call Claude. It is never stored.",
    )
    if not api_key:
        st.caption("No key? Browse the built-in example on the right. It was generated for the sample story.")
    if st.button("↩️ Reset to example", use_container_width=True):
        st.session_state.cases = EXAMPLE_CASES
        st.session_state.source = "example"
        st.rerun()

st.title("🧪 QA Test Case Generator")
st.caption(
    "Turns a user story into structured test cases (positive, negative, boundary, security) "
    "and exports a Zephyr/Jira-ready CSV. The model's output is validated and sanitized before export."
)

story = st.text_area("User story / requirement", value=SAMPLE_STORY, height=260)

if st.button("✨ Generate test cases with Claude", type="primary"):
    if not api_key:
        st.warning("Enter your Anthropic API key in the sidebar to generate new cases. "
                   "The example below works without a key.")
    elif not story.strip():
        st.warning("Paste a user story first.")
    else:
        try:
            with st.spinner("Generating test cases..."):
                st.session_state.cases = agent.call_claude(Anthropic(api_key=api_key), story)
                st.session_state.source = "claude"
        except agent.ModelOutputError as e:
            st.error(f"The model's reply could not be parsed: {e}")
        except Exception as e:
            st.error(f"Request failed: {e}")

cases = st.session_state.cases
issues = agent.validate_test_cases(cases)
coverage = agent.coverage_summary(cases)

st.subheader(
    "Example output (pre-generated)" if st.session_state.source == "example" else "Generated test cases"
)

cols = st.columns(len(coverage) + 1)
cols[0].metric("Total", len(cases))
for col, (kind, count) in zip(cols[1:], coverage.items()):
    col.metric(kind, count)

if issues:
    with st.expander(f"⚠️ {len(issues)} validation issue(s)", expanded=True):
        for issue in issues:
            st.write(f"- {issue}")
else:
    st.success("Validation passed: all required fields present, priorities and types are valid.")

for i, tc in enumerate(cases, start=1):
    if not isinstance(tc, dict):
        continue
    header = f"TC-{i:03d} · {tc.get('title', '(no title)')}  —  {tc.get('type', '?')} / {tc.get('priority', '?')}"
    with st.expander(header):
        st.markdown(f"**Preconditions:** {tc.get('preconditions', '')}")
        st.markdown("**Steps:**")
        for j, step in enumerate(tc.get("steps", []), start=1):
            st.markdown(f"{j}. {step}")
        st.markdown(f"**Expected result:** {tc.get('expected_result', '')}")

left, right = st.columns(2)
left.download_button(
    "⬇️ Download CSV (Zephyr/Jira import)",
    data=agent.to_csv_string([c for c in cases if isinstance(c, dict)]),
    file_name="test_cases.csv",
    mime="text/csv",
    use_container_width=True,
)
right.download_button(
    "⬇️ Download JSON",
    data=json.dumps(cases, ensure_ascii=False, indent=2),
    file_name="test_cases.json",
    mime="application/json",
    use_container_width=True,
)
