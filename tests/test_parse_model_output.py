import json

import pytest

import agent


def test_plain_json_array_is_parsed():
    raw = json.dumps([{"title": "a"}])
    assert agent.parse_model_output(raw) == [{"title": "a"}]


def test_markdown_fences_are_stripped():
    raw = "```json\n[{\"title\": \"a\"}]\n```"
    assert agent.parse_model_output(raw) == [{"title": "a"}]


def test_prose_around_the_array_is_ignored():
    raw = 'Here are your test cases:\n[{"title": "a"}]\nHope this helps!'
    assert agent.parse_model_output(raw) == [{"title": "a"}]


def test_no_json_raises_clear_error():
    with pytest.raises(agent.ModelOutputError):
        agent.parse_model_output("Sorry, I cannot do that.")


def test_broken_json_raises_clear_error():
    with pytest.raises(agent.ModelOutputError):
        agent.parse_model_output('[{"title": "a",}]')


def test_json_object_instead_of_array_is_rejected():
    with pytest.raises(agent.ModelOutputError):
        agent.parse_model_output('{"title": "a"}')
