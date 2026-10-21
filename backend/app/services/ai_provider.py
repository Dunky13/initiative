"""The AI providers: which request shape each speaks, and one call for each.

Two SDKs do the talking: ``anthropic`` for Claude, and ``openai`` for OpenAI
itself (its Responses API) and for every server that speaks the OpenAI Chat
Completions shape (the hosted presets, Ollama, and any custom server). Their
retries, typed errors and usage counts are what this module relies on. What it
adds is the presets, the pinned egress the OpenAI client sends through, the
reading of a reply, and one mapping of the SDKs' errors onto ``AIMessages``.

A connection always names its model; nothing here picks one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import anthropic
import httpx
import openai
from pydantic import BaseModel, ValidationError

from app.core.errors import CodedError
from app.core.messages import AIMessages
from app.schemas.ai_settings import AIProvider
from app.services.safe_http import PinnedTransport
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

_PROVIDER_FAULTS = frozenset(
    {AIMessages.PROVIDER_UNAVAILABLE, AIMessages.PROVIDER_ERROR}
)


class AIRequestError(CodedError):
    """A request for AI work that failed, with the message code and status
    the endpoint answers: a fault on the provider's side is a bad gateway."""

    def __init__(self, code: str) -> None:
        super().__init__(code, 502 if code in _PROVIDER_FAULTS else 400)


class Shape(str, Enum):
    """The request a provider takes."""

    anthropic = "anthropic"
    responses = "responses"
    chat = "chat"


@dataclass(frozen=True)
class Preset:
    shape: Shape
    #: The provider's own address. Without one, the connection gives it.
    base_url: str | None = None
    needs_key: bool = True
    #: A server somebody runs. The operator's may be at a private address.
    self_hosted: bool = False


PRESETS: dict[AIProvider, Preset] = {
    AIProvider.anthropic: Preset(Shape.anthropic, "https://api.anthropic.com"),
    AIProvider.openai: Preset(Shape.responses, "https://api.openai.com/v1"),
    AIProvider.gemini: Preset(
        Shape.chat, "https://generativelanguage.googleapis.com/v1beta/openai/"
    ),
    AIProvider.deepseek: Preset(Shape.chat, "https://api.deepseek.com"),
    AIProvider.groq: Preset(Shape.chat, "https://api.groq.com/openai/v1"),
    AIProvider.xai: Preset(Shape.chat, "https://api.x.ai/v1"),
    AIProvider.together: Preset(Shape.chat, "https://api.together.ai/v1"),
    AIProvider.openrouter: Preset(Shape.chat, "https://openrouter.ai/api/v1"),
    AIProvider.ollama: Preset(Shape.chat, needs_key=False, self_hosted=True),
    AIProvider.custom: Preset(Shape.chat, needs_key=False, self_hosted=True),
}

#: Upper bound on a listed catalog, only so a provider response stays a sane
#: payload. An OpenAI-compatible gateway can offer hundreds of models, so this
#: has to sit well above any real catalog; when it does trim, the list is
#: incomplete and callers must not read absence from it as "no such model".
MODEL_LIST_CAP = 1000


def allow_private(provider: AIProvider, scope: str) -> bool:
    """Whether a connection may reach a private address: only the operator's
    connection to a server somebody runs. Server-computed, never from request
    input."""
    return scope == "platform" and PRESETS[provider].self_hosted


def uses_base_url(provider: AIProvider) -> bool:
    """Whether the connection gives the address, rather than the preset."""
    return PRESETS[provider].base_url is None


def needs_key(provider: AIProvider) -> bool:
    return PRESETS[provider].needs_key


def _endpoint(provider: AIProvider, base_url: str | None) -> str:
    preset = PRESETS[provider]
    if preset.base_url is not None:
        return preset.base_url
    if not base_url:
        raise AIRequestError(AIMessages.INVALID_BASE_URL)
    url = base_url.rstrip("/")
    # Ollama answers the OpenAI shape under /v1, beside its own API.
    if provider == AIProvider.ollama and not url.endswith("/v1"):
        url += "/v1"
    return url


