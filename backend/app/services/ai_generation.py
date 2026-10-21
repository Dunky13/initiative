"""AI work on a task or a file: checklist steps, a description, a summary.

Each asks the connection the community resolves to (``ai_settings``), through
the one request path in ``ai_provider``.
"""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AIMessages
from app.models.tenant.task import Task
from app.models.platform.user import User
from app.services import ai_provider
from app.services.ai_provider import AIRequestError, Job
from app.services.ai_settings import record_health, resolve_ai_settings
from app.services.export.lexical import editor_markdown

# Maximum output lengths to prevent excessive LLM responses
_MAX_CHECKLIST_ITEM_LENGTH = 200
_MAX_DESCRIPTION_LENGTH = 2000
_MAX_SUMMARY_LENGTH = 5000

_CHECKLIST_JOB = Job(purpose="checklist", max_tokens=8000, timeout=120.0)
_DESCRIPTION_JOB = Job(purpose="description", max_tokens=8000, timeout=120.0)
_SUMMARY_JOB = Job(purpose="summary", max_tokens=16000, timeout=180.0)


Answer = TypeVar("Answer")


class _Checklist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str]


async def generate_checklist(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    task: Task,
    *,
    initiative_name: str | None = None,
    project_name: str | None = None,
) -> list[str]:
    """Suggest checklist steps using the configured AI provider."""
    prompt = _build_checklist_prompt(
        task, initiative_name, project_name, locale=user.locale or "en"
    )
    checklist = await _ask(
        session,
        guild_id,
        lambda target: ai_provider.complete_json(
            target, _CHECKLIST_JOB, prompt, _Checklist, guild_id=guild_id
        ),
    )
    return [
        _truncate_output(step.strip(), _MAX_CHECKLIST_ITEM_LENGTH)
        for step in checklist.items
        if step.strip()
    ]


async def generate_description(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    task: Task,
    *,
    initiative_name: str | None = None,
    project_name: str | None = None,
) -> str:
    """Generate/enhance task description using configured AI provider."""
    prompt = _build_description_prompt(
        task, initiative_name, project_name, locale=user.locale or "en"
    )
    content = await _ask(
        session,
        guild_id,
        lambda target: ai_provider.complete_text(
            target, _DESCRIPTION_JOB, prompt, guild_id=guild_id
        ),
    )
    return _truncate_output(content, _MAX_DESCRIPTION_LENGTH)


async def generate_file_summary(
    session: AsyncSession,
    user: User,
    guild_id: int | None,
    file_content: dict | None,
    file_name: str,
) -> str:
    """Generate a summary of a file using configured AI provider."""
    # The editor state as markdown, which a model reads better than JSON
    markdown_content = editor_markdown(file_content, reading=True)
    if not markdown_content.strip():
        raise AIRequestError(AIMessages.DOCUMENT_EMPTY)

    prompt = _build_summary_prompt(
        file_name, markdown_content, locale=user.locale or "en"
    )
    content = await _ask(
        session,
        guild_id,
        lambda target: ai_provider.complete_text(
            target, _SUMMARY_JOB, prompt, guild_id=guild_id
        ),
    )
    return _truncate_output(content, _MAX_SUMMARY_LENGTH)


def _locale_instruction(locale: str) -> str:
    """Return a prompt instruction for the target language, empty for English."""
    if locale == "en":
        return ""
    _LOCALE_NAMES = {
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
    }
    lang = _LOCALE_NAMES.get(locale, locale)
    return f"Write your response in {lang}.\n"


def _truncate_output(text: str, max_length: int) -> str:
    """Truncate LLM output to a maximum length."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    # Try to break at last word boundary
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


# ---------------------------------------------------------------------------
# Prompt builders — return (system_prompt, user_content) tuples.
#
# System prompts contain only instructions. User content wraps all
# user-provided data in XML tags so the LLM can distinguish it from
# instructions.
# ---------------------------------------------------------------------------


def _build_summary_prompt(
    title: str, content: str, *, locale: str = "en"
) -> tuple[str, str]:
    """Build system/user prompt pair for file summarization."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Summarize the provided file in 2-4 paragraphs, focusing on the key points.\n"
        "Write a clear, concise summary that captures the main ideas and important details.\n"
        f"{lang_instruction}"
        "Return ONLY the summary text, no other commentary."
    )
    user_content = (
        f"<file>\n"
        f"  <title>{html.escape(title)}</title>\n"
        f"  <content>\n{html.escape(content)}\n  </content>\n"
        f"</file>"
    )
    return system_prompt, user_content


