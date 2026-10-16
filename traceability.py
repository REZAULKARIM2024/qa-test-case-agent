"""
coverage.py
Requirement traceability for generated test cases. Everything here is deterministic
(no model calls), so it is cheap to test and its results can be trusted more than the
model's own claims:

  extract_criteria  - pulls the acceptance criteria out of a user story (AC-1, AC-2, ...)
  build_coverage    - which criteria are covered, by which test cases, and what looks wrong
  render_markdown   - a review report a human can read before accepting the test set

The model's `covers` field is a CLAIM. This module checks what it can (ids exist, a claimed
link shares at least some vocabulary with the criterion) but it cannot prove a test really
verifies a criterion. A human review is still required, and the report says so.
"""

import re

MAX_CRITERIA = 40
MAX_CRITERIA_CHARS = 500

_HEADER = re.compile(r"^\s*(acceptance\s+criteria|ac)\s*:?\s*$", re.IGNORECASE)
_OTHER_HEADER = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /&'-]{0,40}:\s*$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(.*)$")
_GIVEN = re.compile(r"^\s*given\b", re.IGNORECASE)

_STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "when", "then", "than", "into", "must", "should",
    "their", "there", "which", "while", "shall", "user", "users", "system", "after", "before", "been",
    "being", "each", "other", "only", "also", "does", "they", "them", "your", "about", "within",
}


# ---------------------------------------------------------------------------
# Extracting criteria
# ---------------------------------------------------------------------------

def extract_criteria(story_text: str) -> list[dict]:
    """
    Finds the 'Acceptance Criteria' section and returns [{"id": "AC-1", "text": ...}].
    Accepts bullets (- * •), numbered lines (1. / 1)) and Given/When/Then blocks; wrapped
    lines are joined to the criterion above. Returns [] when no such section exists.
    """
    lines = (story_text or "").splitlines()
    start = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if start is None:
        return []

    items: list[str] = []
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if _OTHER_HEADER.match(line) and not _BULLET.match(line):
            break  # next section, e.g. "Notes:" or "Out of scope:"
        bullet = _BULLET.match(line)
        if bullet:
            items.append(bullet.group(1).strip())
        elif _GIVEN.match(line):
            items.append(line.strip())
        elif items:
            items[-1] += " " + line.strip()  # wrapped continuation
        # text before the first bullet is ignored

    cleaned = [re.sub(r"\s+", " ", t)[:MAX_CRITERIA_CHARS] for t in items if t]
    return [{"id": f"AC-{i}", "text": t} for i, t in enumerate(cleaned[:MAX_CRITERIA], start=1)]


# ---------------------------------------------------------------------------
# Checking the model's traceability claims
# ---------------------------------------------------------------------------

def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{4,}", (text or "").lower())
    return {w[:5] for w in words if w not in _STOPWORDS}


def case_text(tc: dict) -> str:
    steps = tc.get("steps") if isinstance(tc.get("steps"), list) else []
    return " ".join(str(x) for x in [tc.get("title", ""), tc.get("preconditions", ""), *steps,
                                     tc.get("expected_result", "")])


def shares_vocabulary(criterion_text: str, tc: dict) -> bool:
    """Cheap sanity check: a test that claims to cover a criterion should mention at least one of its key words."""
    return bool(_stems(criterion_text) & _stems(case_text(tc)))


def _claimed_ids(tc) -> list[str]:
    covers = tc.get("covers") if isinstance(tc, dict) else None
    if not isinstance(covers, list):
        return []
    seen, out = set(), []
    for c in covers:
        if isinstance(c, str) and c.strip() and c.strip() not in seen:
            seen.add(c.strip())
            out.append(c.strip())
    return out


