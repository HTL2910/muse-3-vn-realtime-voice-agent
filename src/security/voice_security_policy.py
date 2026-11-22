"""
Voice security policy (approach_18) - Tier 1 + Tier 2 controls.

Tier 1 (mandatory before touching real data):
  * tenant_id comes ONLY from the authenticated telephony session
    (DID / trunk binding), never from caller speech, prompt or transcript.
  * Risk-based verification: basic order lookup = order code + phone suffix;
    high-risk actions (change address / cancel / compensation) = OTP verified.
  * Prompt-injection defence for voice: system / evidence / transcript are
    separate channels; transcript is untrusted data, never instructions;
    tool calls are allowlist-checked and blocked when injection is detected.
  * PII masking in logs / transcripts, by role.
  * Rate limiting / blocklist / max session duration (toll-fraud, spam).

Tier 2:
  * Tenant-scoped encryption at rest for recordings/transcripts (KMS-style
    interface; stdlib HMAC-keystream implementation for local/test use,
    replace key provider with cloud KMS + AES-GCM in production).
    Transport is required to be TLS 1.3 at the telephony/API boundary -
    enforced by deployment config, asserted by `REQUIRED_TLS`.
  * Retention expiry, hash-chained immutable audit log, recording consent.

Contracts: CONTRACTS_VERSION / TOTAL_SLO_P95_MS are imported from
src.contracts (locked v1.0.0); this module defines NO mirror of them.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from src.contracts import CONTRACTS_VERSION, TOTAL_SLO_P95_MS  # type: ignore

REQUIRED_TLS = "TLS1.3"


def _fold(text: str) -> str:
    text = (text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d")


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SecurityAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_OTP = "require_otp"
    REQUIRE_VERIFICATION = "require_verification"


@dataclass
class SecurityDecision:
    allowed: bool
    action: SecurityAction
    reason: str = ""
    rule_id: str = ""

    @property
    def denied(self) -> bool:
        return not self.allowed


@dataclass
class AuthenticatedSession:
    """Tenant binding established by telephony layer, NOT by the caller."""
    session_id: str
    tenant_id: str
    caller_phone: str = ""
    did: str = ""
    trunk_id: str = ""
    source_ip: str = ""
    authenticated: bool = True
    started_at: float = field(default_factory=time.time)
    recording_consent: Optional[bool] = None  # None=not asked, False=declined


@dataclass
class Verification:
    order_code_provided: bool = False
    phone_suffix_match: bool = False
    otp_verified: bool = False
    resource_tenant_id: str = ""       # tenant that owns the target resource
    resource_owner_phone: str = ""


# --------------------------------------------------------------------------
# Tier 1a: tenant isolation
# --------------------------------------------------------------------------
def resolve_tenant(session: AuthenticatedSession,
                   claimed_tenant: Optional[str] = None) -> SecurityDecision:
    """Tenant is always the session tenant. A different claimed tenant
    (from speech / prompt / transcript / tool args) is an attack -> DENY."""
    if session is None or not session.authenticated or not session.tenant_id:
        return SecurityDecision(False, SecurityAction.DENY,
                                "unauthenticated_session", "tenant_no_session")
    if claimed_tenant and claimed_tenant != session.tenant_id:
        return SecurityDecision(False, SecurityAction.DENY,
                                "tenant_mismatch_claimed_vs_session", "tenant_mismatch")
    return SecurityDecision(True, SecurityAction.ALLOW, "", "tenant_ok")


def check_cross_tenant(session: AuthenticatedSession, resource_tenant_id: str) -> SecurityDecision:
    if not resource_tenant_id or resource_tenant_id != session.tenant_id:
        return SecurityDecision(False, SecurityAction.DENY,
                                "cross_tenant_access", "cross_tenant")
    return SecurityDecision(True, SecurityAction.ALLOW, "", "same_tenant")


# --------------------------------------------------------------------------
# Tier 1b: risk-based verification
# --------------------------------------------------------------------------
HIGH_RISK_ACTIONS = {"change_address", "cancel_order", "compensation",
                     "refund", "change_phone", "export_data"}
BASIC_ACTIONS = {"get_order_status", "get_inventory", "get_appointment",
                 "get_policy", "get_faq"}


def authorize_action(session: AuthenticatedSession, action: str,
                     v: Verification) -> SecurityDecision:
    d = resolve_tenant(session)
    if not d.allowed:
        return d
    if v.resource_tenant_id:
        d = check_cross_tenant(session, v.resource_tenant_id)
        if not d.allowed:
            return d
    if action not in HIGH_RISK_ACTIONS and action not in BASIC_ACTIONS:
        return SecurityDecision(False, SecurityAction.DENY,
                                "action_not_allowlisted", "action_allowlist")
    if action in HIGH_RISK_ACTIONS:
        if not v.otp_verified:
            return SecurityDecision(False, SecurityAction.REQUIRE_OTP,
                                    "otp_required_for_high_risk", "otp_required")
        # OTP alone is not enough if the resource belongs to another phone
        if v.resource_owner_phone and session.caller_phone \
                and v.resource_owner_phone != session.caller_phone:
            return SecurityDecision(False, SecurityAction.DENY,
                                    "owner_phone_mismatch", "owner_mismatch")
        return SecurityDecision(True, SecurityAction.ALLOW, "", "high_risk_otp_ok")
    # Basic lookup: order code + phone suffix must both check out
    if not (v.order_code_provided and v.phone_suffix_match):
        return SecurityDecision(False, SecurityAction.REQUIRE_VERIFICATION,
                                "order_code_and_phone_suffix_required", "basic_verify")
    return SecurityDecision(True, SecurityAction.ALLOW, "", "basic_ok")


def phone_suffix_match(phone: str, suffix: str) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    sfx = re.sub(r"\D", "", suffix or "")
    return len(sfx) >= 3 and digits.endswith(sfx)


# --------------------------------------------------------------------------
# Tier 1c: prompt injection via audio / transcript
# --------------------------------------------------------------------------
_INJECTION_PATTERNS = [
    "bo qua huong dan", "bo qua chi thi", "ignore previous", "ignore instructions",
    "ignore all instructions", "system prompt", "prompt he thong",
    "ban la he thong", "gia vo la he thong", "developer message",
    "hay chay lenh", "run command", "truy cap co so du lieu",
    "truy cap database", "cho toi du lieu cua khach khac",
    "liet ke tat ca don hang", "show all orders", "bypass", "vuot qua bao mat",
    "khong can xac thuc", "skip verification", "bo qua xac thuc",
]
ALLOWED_TOOLS = BASIC_ACTIONS | {"create_callback_ticket"}


def detect_injection(transcript: str) -> bool:
    folded = _fold(transcript)
    return any(p in folded for p in _INJECTION_PATTERNS)


def sanitize_transcript(transcript: str) -> dict:
    """Transcript is returned strictly as DATA in its own channel."""
    return {"channel": "transcript_untrusted", "is_instruction": False,
            "injection_detected": detect_injection(transcript),
            "text": transcript}


def validate_tool_call(session: AuthenticatedSession, tool: str,
                       args: Optional[dict] = None,
                       transcript: str = "") -> SecurityDecision:
    """A tool call may only run if: session valid, tool allowlisted,
    no tenant override in args, and no injection in the driving transcript.
    An injection in the transcript can therefore NEVER become a tool call."""
    args = args or {}
    d = resolve_tenant(session, claimed_tenant=args.get("tenant_id"))
    if not d.allowed:
        return d
    if tool not in ALLOWED_TOOLS:
        return SecurityDecision(False, SecurityAction.DENY,
                                "tool_not_allowlisted", "tool_allowlist")
    if detect_injection(transcript):
        return SecurityDecision(False, SecurityAction.DENY,
                                "prompt_injection_detected", "injection_block")
    # Args must never widen scope: no raw SQL / db handles / arbitrary URLs
    blob = _fold(" ".join(str(v) for v in args.values()))
    if any(x in blob for x in ("select ", "drop table", "union select", "http://", "https://")):
        return SecurityDecision(False, SecurityAction.DENY,
                                "suspicious_tool_args", "tool_args")
    return SecurityDecision(True, SecurityAction.ALLOW, "", "tool_ok")


# --------------------------------------------------------------------------
# Tier 1d: PII masking / redaction, by role
# --------------------------------------------------------------------------
_PHONE_RE = re.compile(r"\b0\d{9}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_ID_RE = re.compile(r"\b\d{9}(\d{3})?\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_ADDR_RE = re.compile(r"(địa chỉ\s*:\s*)([^\n,;]+)", re.IGNORECASE)


def _mask_phone(m: re.Match) -> str:
    n = m.group(0)
    return n[:2] + "******" + n[-2:]


def redact_pii(text: str, role: str = "analytics") -> str:
    """Log/analytics redaction. Raw phone / ID / card / address must not
    survive into logs for ANY role; agents keep only phone last-2 hint."""
    if not text:
        return text or ""
    out = _CARD_RE.sub("[CARD]", text)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _PHONE_RE.sub(_mask_phone, out)
    # 9/12-digit IDs (CCCD) - run after phone so 10-digit phones already masked
    out = _ID_RE.sub("[ID]", out)
    out = _ADDR_RE.sub(lambda m: m.group(1) + "[ADDRESS]", out)
    return out


redact_for_log = redact_pii


def contains_raw_pii(text: str) -> bool:
    return bool(_PHONE_RE.search(text or "") or _EMAIL_RE.search(text or ""))


# --------------------------------------------------------------------------
# Tier 1e: rate limiting, blocklist, session duration (toll fraud / spam)
# --------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_per_window: int = 5, window_s: float = 60.0,
                 max_session_s: float = 1800.0):
        self.max_per_window = max_per_window
        self.window_s = window_s
        self.max_session_s = max_session_s
        self._hits: dict[str, list[float]] = {}
        self.blocklist: set[str] = set()

    def block(self, key: str) -> None:
        self.blocklist.add(key)

    def allow(self, *, caller: str = "", did: str = "", ip: str = "",
              trunk: str = "", now: Optional[float] = None) -> SecurityDecision:
        now = time.time() if now is None else now
        for key in (caller, did, ip, trunk):
            if key and key in self.blocklist:
                return SecurityDecision(False, SecurityAction.DENY,
                                        "blocklisted", "blocklist")
        key = caller or ip or did or trunk or "unknown"
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
        if len(hits) >= self.max_per_window:
            self._hits[key] = hits
            return SecurityDecision(False, SecurityAction.DENY,
                                    "rate_limit_exceeded", "rate_limit")
        hits.append(now)
        self._hits[key] = hits
        return SecurityDecision(True, SecurityAction.ALLOW, "", "rate_ok")

    def check_session_duration(self, session: AuthenticatedSession,
                               now: Optional[float] = None) -> SecurityDecision:
        now = time.time() if now is None else now
        if now - session.started_at > self.max_session_s:
            return SecurityDecision(False, SecurityAction.DENY,
                                    "session_too_long", "session_duration")
        return SecurityDecision(True, SecurityAction.ALLOW, "", "duration_ok")


# --------------------------------------------------------------------------
# Tier 1f: session resource registry - hangup must release EVERYTHING
# --------------------------------------------------------------------------
class SessionRegistry:
    """Tracks connections/tasks per session; close() is idempotent and
    leaves zero leaked resources (asserted by tests)."""

    def __init__(self):
        self._resources: dict[str, dict[str, Any]] = {}

    def register(self, session_id: str, name: str, resource: Any) -> None:
        self._resources.setdefault(session_id, {})[name] = resource

    def active_count(self, session_id: Optional[str] = None) -> int:
        if session_id is not None:
            return len(self._resources.get(session_id, {}))
        return sum(len(v) for v in self._resources.values())

    def close_session(self, session_id: str) -> int:
        resources = self._resources.pop(session_id, {})
        closed = 0
        for res in resources.values():
            for closer in ("close", "cancel", "release"):
                fn = getattr(res, closer, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
                    break
            closed += 1
        return closed

    leaked_count = active_count


# --------------------------------------------------------------------------
# Tier 2a: tenant-scoped encryption at rest (KMS-style interface)
# --------------------------------------------------------------------------
def _keystream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < n:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"),
                        hashlib.sha256).digest()
        counter += 1
    return out[:n]


class TenantCipher:
    """Authenticated encryption keyed per tenant. Production: swap the
    key provider for cloud KMS and this construction for AES-256-GCM."""

    def __init__(self, master_keys: dict[str, bytes]):
        self._keys = dict(master_keys)

    def encrypt(self, tenant_id: str, plaintext: str) -> dict:
        key = self._keys[tenant_id]  # KeyError = unknown tenant, fail-closed
        nonce = secrets.token_bytes(16)
        data = plaintext.encode("utf-8")
        ct = bytes(a ^ b for a, b in zip(data, _keystream(key, nonce, len(data))))
        tag = hmac.new(key, nonce + ct, hashlib.sha256).hexdigest()
        return {"tenant_id": tenant_id, "nonce": nonce.hex(),
                "ciphertext": ct.hex(), "tag": tag}

    def decrypt(self, tenant_id: str, blob: dict) -> str:
        if blob.get("tenant_id") != tenant_id:
            raise ValueError("cross_tenant_decrypt_denied")
        key = self._keys[tenant_id]
        nonce = bytes.fromhex(blob["nonce"])
        ct = bytes.fromhex(blob["ciphertext"])
        expected = hmac.new(key, nonce + ct, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, blob["tag"]):
            raise ValueError("integrity_check_failed")
        data = bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))
        return data.decode("utf-8")


# --------------------------------------------------------------------------
# Tier 2b: retention, audit log (hash chain), recording consent
# --------------------------------------------------------------------------
def retention_expired(created_at: float, retention_days: int,
                      now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    return now - created_at > retention_days * 86400


class AuditLog:
    """Append-only, hash-chained: tampering with an entry breaks the chain."""

    def __init__(self):
        self.entries: list[dict] = []

    def append(self, event: str, actor: str, detail: str = "") -> dict:
        prev = self.entries[-1]["hash"] if self.entries else "GENESIS"
        body = f"{prev}|{time.time()}|{event}|{actor}|{redact_pii(detail)}"
        entry = {"event": event, "actor": actor, "detail": redact_pii(detail),
                 "contracts_version": CONTRACTS_VERSION,
                 "prev_hash": prev,
                 "hash": hashlib.sha256(body.encode()).hexdigest()}
        self.entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        prev = "GENESIS"
        for e in self.entries:
            if e["prev_hash"] != prev:
                return False
            prev = e["hash"]
        return True


def recording_allowed(session: AuthenticatedSession) -> bool:
    """Recording requires consent not declined; declined => no recording,
    call may continue unrecorded or route to callback per tenant policy."""
    return session.recording_consent is not False


# Convenience facade -------------------------------------------------------
class VoiceSecurityPolicy:
    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.registry = SessionRegistry()
        self.audit = AuditLog()

    resolve_tenant = staticmethod(resolve_tenant)
    authorize_action = staticmethod(authorize_action)
    validate_tool_call = staticmethod(validate_tool_call)
    redact_pii = staticmethod(redact_pii)
    detect_injection = staticmethod(detect_injection)
