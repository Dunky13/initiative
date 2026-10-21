"""AI work on a task or a file, on the connection the community resolves to.

The request path itself (each shape, the pinned egress, the errors) is
``ai_provider_test``; this covers what generation asks for and what it makes
of the answer.
"""

import json
from unittest.mock import patch

import httpx
import pytest

from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider, ConnectionScope, ResolvedAISettings
from app.services import ai_generation, ai_provider, safe_http
from app.services.ai_provider import AIRequestError


class _Task:
    def __init__(self, title: str = "Ship it", description: str = "Do the thing"):
        self.title = title
        self.description = description


class _User:
    locale = "en"


def _resolving_to(monkeypatch, **overrides) -> list[tuple]:
    """Resolve to one connection, and keep what is written of its health."""
    resolved = ResolvedAISettings(
        **{
            "enabled": True,
            "provider": AIProvider.groq,
            "api_key": "test-key",
            "model": "m",
            "scope": ConnectionScope.community,
            "connection_id": 3,
            "source": "community",
            **overrides,
        }
    )
    health: list[tuple] = []

    async def resolve(*args, **kwargs):
        return resolved

    async def record_health(*args):
        health.append(args)

    monkeypatch.setattr(ai_generation, "resolve_ai_settings", resolve)
    monkeypatch.setattr(ai_generation, "record_health", record_health)
    return health


async def test_a_checklist_is_asked_for_as_json_and_tidied(monkeypatch):
    sent: list[dict] = []
    answer = {"items": [" Book the hall ", "", "x" * 300]}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(answer)},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        ai_provider,
        "PinnedTransport",
        lambda *, allow_private, max_bytes: safe_http.PinnedTransport(
            allow_private=allow_private,
            max_bytes=max_bytes,
            inner=httpx.MockTransport(handler),
        ),
    )
    health = _resolving_to(monkeypatch)

    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=[(2, 0, 0, "", ("93.184.216.34", 0))],
    ):
        steps = await ai_generation.generate_checklist(None, _User(), 1, _Task())

    assert steps[0] == "Book the hall"
    assert len(steps) == 2 and steps[1].endswith("...")
    system = sent[0]["messages"][0]["content"]
    assert '{"items":' in system
    # The connection answered, so it is well.
    assert health == [(ConnectionScope.community, 3, 1, None)]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"enabled": False, "provider": None}, AIMessages.NOT_ENABLED),
        ({"enabled": False, "api_key": None}, AIMessages.NOT_CONFIGURED),
    ],
)
async def test_a_connection_that_cannot_answer_says_why(monkeypatch, overrides, code):
    _resolving_to(monkeypatch, **overrides)
    with pytest.raises(AIRequestError) as refused:
        await ai_generation.generate_description(None, _User(), 1, _Task())
    assert refused.value.code == code


async def test_an_empty_file_is_not_sent(monkeypatch):
    _resolving_to(monkeypatch)
    with pytest.raises(AIRequestError) as refused:
        await ai_generation.generate_file_summary(None, _User(), 1, None, "Notes")
    assert refused.value.code == AIMessages.DOCUMENT_EMPTY