def build_coverage(test_cases: list[dict], criteria: list[dict]) -> dict:
    """
    Returns {"rows": [...], "summary": {...}, "unknown_refs": [...], "untraced": [...], "suspect_links": [...]}.
    Row status: "uncovered" (no test claims it), "thin" (covered, but only by Positive cases, so no negative or
    boundary check), or "covered".
    """
    known = {c["id"]: c for c in criteria}
    claims: dict[str, list[int]] = {cid: [] for cid in known}
    unknown_refs, untraced, suspect = [], [], []

    for idx, tc in enumerate(test_cases, start=1):
        tc_id = f"TC-{idx:03d}"
        ids = _claimed_ids(tc)
        valid = [i for i in ids if i in known]
        for bad in (i for i in ids if i not in known):
            unknown_refs.append({"test": tc_id, "criterion": bad})
        if not valid:
            untraced.append(tc_id)
        for cid in valid:
            claims[cid].append(idx)
            if isinstance(tc, dict) and not shares_vocabulary(known[cid]["text"], tc):
                suspect.append({"test": tc_id, "criterion": cid})

    rows = []
    for cid, c in known.items():
        idxs = claims[cid]
        types = []
        for i in idxs:
            t = test_cases[i - 1].get("type") if isinstance(test_cases[i - 1], dict) else None
            if t and t not in types:
                types.append(t)
        if not idxs:
            status = "uncovered"
        elif set(types) <= {"Positive"}:
            status = "thin"
        else:
            status = "covered"
        rows.append({"id": cid, "text": c["text"], "tests": [f"TC-{i:03d}" for i in idxs],
                     "types": types, "status": status})

    n = len(rows)
    covered = sum(1 for r in rows if r["status"] != "uncovered")
    return {
        "rows": rows,
        "summary": {"criteria": n, "covered": covered, "uncovered": n - covered,
                    "thin": sum(1 for r in rows if r["status"] == "thin"),
                    "percent": round(100 * covered / n) if n else 0,
                    "test_cases": len(test_cases)},
        "unknown_refs": unknown_refs,
        "untraced": untraced,
        "suspect_links": suspect,
    }


def uncovered_criteria(report: dict) -> list[dict]:
    return [{"id": r["id"], "text": r["text"]} for r in report["rows"] if r["status"] == "uncovered"]


# ---------------------------------------------------------------------------
# Review report
# ---------------------------------------------------------------------------

def _cell(text) -> str:
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def render_markdown(report: dict, test_cases: list[dict]) -> str:
    s = report["summary"]
    out = ["# Test coverage review", "",
           f"- Acceptance criteria: **{s['criteria']}**",
           f"- Covered by at least one test case: **{s['covered']}** ({s['percent']}%)",
           f"- Not covered: **{s['uncovered']}**",
           f"- Covered only by Positive cases (no negative/boundary check): **{s['thin']}**",
           f"- Test cases: **{s['test_cases']}**", "",
           "## Criteria", "", "| ID | Criterion | Status | Test cases | Types |", "|---|---|---|---|---|"]
    for r in report["rows"]:
        out.append(f"| {r['id']} | {_cell(r['text'])} | {r['status']} | {', '.join(r['tests']) or '-'} | "
                   f"{', '.join(r['types']) or '-'} |")

    def section(title, lines):
        if lines:
            out.extend(["", f"## {title}", "", *lines])

    section("Not covered (generate or write these)", [f"- {r['id']}: {_cell(r['text'])}" for r in report["rows"]
                                                       if r["status"] == "uncovered"])
    section("Links to check by hand (the test shares no key words with the criterion it claims)",
            [f"- {x['test']} claims {x['criterion']}" for x in report["suspect_links"]])
    section("References to criteria that do not exist (model error)",
            [f"- {x['test']} references {x['criterion']}" for x in report["unknown_refs"]])
    section("Test cases not linked to any criterion (extra, or the model did not trace them)",
            [f"- {t}: {_cell(test_cases[int(t[3:]) - 1].get('title', ''))}" for t in report["untraced"]
             if isinstance(test_cases[int(t[3:]) - 1], dict)])
    out += ["", "## How to read this", "",
            "- Traceability is **claimed by the model**. This report checks that referenced criteria exist and that "
            "each link shares at least some vocabulary with its criterion. It cannot prove a test actually verifies the criterion.",
            "- A reviewer should still read each test case against its criterion before accepting the set.", ""]
    return "\n".join(out)
