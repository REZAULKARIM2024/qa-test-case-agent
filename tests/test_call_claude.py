"""call_claude with a fake client: runs offline, instantly, costs nothing."""
import json
from types import SimpleNamespace

import pytest

import agent


class FakeMessages:
    def __init__(self, reply):
        self.reply = reply
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


class FakeClient:
    def __init__(self, reply):
        self.messages = FakeMessages(reply)


def test_call_claude_returns_parsed_cases(good_case):
    client = FakeClient(json.dumps([good_case]))
    assert agent.call_claude(client, "As a user ...") == [good_case]


def test_requirement_text_is_sent_to_the_model(good_case):
    client = FakeClient(json.dumps([good_case]))
    agent.call_claude(client, "Password reset story")
    sent = client.messages.kwargs["messages"][0]["content"]
    assert "Password reset story" in sent
    assert client.messages.kwargs["system"] == agent.SYSTEM_PROMPT


def test_fenced_reply_is_handled(good_case):
    client = FakeClient("```json\n" + json.dumps([good_case]) + "\n```")
    assert agent.call_claude(client, "x") == [good_case]


def test_garbage_reply_raises_model_output_error():
    with pytest.raises(agent.ModelOutputError):
        agent.call_claude(FakeClient("I'm sorry, I can't help."), "x")


def test_system_prompt_names_every_test_type_and_priority():
    for word in (*agent.ALLOWED_TYPES, *agent.ALLOWED_PRIORITIES):
        assert word in agent.SYSTEM_PROMPT
