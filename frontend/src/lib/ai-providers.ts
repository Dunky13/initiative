import type { AIProvider } from "@/api/generated/initiativeAPI.schemas";

export const DEFAULT_OLLAMA_URL = "http://localhost:11434";

/**
 * How each provider is set up. Mirrors the backend's presets
 * (`app/services/ai_provider.py`): a hosted service has its own address, and a
 * server somebody runs is reached at the address the connection gives. Models
 * always come from the provider's own list.
 */
export interface ProviderConfig {
  label: string;
  /** Whether the connection takes an API key. */
  hasApiKey: boolean;
  /** Whether the connection gives the address. */
  requiresBaseUrl: boolean;
  defaultBaseUrl?: string;
}

const hosted = (label: string): ProviderConfig => ({
  label,
  hasApiKey: true,
  requiresBaseUrl: false,
});

export const PROVIDER_CONFIGS: Record<AIProvider, ProviderConfig> = {
  openai: hosted("OpenAI"),
  anthropic: hosted("Anthropic"),
  gemini: hosted("Google Gemini"),
  deepseek: hosted("DeepSeek"),
  groq: hosted("Groq"),
  xai: hosted("xAI"),
  together: hosted("Together AI"),
  openrouter: hosted("OpenRouter"),
  ollama: {
    label: "Ollama",
    hasApiKey: false,
    requiresBaseUrl: true,
    defaultBaseUrl: DEFAULT_OLLAMA_URL,
  },
  custom: {
    label: "OpenAI-compatible server",
    hasApiKey: true,
    requiresBaseUrl: true,
  },
};

// Connections are defined either by the platform operator or by a community.
// Members never define one, so there is no "user" scope here.
export type AISettingsScope = "platform" | "community";

const ALL_PROVIDERS = Object.keys(PROVIDER_CONFIGS) as AIProvider[];

const PROVIDERS_BY_SCOPE: Record<AISettingsScope, AIProvider[]> = {
  platform: ALL_PROVIDERS,
  // Ollama runs beside the server, at an address only the operator may give.
  community: ALL_PROVIDERS.filter((provider) => provider !== "ollama"),
};

export const getProvidersForScope = (scope: AISettingsScope): AIProvider[] =>
  PROVIDERS_BY_SCOPE[scope];