@dataclass(frozen=True)
class Target:
    """Where one request goes, with what."""

    provider: AIProvider
    model: str | None
    api_key: str | None
    base_url: str | None
    allow_private: bool


def _check(target: Target) -> None:
    """Refuse a request its connection cannot make."""
    if needs_key(target.provider) and not target.api_key:
        raise AIRequestError(AIMessages.NOT_CONFIGURED)


@dataclass(frozen=True)
class Job:
    """What one kind of request asks of the model."""

    purpose: str
    #: Room for the answer, and for the thinking of a model that thinks first.
    max_tokens: int
    timeout: float


def _anthropic_client(target: Target, timeout: float) -> anthropic.AsyncAnthropic:
    # The key and the address are always given: without them the SDK would
    # look for its own in the server's environment.
    return anthropic.AsyncAnthropic(
        api_key=target.api_key,
        base_url=PRESETS[AIProvider.anthropic].base_url,
        timeout=timeout,
    )


def _openai_client(target: Target, timeout: float) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        # A server with no key still needs a value here; it is not checked.
        api_key=target.api_key or "none",
        base_url=_endpoint(target.provider, target.base_url),
        timeout=timeout,
        http_client=httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=PinnedTransport(allow_private=target.allow_private),
        ),
    )


def _failure_code(exc: BaseException, provider: AIProvider, *, sent_key: bool) -> str:
    """The message code for a request to ``provider`` that raised. What the
    provider named is logged, not returned."""
    cause = exc.__cause__ or exc.__context__
    if isinstance(exc, (WebhookTargetUrlError, WebhookTargetUrlPrivateError)) or (
        isinstance(cause, (WebhookTargetUrlError, WebhookTargetUrlPrivateError))
    ):
        return AIMessages.INVALID_BASE_URL
    status = getattr(exc, "status_code", None)
    logger.warning(
        "AI provider %s failed: %s %s",
        provider.value,
        status if status is not None else type(exc).__name__,
        _error_kind(exc),
    )
    if isinstance(exc, (anthropic.AuthenticationError, openai.AuthenticationError)):
        return AIMessages.INVALID_API_KEY if sent_key else AIMessages.PROVIDER_ERROR
    if isinstance(exc, (anthropic.NotFoundError, openai.NotFoundError)):
        return AIMessages.MODEL_NOT_FOUND
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return AIMessages.PROVIDER_UNAVAILABLE
    return AIMessages.PROVIDER_ERROR


