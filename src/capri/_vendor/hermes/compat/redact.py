"""Upstream-derived display redaction subset. No vault, profile, env discovery or plugins.

Supports prefixed tokens, authorization/API headers, Telegram tokens, private keys,
DB passwords and JWTs. Other upstream redaction integrations are outside Port 01.
"""
import os
import re

_PREFIX_PATTERNS = [
    # Some provider-issued ``sk-`` keys carry dot-delimited body segments (Alibaba
    # ``sk-sp-…``/``sk-ws-…``). Each unit is one body char optionally preceded by
    # a single dot, so the body ends on its last non-dot char (sentence punctuation
    # is never consumed) and can never span ``..``: the ``sk-pro...EFGH`` display
    # mask is left alone by a second redaction pass instead of collapsing to
    # ``***``. Kept free of nested unbounded repeats so the pattern passes the
    # same structural gate plugins must.
    r"sk-[A-Za-z0-9_-](?:\.?[A-Za-z0-9_-]){9,}",
    # Context7 API keys: a fixed vendor prefix (``ctx7sk-``) plus an opaque body.
    # The generic ``sk-`` family cannot catch it: the matcher's lookbehind
    # rejects a prefix preceded by a word char, and here the ``sk-`` sits inside
    # ``ctx7sk-`` - so a bare Context7 key passed through unmasked (#142576).
    r"ctx7sk-[A-Za-z0-9_-]{10,}",
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",            # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",            # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",            # GitHub server-to-server token
    r"ghr_[A-Za-z0-9]{10,}",            # GitHub refresh token
    r"xapp-\d+-[A-Za-z0-9-]{10,}",      # Slack app-Level token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack bot/app/user tokens
    r"AIza[A-Za-z0-9_-]{30,}",          # Google API keys
    r"pplx-[A-Za-z0-9]{10,}",           # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",          # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",             # Firecrawl
    r"bb_live_[A-Za-z0-9_-]{10,}",      # BrowserBase
    r"gAAAA[A-Za-z0-9_=-]{20,}",        # Codex encrypted tokens
    r"AKIA[A-Z0-9]{16}",                # AWS Access Key ID
    r"sk_live_[A-Za-z0-9]{10,}",        # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",        # Stripe secret key (test)
    r"rk_live_[A-Za-z0-9]{10,}",        # Stripe restricted key
    r"SG\.[A-Za-z0-9_-]{10,}",          # SendGrid API key
    r"hf_[A-Za-z0-9]{10,}",             # HuggingFace token
    r"r8_[A-Za-z0-9]{10,}",             # Replicate API token
    r"npm_[A-Za-z0-9]{10,}",            # npm access token
    r"pypi-[A-Za-z0-9_-]{10,}",         # PyPI API token
    r"dop_v1_[A-Za-z0-9]{10,}",         # DigitalOcean PAT
    r"doo_v1_[A-Za-z0-9]{10,}",         # DigitalOcean OAuth
    # AgentMail API key: ``am_`` / ``am_org_`` + an opaque alphanumeric body. The body has no ``_``/``-``,
    # which is what separates it from ``am_example_identifier_123`` (#10983); public docs pin only the
    # prefix, so the charset stays broad and the length floor does the discriminating.
    r"am_(?:org_)?[A-Za-z0-9]{20,}",
    r"sk_[A-Za-z0-9_]{10,}",            # ElevenLabs TTS key (sk_ underscore, not sk- dash)
    r"tvly-[A-Za-z0-9]{10,}",           # Tavily search API key
    r"exa_[A-Za-z0-9]{10,}",            # Exa search API key
    r"gsk_[A-Za-z0-9]{10,}",            # Groq Cloud API key
    r"syt_[A-Za-z0-9]{10,}",            # Matrix access token
    r"retaindb_[A-Za-z0-9]{10,}",       # RetainDB API key
    r"hsk-[A-Za-z0-9]{10,}",            # Hindsight API key
    r"mem0_[A-Za-z0-9]{10,}",           # Mem0 Platform API key
    r"brv_[A-Za-z0-9]{10,}",            # ByteRover API key
    r"xai-[A-Za-z0-9]{30,}",            # xAI (Grok) API key
    r"ntn_[A-Za-z0-9]{10,}",            # Notion internal integration token
    r"fw-[A-Za-z0-9]{30,}",             # Fireworks AI API key
    r"fw_[A-Za-z0-9]{30,}",             # Fireworks AI API key
    r"fpk_[A-Za-z0-9]{30,}",            # Fireworks AI project key
    # GitLab token families (each keeps a full literal prefix for the pre-screen).
    # Ported from openclaw/openclaw#112954; follow-up invited in #4541.
    r"glpat-[A-Za-z0-9_\-]{10,}",       # GitLab personal access token
    r"gloas-[A-Za-z0-9_\-]{10,}",       # GitLab OAuth application secret
    r"gldt-[A-Za-z0-9_\-]{10,}",        # GitLab deploy token
    r"glrt-[A-Za-z0-9_.\-]{10,}",       # GitLab runner authentication token (routable tokens are dotted)
    r"glrtr-[A-Za-z0-9_.\-]{10,}",      # GitLab runner registration token (routable)
    r"glcbt-[A-Za-z0-9_\-]{10,}",       # GitLab CI/CD job token
    r"glptt-[A-Za-z0-9_\-]{10,}",       # GitLab pipeline trigger token
    r"glft-[A-Za-z0-9_\-]{10,}",        # GitLab feed token
    r"glimt-[A-Za-z0-9_\-]{10,}",       # GitLab incoming mail token
    r"glagent-[A-Za-z0-9_\-]{10,}",     # GitLab agent (KAS) token
    r"glsoat-[A-Za-z0-9_\-]{10,}",      # GitLab service-account access token
    r"glffct-[A-Za-z0-9_\-]{10,}",      # GitLab feature-flags client token
    r"glwt-[A-Za-z0-9_\-]{10,}",        # GitLab workspace token
    r"GR1348941[A-Za-z0-9_\-]{10,}",    # GitLab legacy runner registration token
    r"pk-lf-[A-Za-z0-9\-]{8,}",         # Langfuse public key (sk-lf- already covered by sk- pattern)
]

