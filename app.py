"""
app.py
Streamlit web UI for the QA test case generator.

- Works instantly with no setup: it opens with a pre-generated example for
  the sample password-reset story, so a visitor can see the output format,
  the validation report and the CSV download without an API key.
- With an Anthropic API key in the sidebar, it generates fresh test cases for
  any user story you paste, traces them to the story's acceptance criteria and
  asks once more for any criterion that no test case covers.

Run with:
    streamlit run app.py
"""

import json
import os
from pathlib import Path

import streamlit as st
from anthropic import Anthropic

import agent
import traceability

ROOT = Path(__file__).parent
SAMPLE_STORY = (ROOT / "sample_input" / "user_story.txt").read_text(encoding="utf-8")
EXAMPLE_CASES = json.loads((ROOT / "sample_output" / "example_with_coverage.json").read_text(encoding="utf-8"))
EXAMPLE_CRITERIA = traceability.extract_criteria(SAMPLE_STORY)

st.set_page_config(page_title="QA Test Case Generator", page_icon="🧪", layout="wide")

def _load_example():
    st.session_state.cases = EXAMPLE_CASES
    st.session_state.criteria = EXAMPLE_CRITERIA
    st.session_state.followups = 0
    st.session_state.followup_error = None
    st.session_state.source = "example"


if "cases" not in st.session_state:
    _load_example()

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
        _load_example()
        st.rerun()

st.title("🧪 QA Test Case Generator")
st.caption(
    "Turns a user story into structured test cases (positive, negative, boundary, security) "
    "and exports a Zephyr/Jira-ready CSV. The model's output is validated and sanitized before export."
)

story = st.text_area("User story / requirement", value=SAMPLE_STORY, height=260)
detected = traceability.extract_criteria(story)
if detected:
    st.caption(f"Detected {len(detected)} acceptance criteria (AC-1 to AC-{len(detected)}). "
               "Generated test cases will be traced to them.")
else:
    st.caption("No 'Acceptance Criteria:' section found. Test cases will be generated without a coverage report.")

if st.button("✨ Generate test cases with Claude", type="primary"):
    if not api_key:
        st.warning("Enter your Anthropic API key in the sidebar to generate new cases. "
                   "The example below works without a key.")
    elif not story.strip():
        st.warning("Paste a user story first.")
    else:
        try:
            with st.spinner("Generating test cases..."):
                result = agent.generate_with_coverage(Anthropic(api_key=api_key), story)
                st.session_state.cases = result["cases"]
                st.session_state.criteria = result["criteria"]
                st.session_state.followups = result["followups"]
                st.session_state.followup_error = result["followup_error"]
                st.session_state.source = "claude"
        except agent.ModelOutputError as e:
            st.error(f"The model's reply could not be parsed: {e}")
        except Exception as e:
            st.error(f"Request failed: {e}")

cases = st.session_state.cases
criteria = st.session_state.criteria
issues = agent.validate_test_cases(cases, criteria or None)
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

if criteria:
    st.subheader("Requirement coverage")
    if st.session_state.source == "example":
        st.info("The test cases in this example were generated earlier by Claude. The criterion links (`covers`) "
                "were added by hand to illustrate the report. Generate with your own key to get the model's own mapping.")

    dropped = st.multiselect(
        "What if these test cases were removed? (simulation, changes nothing)",
        options=[f"TC-{i:03d}" for i in range(1, len(cases) + 1)],
    )
    kept = [c for i, c in enumerate(cases, start=1) if f"TC-{i:03d}" not in dropped]
    report = traceability.build_coverage(kept, criteria)
    if dropped:
        st.caption("Note: IDs below are renumbered after removal.")
    s = report["summary"]

    m = st.columns(4)
    m[0].metric("Criteria", s["criteria"])
    m[1].metric("Covered", f"{s['covered']} ({s['percent']}%)")
    m[2].metric("Not covered", s["uncovered"])
    m[3].metric("Only positive tests", s["thin"])

    if st.session_state.followups:
        st.caption(f"{st.session_state.followups} follow-up request(s) were made for uncovered criteria.")
    if st.session_state.followup_error:
        st.warning(f"A follow-up request failed and was skipped: {st.session_state.followup_error}")

    labels = {"covered": "✅ covered", "thin": "🟡 only positive", "uncovered": "❌ not covered"}
    st.dataframe(
        [{"Criterion": r["id"], "Text": r["text"], "Status": labels[r["status"]],
          "Test cases": ", ".join(r["tests"]), "Types": ", ".join(r["types"])} for r in report["rows"]],
        use_container_width=True, hide_index=True,
    )
    for r in report["rows"]:
        if r["status"] == "uncovered":
            st.warning(f"{r['id']} is not covered by any test case: {r['text']}")
    if report["suspect_links"]:
        with st.expander(f"🔎 {len(report['suspect_links'])} link(s) to check by hand"):
            st.caption("These test cases claim a criterion but share no key words with it.")
            for x in report["suspect_links"]:
                st.write(f"- {x['test']} claims {x['criterion']}")
    if report["unknown_refs"]:
        with st.expander(f"⚠️ {len(report['unknown_refs'])} reference(s) to criteria that do not exist"):
            for x in report["unknown_refs"]:
                st.write(f"- {x['test']} references {x['criterion']}")
    if report["untraced"]:
        with st.expander(f"{len(report['untraced'])} test case(s) not linked to any criterion"):
            for t in report["untraced"]:
                tc = kept[int(t[3:]) - 1]
                st.write(f"- {t}: {tc.get('title', '') if isinstance(tc, dict) else ''}")
    st.caption("Coverage is claimed by the model. The checks above catch missing, invented and implausible links, "
               "but they cannot prove a test verifies its criterion. Review before accepting the set.")
    st.download_button("⬇️ Download coverage report (Markdown)",
                       data=traceability.render_markdown(report, kept),
                       file_name="coverage_report.md", mime="text/markdown", use_container_width=True)

left, right = st.columns(2)
left.download_button(
    "⬇️ Download CSV (Zephyr/Jira import)",
    data=agent.to_csv_string([c for c in cases if isinstance(c, dict)], include_coverage=bool(criteria)),
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
