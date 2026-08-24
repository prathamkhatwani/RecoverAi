"""
Configuration.

Deliberately stdlib-only (no pydantic-settings) and deliberately tolerant: every knob
has a working default so the app boots and demos correctly with no .env file at all.

The LLM section is provider-agnostic on purpose. Any OpenAI-compatible endpoint works
-- OpenRouter, Zhipu GLM, Moonshot Kimi, Groq, Gemini's compat layer, or a local
Ollama/llama.cpp server. Set three variables and the reasoning tier goes live; set
nothing and a deterministic offline reasoner stands in so the demo cannot break.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
DATA_DIR = BASE_DIR / "data"


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or "").strip() or default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _load_dotenv() -> None:
    """Minimal .env loader.

    Searched in order: backend/.env, then repo-root/.env. Real environment variables
    always win, so an exported key overrides a stale file.
    """
    for candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key.startswith("export "):
                key = key[7:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            # Do not clobber a real exported variable.
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


# ---------------------------------------------------------------------------
# LLM provider presets
# ---------------------------------------------------------------------------
# Convenience only: LLM_PROVIDER picks a base URL + default model so the user has to
# supply just an API key. Any explicit LLM_BASE_URL / LLM_MODEL always overrides.

@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    base_url: str
    default_model: str
    api_key_env: tuple[str, ...]
    signup_url: str
    notes: str
    # Second model tried when the primary is rate-limited or unknown. Free tiers are
    # the flakiest part of this design, so every free preset names a spare.
    fallback_model: str = ""
    # "free" | "trial" | "paid" | "local" -- surfaced in the dashboard so nobody has
    # to guess which of these actually costs money.
    tier: str = "paid"
    # Providers differ on structured output: strict json_schema > json_object > prose.
    # We start at the best level a provider is known to support and degrade on 400.
    json_mode: str = "json_object"       # "json_schema" | "json_object" | "none"


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "openrouter": ProviderPreset(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="z-ai/glm-5.2:free",
        fallback_model="nvidia/nemotron-3-super-120b-a12b:free",
        api_key_env=("OPENROUTER_API_KEY", "LLM_API_KEY"),
        signup_url="https://openrouter.ai/keys",
        tier="free",
        json_mode="json_schema",
        notes=(
            "Recommended. One key, many `:free` models including GLM. 50 requests/day "
            "and 20/min without buying credits -- ample, because the rules tier absorbs "
            "~78% of events before the model is consulted."
        ),
    ),
    "zhipu_intl": ProviderPreset(
        key="zhipu_intl",
        label="Z.ai (GLM, international)",
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-4.7-flash",
        fallback_model="glm-4.5-flash",
        api_key_env=("ZAI_API_KEY", "ZHIPU_API_KEY", "GLM_API_KEY", "LLM_API_KEY"),
        signup_url="https://z.ai/model-api",
        tier="free",
        notes="GLM direct from Z.ai. The `-flash` tiers are genuinely free.",
    ),
    "zhipu": ProviderPreset(
        key="zhipu",
        label="Zhipu GLM (mainland China endpoint)",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.7-flash",
        fallback_model="glm-4.5-flash",
        api_key_env=("ZHIPU_API_KEY", "GLM_API_KEY", "LLM_API_KEY"),
        signup_url="https://open.bigmodel.cn/usercenter/apikeys",
        tier="free",
        notes="Same models, mainland endpoint. Use zhipu_intl outside China.",
    ),
    "groq": ProviderPreset(
        key="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="openai/gpt-oss-120b",
        fallback_model="openai/gpt-oss-20b",
        api_key_env=("GROQ_API_KEY", "LLM_API_KEY"),
        signup_url="https://console.groq.com/keys",
        tier="free",
        json_mode="json_schema",
        notes=(
            "Fastest option -- sub-second classification looks excellent live. Free tier "
            "is throughput-capped (~8K tokens/min), so keep LLM_CONCURRENCY low."
        ),
    ),
    "gemini": ProviderPreset(
        key="gemini",
        label="Google Gemini (OpenAI compat layer)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        # Verified against this endpoint: 3.5-flash answers in ~2-4s and honours strict
        # json_schema. Deliberately not the newest flash -- 3.7 was returning 503
        # "high demand" here, and a headline model that is busy on demo day is worse
        # than a slightly older one that answers.
        default_model="gemini-3.5-flash",
        fallback_model="gemini-3.5-flash-lite",
        api_key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY"),
        signup_url="https://aistudio.google.com/apikey",
        tier="free",
        json_mode="json_schema",
        notes="Generous free tier via AI Studio. Note the `/openai` suffix on the URL.",
    ),
    "moonshot": ProviderPreset(
        key="moonshot",
        label="Moonshot Kimi",
        base_url="https://api.moonshot.ai/v1",
        default_model="kimi-k2.6",
        fallback_model="kimi-k2.6-turbo",
        api_key_env=("MOONSHOT_API_KEY", "KIMI_API_KEY", "LLM_API_KEY"),
        signup_url="https://platform.moonshot.ai/console/api-keys",
        tier="trial",
        notes=(
            "Kimi has no standing free tier -- signup credit only. For a free Kimi, "
            "route through OpenRouter instead."
        ),
    ),
    "mistral": ProviderPreset(
        key="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
        api_key_env=("MISTRAL_API_KEY", "LLM_API_KEY"),
        signup_url="https://console.mistral.ai/api-keys",
        tier="free",
        notes="Free experimental tier, no card required.",
    ),
    "anthropic": ProviderPreset(
        key="anthropic",
        label="Anthropic Claude",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-5",
        fallback_model="claude-haiku-4-5-20251001",
        api_key_env=("ANTHROPIC_API_KEY", "LLM_API_KEY"),
        signup_url="https://console.anthropic.com/settings/keys",
        tier="paid",
        json_mode="none",   # native Messages API uses forced tool-use for structure
        notes="Highest diagnostic quality. Uses the native Messages API, not the compat shim.",
    ),
    "openai": ProviderPreset(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        api_key_env=("OPENAI_API_KEY", "LLM_API_KEY"),
        signup_url="https://platform.openai.com/api-keys",
        tier="paid",
        json_mode="json_schema",
        notes="Paid.",
    ),
    "ollama": ProviderPreset(
        key="ollama",
        label="Ollama (local)",
        base_url="http://localhost:11434/v1",
        default_model="llama3.1",
        api_key_env=("LLM_API_KEY",),
        signup_url="https://ollama.com",
        tier="local",
        notes="Fully local. Set LLM_API_KEY=ollama (any non-empty value) to enable.",
    ),
    "custom": ProviderPreset(
        key="custom",
        label="Custom OpenAI-compatible",
        base_url="",
        default_model="",
        api_key_env=("LLM_API_KEY",),
        signup_url="",
        tier="paid",
        notes="Set LLM_BASE_URL and LLM_MODEL explicitly.",
    ),
}


def _resolve_provider() -> tuple[ProviderPreset, str]:
    """Pick a provider and API key.

    Explicit LLM_PROVIDER wins. Otherwise we auto-detect by scanning presets for a
    populated key env var, so `OPENROUTER_API_KEY=... uvicorn ...` just works.
    """
    requested = _env("LLM_PROVIDER").lower()
    if requested in PROVIDER_PRESETS:
        preset = PROVIDER_PRESETS[requested]
        for var in preset.api_key_env:
            if _env(var):
                return preset, _env(var)
        return preset, _env("LLM_API_KEY")

    detection_order = (
        "openrouter", "groq", "gemini", "zhipu_intl", "zhipu", "moonshot",
        "mistral", "anthropic", "openai",
    )
    for name in detection_order:
        preset = PROVIDER_PRESETS[name]
        for var in preset.api_key_env:
            if var == "LLM_API_KEY":
                continue          # too generic to identify a provider by itself
            if _env(var):
                return preset, _env(var)

    # A bare LLM_API_KEY with an explicit base URL is the "custom endpoint" path.
    if _env("LLM_API_KEY") and _env("LLM_BASE_URL"):
        return PROVIDER_PRESETS["custom"], _env("LLM_API_KEY")

    return PROVIDER_PRESETS["openrouter"], ""


_PRESET, _API_KEY = _resolve_provider()


@dataclass(frozen=True)
class LLMConfig:
    provider: str = _PRESET.key
    provider_label: str = _PRESET.label
    api_key: str = _API_KEY
    base_url: str = _env("LLM_BASE_URL", _PRESET.base_url)
    model: str = _env("LLM_MODEL", _PRESET.default_model)
    fallback_model: str = _env("LLM_FALLBACK_MODEL", _PRESET.fallback_model)
    temperature: float = _env_float("LLM_TEMPERATURE", 0.0)
    max_tokens: int = _env_int("LLM_MAX_TOKENS", 900)
    timeout_seconds: float = _env_float("LLM_TIMEOUT", 22.0)
    max_retries: int = _env_int("LLM_MAX_RETRIES", 1)
    signup_url: str = _PRESET.signup_url
    notes: str = _PRESET.notes
    tier: str = _PRESET.tier
    # "json_schema" | "json_object" | "none". Overridable because a self-hosted or
    # proxied endpoint may support more (or less) than its upstream preset implies.
    json_mode: str = _env("LLM_JSON_MODE", _PRESET.json_mode)

    # OpenRouter-only: refuse to silently route to a provider that drops
    # response_format, which would otherwise turn structured output into prose.
    require_parameters: bool = _env_bool("LLM_REQUIRE_PARAMETERS", True)

    # Hard cap on live calls per simulation run. A 2,000-event stream must never
    # translate into 2,000 API calls -- the rules tier absorbs the bulk and this
    # bounds the remainder so a free tier is not exhausted mid-demo.
    max_calls_per_run: int = _env_int("LLM_MAX_CALLS_PER_RUN", 40)

    # Concurrency for the messy remainder, so live classification stays snappy.
    # Groq's free tier is throughput-limited; 4 is safe on OpenRouter, drop to 2 there.
    concurrency: int = _env_int("LLM_CONCURRENCY", 4)

    @property
    def is_anthropic_native(self) -> bool:
        return "api.anthropic.com" in self.base_url

    @property
    def is_openrouter(self) -> bool:
        return "openrouter.ai" in self.base_url

    @property
    def supports_json_mode(self) -> bool:
        return self.json_mode in ("json_schema", "json_object")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    def public_dict(self) -> dict:
        """Safe to serialise to the dashboard -- never includes the key itself."""
        return {
            "provider": self.provider,
            "provider_label": self.provider_label,
            "model": self.model if self.enabled else None,
            "fallback_model": self.fallback_model or None if self.enabled else None,
            "base_url": self.base_url if self.enabled else None,
            "enabled": self.enabled,
            "mode": "live" if self.enabled else "offline",
            "tier": self.tier,
            "json_mode": self.json_mode,
            "signup_url": self.signup_url,
            "notes": self.notes,
            "max_calls_per_run": self.max_calls_per_run,
            "available_providers": [
                {
                    "key": p.key,
                    "label": p.label,
                    "default_model": p.default_model,
                    "fallback_model": p.fallback_model or None,
                    "tier": p.tier,
                    "signup_url": p.signup_url,
                    "notes": p.notes,
                }
                for p in PROVIDER_PRESETS.values()
                if p.key != "custom"
            ],
        }


@dataclass(frozen=True)
class PolicyConfig:
    """Guardrail parameters. Runtime-tunable from the dashboard so a judge can watch
    the recovered-revenue number move when a cap is loosened."""

    # Attempt caps ---------------------------------------------------------
    max_attempts_per_method_per_week: int = _env_int("GR_MAX_ATTEMPTS_WEEK", 4)
    max_attempts_per_method_per_day: int = _env_int("GR_MAX_ATTEMPTS_DAY", 2)

    # Exposure ceiling -----------------------------------------------------
    # Value the agent may act on autonomously before a human must sign off.
    # Stored in minor units (paise / cents) to avoid float drift.
    autonomous_exposure_ceiling_minor: int = _env_int("GR_EXPOSURE_CEILING", 5_000_00)
    daily_autonomous_budget_minor: int = _env_int("GR_DAILY_BUDGET", 25_00_000)

    # Communication guardrails --------------------------------------------
    quiet_hours_start: int = _env_int("GR_QUIET_START", 21)   # 21:00 local
    quiet_hours_end: int = _env_int("GR_QUIET_END", 8)        # 08:00 local
    max_nudges_per_customer_per_week: int = _env_int("GR_MAX_NUDGES_WEEK", 2)
    min_hours_between_nudges: float = _env_float("GR_MIN_NUDGE_GAP", 36.0)

    # Escalation -----------------------------------------------------------
    escalate_after_failed_attempts: int = _env_int("GR_ESCALATE_AFTER", 3)
    high_value_review_multiplier: float = _env_float("GR_HIGH_VALUE_MULT", 1.0)

    def public_dict(self) -> dict:
        return {
            "max_attempts_per_method_per_week": self.max_attempts_per_method_per_week,
            "max_attempts_per_method_per_day": self.max_attempts_per_method_per_day,
            "autonomous_exposure_ceiling_minor": self.autonomous_exposure_ceiling_minor,
            "daily_autonomous_budget_minor": self.daily_autonomous_budget_minor,
            "quiet_hours_start": self.quiet_hours_start,
            "quiet_hours_end": self.quiet_hours_end,
            "max_nudges_per_customer_per_week": self.max_nudges_per_customer_per_week,
            "min_hours_between_nudges": self.min_hours_between_nudges,
            "escalate_after_failed_attempts": self.escalate_after_failed_attempts,
        }


@dataclass(frozen=True)
class BaselineConfig:
    """The naive strategy we benchmark against -- "retries everything blindly on a
    fixed schedule (what most competing demos will build)"."""

    max_attempts: int = _env_int("BASELINE_MAX_ATTEMPTS", 4)
    interval_hours: float = _env_float("BASELINE_INTERVAL_HOURS", 24.0)
    sends_email_each_attempt: bool = _env_bool("BASELINE_EMAILS", True)

    def public_dict(self) -> dict:
        return {
            "max_attempts": self.max_attempts,
            "interval_hours": self.interval_hours,
            "sends_email_each_attempt": self.sends_email_each_attempt,
            "description": (
                f"Retries every failure up to {self.max_attempts} times on a fixed "
                f"{self.interval_hours:.0f}h schedule, regardless of decline reason, "
                f"and emails the customer on every attempt."
            ),
        }