def _build_checklist_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Build system/user prompt pair for checklist generation."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Break the task provided by the user into checklist steps.\n"
        "Return 3-7 specific, actionable steps.\n"
        "Each step should be a clear action that contributes to completing the task.\n"
        "Keep each step concise (under 100 characters).\n"
        "Do not include numbering or bullet points in the step text.\n"
        f"{lang_instruction}"
        'Return ONLY a JSON object of the form {"items": ["first step", ...]}, '
        "no other text."
    )

    context_parts = []
    if initiative_name:
        context_parts.append(
            f"  <initiative>{html.escape(initiative_name)}</initiative>"
        )
    if project_name:
        context_parts.append(f"  <project>{html.escape(project_name)}</project>")
    context_xml = (
        "\n<context>\n" + "\n".join(context_parts) + "\n</context>"
        if context_parts
        else ""
    )

    description_xml = (
        f"\n  <description>{html.escape(task.description)}</description>"
        if task.description
        else ""
    )
    user_content = (
        f"<task>\n"
        f"  <title>{html.escape(task.title)}</title>{description_xml}\n"
        f"</task>{context_xml}"
    )
    return system_prompt, user_content


def _build_description_prompt(
    task: Task,
    initiative_name: str | None = None,
    project_name: str | None = None,
    *,
    locale: str = "en",
) -> tuple[str, str]:
    """Build system/user prompt pair for description generation."""
    lang_instruction = _locale_instruction(locale)
    system_prompt = (
        "Write a clear task description for the task provided by the user.\n"
        "Write 2-4 sentences explaining what needs to be done, the expected outcome, "
        "and any key considerations.\n"
        "Be specific and actionable. Use markdown formatting if helpful.\n"
        f"{lang_instruction}"
        "Return ONLY the description text, no other commentary."
    )

    context_parts = []
    if initiative_name:
        context_parts.append(
            f"  <initiative>{html.escape(initiative_name)}</initiative>"
        )
    if project_name:
        context_parts.append(f"  <project>{html.escape(project_name)}</project>")
    context_xml = (
        "\n<context>\n" + "\n".join(context_parts) + "\n</context>"
        if context_parts
        else ""
    )

    existing_xml = (
        f"\n  <existing_description>{html.escape(task.description)}</existing_description>"
        if task.description
        else ""
    )
    user_content = (
        f"<task>\n"
        f"  <title>{html.escape(task.title)}</title>{existing_xml}\n"
        f"</task>{context_xml}"
    )
    return system_prompt, user_content


async def _ask(
    session: AsyncSession,
    guild_id: int | None,
    ask: Callable[[ai_provider.Target], Awaitable[Answer]],
) -> Answer:
    """``ask`` the connection a request in ``guild_id`` goes through, with its
    key, and write down on the connection how the provider answered."""
    resolved = await resolve_ai_settings(session, guild_id, with_key=True)
    if not resolved.enabled or resolved.provider is None:
        raise AIRequestError(
            AIMessages.NOT_CONFIGURED if resolved.provider else AIMessages.NOT_ENABLED
        )
    assert resolved.scope is not None and resolved.connection_id is not None
    target = ai_provider.Target(
        provider=resolved.provider,
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        allow_private=resolved.allow_private,
    )
    try:
        answer = await ask(target)
    except AIRequestError as exc:
        if exc.code in ai_provider.PROVIDER_CODES:
            await record_health(
                resolved.scope, resolved.connection_id, guild_id, exc.code
            )
        raise
    await record_health(resolved.scope, resolved.connection_id, guild_id, None)
    return answer
