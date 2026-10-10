import csv
import io

import agent


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_header_matches_zephyr_style_columns(good_case):
    text = agent.to_csv_string([good_case])
    assert text.splitlines()[0] == ",".join(agent.CSV_FIELDNAMES)


def test_ids_are_sequential_and_zero_padded(good_case):
    rows = _rows(agent.to_csv_string([good_case, good_case, good_case]))
    assert [r["Test Case ID"] for r in rows] == ["TC-001", "TC-002", "TC-003"]


def test_steps_are_numbered_on_separate_lines(good_case):
    row = _rows(agent.to_csv_string([good_case]))[0]
    assert row["Steps"] == "1. Open login page\n2. Enter credentials\n3. Submit"


def test_commas_quotes_and_newlines_survive_a_round_trip(good_case):
    good_case["title"] = 'Reset, then "login" again'
    good_case["preconditions"] = "Line one\nLine two"
    row = _rows(agent.to_csv_string([good_case]))[0]
    assert row["Title"] == 'Reset, then "login" again'
    assert row["Preconditions"] == "Line one\nLine two"


def test_unicode_is_preserved(good_case):
    good_case["title"] = "পাসওয়ার্ড রিসেট - Résumé"
    row = _rows(agent.to_csv_string([good_case]))[0]
    assert row["Title"] == "পাসওয়ার্ড রিসেট - Résumé"


def test_formula_injection_is_neutralised(good_case):
    good_case["title"] = '=HYPERLINK("http://evil.example","click")'
    good_case["expected_result"] = "+1+1"
    row = _rows(agent.to_csv_string([good_case]))[0]
    assert row["Title"].startswith("'=")
    assert row["Expected Result"].startswith("'+")


def test_normal_text_is_not_altered(good_case):
    row = _rows(agent.to_csv_string([good_case]))[0]
    assert row["Title"] == good_case["title"]


def test_save_csv_and_json_write_files(tmp_path, good_case):
    csv_path, json_path = tmp_path / "t.csv", tmp_path / "t.json"
    agent.save_csv([good_case], csv_path)
    agent.save_json([good_case], json_path)
    assert csv_path.read_text(encoding="utf-8").startswith("Test Case ID")
    assert '"title": "Login with valid credentials"' in json_path.read_text(encoding="utf-8")