@dataclass(frozen=True)
class Settings:
    app_name: str = "AI Revenue Recovery"
    track: str = "TRACK 03"
    version: str = "1.0.0"

    db_path: Path = field(default_factory=lambda: Path(_env("DB_PATH", str(DATA_DIR / "recovery.db"))))
    reset_db_on_start: bool = _env_bool("RESET_DB_ON_START", False)

    # Deterministic by default: the same seed produces the same stream and therefore
    # the same headline numbers every time the demo is run.
    random_seed: int = _env_int("RANDOM_SEED", 20260824)

    default_event_count: int = _env_int("DEFAULT_EVENT_COUNT", 600)
    max_event_count: int = _env_int("MAX_EVENT_COUNT", 5000)

    # Stream pacing for the live triage view (milliseconds between events).
    stream_interval_ms: int = _env_int("STREAM_INTERVAL_MS", 220)

    default_currency: str = _env("DEFAULT_CURRENCY", "INR")

    cors_origins: tuple[str, ...] = ("*",)

    llm: LLMConfig = field(default_factory=LLMConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    baseline: BaselineConfig = field(default_factory=BaselineConfig)

    def public_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "track": self.track,
            "version": self.version,
            "default_event_count": self.default_event_count,
            "max_event_count": self.max_event_count,
            "stream_interval_ms": self.stream_interval_ms,
            "default_currency": self.default_currency,
            "random_seed": self.random_seed,
            "llm": self.llm.public_dict(),
            "policy": self.policy.public_dict(),
            "baseline": self.baseline.public_dict(),
        }


settings = Settings()

DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.db_path.parent.mkdir(parents=True, exist_ok=True)