_AUTH_HEADER_RE = re.compile(r"((?:Proxy-)?Authorization:\s*)([A-Za-z][\w.+-]*\s+)?([^\s\"']+)", re.IGNORECASE)

SECRET_HEADER_NAME_LIST = ("x-api-key", "x-goog-api-key", "api-key", "apikey", "x-api-token", "x-auth-token", "x-access-token")

_SECRET_HEADER_NAMES = rf"(?:{'|'.join(SECRET_HEADER_NAME_LIST)})"

_SECRET_HEADER_RE = re.compile(rf"({_SECRET_HEADER_NAMES}\s*:\s*)(\S+)", re.IGNORECASE)

_TELEGRAM_RE = re.compile(r"(?<!\d)(bot)?(\d{8,}):([-A-Za-z0-9_]{30,})")

_PRIVATE_KEY_RE = re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----")

_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s]+:)([^@\s]+)(@)",
    re.IGNORECASE,
)

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")

def _compile_prefix_matcher(patterns: list) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(patterns) + r")(?![A-Za-z0-9_-])")

_PREFIX_RE = _compile_prefix_matcher(_PREFIX_PATTERNS)

_DISPLAY_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x80-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2064]")

def mask_secret(value: str, *, head: int = 4, tail: int = 4, floor: int = 12,
                placeholder: str = "***", empty: str = "") -> str:
    """Mask a secret for display (``hermes config`` / ``status`` / ``dump``):
    ``sk-p...7890``; shorter than ``floor`` (after control-byte stripping) →
    ``placeholder``; falsy → ``empty``."""
    value = _DISPLAY_CONTROL_RE.sub("", value) if value else value
    if not value:
        return empty
    return placeholder if len(value) < floor else f"{value[:head]}...{value[-tail:]}"

def _mask_token(token: str) -> str:
    """Mask a log token — 18-char floor, preserves 6 prefix / 4 suffix; empty → ``***``."""
    if not token:
        return "***"
    return mask_secret(token, head=6, tail=4, floor=18)

_REDACT_ENABLED = os.getenv("HERMES_REDACT_SECRETS", "true").lower() in {"1", "true", "yes", "on"}

def redact_sensitive_text(text, *, force=False):
    if text is None:
        return None
    text = text if isinstance(text, str) else str(text)
    if not text or not (force or _REDACT_ENABLED):
        return text
    text = _PREFIX_RE.sub(lambda m: _mask_token(m.group(1)), text)
    text = _AUTH_HEADER_RE.sub(lambda m: m.group(1) + (m.group(2) or "") + _mask_token(m.group(3)), text)
    text = _SECRET_HEADER_RE.sub(lambda m: m.group(1) + _mask_token(m.group(2)), text)
    text = _TELEGRAM_RE.sub(lambda m: f"{m.group(1) or ''}{m.group(2)}:***", text)
    text = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    text = _DB_CONNSTR_RE.sub(lambda m: m.group(1) + "***" + m.group(3), text)
    return _JWT_RE.sub(lambda m: _mask_token(m.group(0)), text)
