"""AI settings & connections schemas (mode-based, schema-per-guild).

AI config ownership is a single global mode (``platform`` or ``guild``, never
both — like the auth posture). The mode's owner defines *connections* (the
destination: provider, base_url, model, and its key). Members configure nothing.
"""

from enum import Enum
from typing import Optional

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class AIProvider(str, Enum):
    """Where a connection sends its requests. ``ollama`` and ``custom`` are
    servers somebody runs, at the address the connection gives; the rest are
    hosted services at their own (``app.services.ai_provider.PRESETS``)."""

    openai = "openai"
    anthropic = "anthropic"
    gemini = "gemini"
    deepseek = "deepseek"
    groq = "groq"
    xai = "xai"
    together = "together"
    openrouter = "openrouter"
    ollama = "ollama"
    custom = "custom"


class AIConfigMode(str, Enum):
    """Who owns AI config, app-wide. ``platform`` = the operator's connections
    apply to every guild; ``community`` = each community admin configures its own;
    ``disabled`` = AI off."""

    disabled = "disabled"
    platform = "platform"
    community = "community"


class ConnectionScope(str, Enum):
    """Which table a connection lives in — ``platform`` = the shared
    ``platform_ai_connections`` row, ``community`` = a ``guild_ai_connections`` row."""

    platform = "platform"
    community = "community"


# --- Connections (owner-controlled destination) ------------------------------
class AIConnectionResponse(SanitizedBaseModel):
    """A connection as seen by its owning admin. Never carries the key itself —
    only whether one is set."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    scope: ConnectionScope
    label: str
    provider: AIProvider
    base_url: Optional[str] = None
    model: Optional[str] = None
    has_api_key: bool = False
    enabled: bool = True
    is_default: bool = False


class AIConnectionCreate(SanitizedBaseModel):
    label: str
    provider: AIProvider
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[RawTextStr] = None
    enabled: bool = True
    is_default: bool = False


class AIConnectionUpdate(SanitizedBaseModel):
    label: Optional[str] = None
    provider: Optional[AIProvider] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[RawTextStr] = None
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None


# --- Platform mode (operator-set, on app_settings) ---------------------------
class PlatformAIModeResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    mode: AIConfigMode = AIConfigMode.disabled


class PlatformAIModeUpdate(SanitizedBaseModel):
    mode: AIConfigMode


# --- Resolved (final computed, used internally) ------------------------------
class ResolvedAISettings(SanitizedBaseModel):
    enabled: bool = False
    provider: Optional[AIProvider] = None
    api_key: Optional[RawTextStr] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    # ``allow_private`` is server-computed as (provider == ollama and the chosen
    # connection is a platform connection); never influenced by request input.
    allow_private: bool = False
    scope: Optional[ConnectionScope] = None
    connection_id: Optional[int] = None
    source: str = "disabled"  # "platform" | "community" | "disabled"


class ResolvedAISettingsResponse(SanitizedBaseModel):
    """Resolved settings for the frontend — never exposes the API key."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool = False
    provider: Optional[AIProvider] = None
    has_api_key: bool = False
    base_url: Optional[str] = None
    model: Optional[str] = None
    source: str = "disabled"


# --- Connection probe (test / list models on a STORED connection) ------------
class AIConnectionTestResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    #: The failure's message code; none on success.
    message: Optional[str] = None
    available_models: Optional[list[str]] = None


class AIModelsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    models: list[str]
    error: Optional[str] = None
