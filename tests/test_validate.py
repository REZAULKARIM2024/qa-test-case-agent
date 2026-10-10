import agent


def test_example_output_is_valid(example_cases):
    assert agent.validate_test_cases(example_cases) == []


def test_empty_list_is_reported():
    assert agent.validate_test_cases([]) == ["No test cases were generated."]


def test_missing_field_is_reported(good_case):
    del good_case["expected_result"]
    issues = agent.validate_test_cases([good_case])
    assert any("expected_result" in i for i in issues)


def test_empty_steps_is_reported(good_case):
    good_case["steps"] = []
    issues = agent.validate_test_cases([good_case])
    assert any("steps" in i for i in issues)


def test_invalid_priority_is_reported(good_case):
    good_case["priority"] = "Urgent"
    issues = agent.validate_test_cases([good_case])
    assert any("priority" in i for i in issues)


def test_invalid_type_is_reported(good_case):
    good_case["type"] = "Smoke"
    issues = agent.validate_test_cases([good_case])
    assert any("type" in i for i in issues)


def test_steps_must_be_strings(good_case):
    good_case["steps"] = [1, 2, 3]
    issues = agent.validate_test_cases([good_case])
    assert any("list of strings" in i for i in issues)


def test_non_object_entry_is_reported():
    issues = agent.validate_test_cases(["not a dict"])
    assert any("not an object" in i for i in issues)


def test_coverage_summary_counts_every_type(example_cases):
    summary = agent.coverage_summary(example_cases)
    assert set(summary) == set(agent.ALLOWED_TYPES)
    assert sum(summary.values()) == len(example_cases)


def test_example_covers_all_four_test_types(example_cases):
    summary = agent.coverage_summary(example_cases)
    assert all(count >= 1 for count in summary.values())