def _error_kind(exc: BaseException) -> str:
    """The kind of error a provider named (its ``type`` or ``code``), if any."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(error, dict):
        for key in ("type", "code", "status"):
            kind = error.get(key)
            if isinstance(kind, (str, int)) and str(kind):
                return str(kind)[:64]
    return ""


def _log_usage(
    target: Target, job: Job, guild_id: int | None, used: tuple[int, int, int]
) -> None:
    logger.info(
        "AI usage community=%s provider=%s model=%s purpose=%s "
        "input=%d output=%d cached=%d",
        guild_id,
        target.provider.value,
        target.model,
        job.purpose,
        *used,
    )


async def _anthropic_text(
    target: Target, job: Job, prompt: tuple[str, str], schema: dict | None
) -> tuple[str, tuple[int, int, int]]:
    system, user = prompt
    params: dict[str, Any] = {
        "model": target.model,
        "max_tokens": job.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if schema is not None:
        params["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    async with _anthropic_client(target, job.timeout) as client:
        reply = await client.messages.create(**params)
    # A model that thinks first answers with thinking blocks before the text.
    text = "".join(b.text for b in reply.content if b.type == "text")
    usage = reply.usage
    return text, (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_input_tokens or 0,
    )


async def _responses_text(
    target: Target, job: Job, prompt: tuple[str, str], schema: dict | None
) -> tuple[str, tuple[int, int, int]]:
    system, user = prompt
    params: dict[str, Any] = {
        "model": target.model,
        "instructions": system,
        "input": user,
        "max_output_tokens": job.max_tokens,
        "store": False,
    }
    if schema is not None:
        params["text"] = {
            "format": {
                "type": "json_schema",
                "name": "answer",
                "schema": schema,
                "strict": True,
            }
        }
    async with _openai_client(target, job.timeout) as client:
        reply = await client.responses.create(**params)
    usage = reply.usage
    return reply.output_text, (
        usage.input_tokens if usage else 0,
        usage.output_tokens if usage else 0,
        usage.input_tokens_details.cached_tokens if usage else 0,
    )


async def _chat_text(
    target: Target, job: Job, prompt: tuple[str, str], schema: dict | None
) -> tuple[str, tuple[int, int, int]]:
    # The servers that speak this shape differ in the structured output they
    # take, so a schema is asked for in the prompt, and checked on the way out.
    system, user = prompt
    async with _openai_client(target, job.timeout) as client:
        reply = await client.chat.completions.create(
            model=target.model or "",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=job.max_tokens,
        )
    usage = reply.usage
    cached = (
        usage.prompt_tokens_details.cached_tokens
        if usage and usage.prompt_tokens_details
        else None
    )
    return reply.choices[0].message.content or "", (
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
        cached or 0,
    )


_SENDERS: dict[Shape, Callable[..., Any]] = {
    Shape.anthropic: _anthropic_text,
    Shape.responses: _responses_text,
    Shape.chat: _chat_text,
}


async def _send(
    target: Target,
    job: Job,
    prompt: tuple[str, str],
    guild_id: int | None,
    schema: dict | None = None,
) -> str:
    _check(target)
    if not target.model:
        raise AIRequestError(AIMessages.MODEL_REQUIRED)
    send = _SENDERS[PRESETS[target.provider].shape]
    try:
        try:
            text, used = await send(target, job, prompt, schema)
        except (anthropic.BadRequestError, openai.BadRequestError):
            if schema is None:
                raise
            # A model that takes no schema still answers one the prompt asks
            # for, and the answer is checked either way.
            text, used = await send(target, job, prompt, None)
    except AIRequestError:
        raise
    except Exception as exc:
        raise AIRequestError(
            _failure_code(exc, target.provider, sent_key=bool(target.api_key))
        ) from exc
    _log_usage(target, job, guild_id, used)
    return text


async def complete_text(
    target: Target, job: Job, prompt: tuple[str, str], *, guild_id: int | None
) -> str:
    """The model's answer to ``prompt``, as text."""
    return (await _send(target, job, prompt, guild_id)).strip()


Answer = TypeVar("Answer", bound=BaseModel)


async def complete_json(
    target: Target,
    job: Job,
    prompt: tuple[str, str],
    answer: type[Answer],
    *,
    guild_id: int | None,
) -> Answer:
    """The model's answer to ``prompt`` as an ``answer``. The prompt asks for
    the JSON shape; a provider that takes a schema is given it too. An answer
    that does not fit is asked for once more."""
    schema = answer.model_json_schema()
    for attempt in (1, 2):
        text = await _send(target, job, prompt, guild_id, schema)
        try:
            return answer.model_validate_json(_json_object(text))
        except ValidationError:
            if attempt == 2:
                raise AIRequestError(AIMessages.PROVIDER_ERROR) from None
    raise AssertionError("unreachable")


def _json_object(text: str) -> str:
    """The outermost JSON object in ``text``, past any words around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


async def list_models(target: Target) -> list[str]:
    """The models the provider offers this connection, sorted by name."""
    _check(target)
    timeout = 10.0
    try:
        if PRESETS[target.provider].shape is Shape.anthropic:
            async with _anthropic_client(target, timeout) as client:
                ids = [m.id async for m in client.models.list(limit=MODEL_LIST_CAP)]
        else:
            async with _openai_client(target, timeout) as client:
                ids = [m.id async for m in client.models.list()]
    except AIRequestError:
        raise
    except Exception as exc:
        raise AIRequestError(
            _failure_code(exc, target.provider, sent_key=bool(target.api_key))
        ) from exc
    return sorted(ids)[:MODEL_LIST_CAP]
