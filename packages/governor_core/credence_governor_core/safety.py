"""safety.py — risk-aware features for the harm posterior P(unsafe|X).

Port of credence-openclaw openclaw-plugin/src/safety.ts. The pure classifiers are
faithful; the live `SafetyTracker` (which held per-session taint in the in-process
plugin) is replaced by `extract_safety(event, session)`, which **replays** the
Session's tool_result messages to reconstruct the causal taint state, then computes
the 4 features for the proposed call. This is the server-side / transcript-replay
form: the taint SOURCE is the content the agent consumed (tool results), all of
which precede the proposed call (not yet in `messages`).
"""

from __future__ import annotations

import json
import re
from typing import Any

from .schema import AgentToolEvent, FeatureDict, Session


def _flatten(args: Any) -> str:
    try:
        return json.dumps(args if args is not None else "").lower()
    except (TypeError, ValueError):
        return ""


# Ordered most-dangerous-first; first match wins. (class, name-pattern, args-pattern or None)
_ACTION_RULES: list[tuple[str, re.Pattern[str], re.Pattern[str] | None]] = [
    ("delete", re.compile(r"\b(rm|unlink|rmdir|delete|remove|trash|drop)\b", re.I), None),
    ("delete", re.compile(r"\b(exec|process|bash|sh|tmux|run)\b", re.I),
     re.compile(r"\b(rm\s|unlink|rmdir|drop\s+table|delete\s+from)\b", re.I)),
    ("external-send", re.compile(r"send|forward|publish|tweet|post\b|webhook|gmail|email|sendmessage|pinmessage|sms|slack", re.I), None),
    ("external-send", re.compile(r"\b(exec|process|bash|sh|tmux|curl|wget)\b", re.I),
     re.compile(r"(curl|wget).*(-d|--data|-t\b|-f\b|@/|http)", re.I)),
    ("credential-access", re.compile(r"op_signin|1password|keychain|secret|credential|vault", re.I), None),
    ("credential-access", re.compile(r"read|search|cat|grep|get", re.I),
     re.compile(r"api[_-]?key|secret|credential|token|password|\.env|private[_-]?key", re.I)),
    ("cross-boundary", re.compile(r"web_fetch|web_search|browser|agent-browser|activate_window|screenshot|type_text|open\b", re.I), None),
    ("cross-boundary", re.compile(r"move|copy|mv|cp", re.I), re.compile(r"public/|/sync/|external|http", re.I)),
    ("exec", re.compile(r"\b(exec|process|bash|sh|tmux|run|gh\s+api|api\s+gateway|cron)\b", re.I), None),
    ("local-write", re.compile(r"\b(write|edit|create|apply_patch|update|move|mv|cp|copy|append|insert)\b", re.I), None),
    ("read-only", re.compile(r"\b(read|cat|head|tail|ls|grep|find|search|get|list|print|fetch|capture|transcript|view|show|envelope)\b", re.I), None),
]


def action_class(tool_name: str, args: Any) -> str:
    """Coarse risk class of an action (the candidate-harm taxonomy)."""
    name = (tool_name or "").lower()
    a = _flatten(args)
    for cls, name_pat, arg_pat in _ACTION_RULES:
        if name_pat.search(name) and (arg_pat is None or arg_pat.search(a) or arg_pat.search(name)):
            return cls
        # command-style tools carry the verb in the args, not the name.
        # NOTE: this name-pattern-over-args scan can incidentally over-match benign
        # calls whose args contain a trigger substring (e.g. a path ".../post.ts" ->
        # external-send). Preserved verbatim from credence-openclaw's safety.ts because
        # the shipped harm warm-counts (data/brain/harm_brain.counts.json) were TRAINED
        # against exactly this action_class; diverging would silently misalign the
        # trained harm posterior. Revisit only with a retrained harm brain.
        if arg_pat is None and name_pat.search(a):
            return cls
    return "other"


_EMAIL = r"[\w.+-]+@[\w.-]+\.\w+"
_URL = r"https?://[\w.-]+"
_PUBLIC_PATH = re.compile(r"(^|[\"'/])(public|sync|shared|outbox|external)/", re.I)


def target_externality(tool_name: str, args: Any) -> str:
    """Does the action reach OUTSIDE the trusted boundary? external | internal | none."""
    a = _flatten(args)
    emails = re.findall(_EMAIL, a)
    urls = re.findall(_URL, a)
    external = (
        any(not re.search(r"@(localhost|internal|corp|company|local)\b", e) for e in emails)
        or any(not re.search(r"//(localhost|127\.|10\.|192\.168|internal)", u) for u in urls)
        or bool(_PUBLIC_PATH.search(a))
    )
    if external:
        return "external"
    if emails or urls or re.search(r"\bchannel\b|recipient|to:", a):
        return "internal"
    return "none"


_UNTRUSTED_MARKERS = re.compile(
    r"untrusted|injection|ignore (the )?(previous|above|prior)|disregard (your|the)|bypass|"
    r"exfiltrat|skip (intermediate )?confirmation|override (your|the|safety|user)|jailbreak|"
    r"system prompt|new instructions?:",
    re.I,
)


def looks_untrusted(text: str) -> bool:
    return bool(_UNTRUSTED_MARKERS.search(text or ""))


# ── taint-flow primitives ───────────────────────────────────────────────
_SINK_RE = re.compile(
    r"send|forward|post|publish|tweet|webhook|curl|wget|upload|message|write|edit|create|"
    r"apply_patch|append|insert|move|copy|cp|mv|rm|unlink|delete|drop|remove|exec|process|"
    r"bash|sh|tmux|run|api|gh ",
    re.I,
)
_READ_RE = re.compile(r"read|cat|head|tail|ls|grep|find|list|view|envelope|capture", re.I)
_EXTERNAL_SEND_RE = re.compile(
    r"send|forward|post|publish|tweet|webhook|curl|wget|upload|message|email|gmail|sms|slack|"
    r"send.?keys|sendmessage",
    re.I,
)
_CRED_RE = re.compile(
    r"api[_-]?key|secret|credential|token|password|\.env|private[_-]?key|keychain|op_signin|"
    r"1password|vault|credentials",
    re.I,
)


def is_read_only(tool_name: str) -> bool:
    n = (tool_name or "").lower()
    return bool(_READ_RE.search(n)) or n == "get"


def is_sink(tool_name: str) -> bool:
    return bool(_SINK_RE.search(tool_name or "")) and not is_read_only(tool_name)


def is_external_send(tool_name: str) -> bool:
    return bool(_EXTERNAL_SEND_RE.search(tool_name or ""))


def is_credential_access(tool_name: str, args: Any) -> bool:
    return bool(_CRED_RE.search(tool_name or "")) or bool(_CRED_RE.search(_flatten(args)))


_STOP_TOKENS = frozenset(
    {"example.com", "localhost", "127.0.0.1", "0.0.0.0", "github.com", "schema.org"}
)
_TOKEN_RES = [
    re.compile(r"[\w.+-]+@[\w.-]+\.\w+"),                  # email
    re.compile(r"https?://[\w./?=&%+#~-]+"),               # url
    re.compile(r"\b[\w-]+\.(?:com|net|org|io|ai|co|dev|xyz|ru|cn|evil|sh|info)\b", re.I),  # domain
    re.compile(r"(?:/[\w.+-]+){2,}/?"),                    # deep path
]
_TRAILING_PUNCT = re.compile(r"[/.,);'\"]+$")


def extract_tokens(text: str) -> set[str]:
    """Distinctive tokens in text, normalised (lowercased, trailing punct stripped)."""
    t = (text or "").lower()
    out: set[str] = set()
    for rx in _TOKEN_RES:
        for tok in rx.findall(t):
            tok = _TRAILING_PUNCT.sub("", tok)
            if len(tok) >= 4 and tok not in _STOP_TOKENS:
                out.add(tok)
    return out


def taint_flow(tool_name: str, args: Any, taint: set[str]) -> str:
    """Graded taint-flow bucket: none < tainted-sink < tainted-external-target."""
    if not taint:
        return "none"
    at = _flatten(args)
    if is_external_send(tool_name):
        for tok in extract_tokens(at):
            if tok in taint:
                return "tainted-external-target"
    if is_sink(tool_name):
        for tok in taint:
            if tok in at:
                return "tainted-sink"
    return "none"


_IMPERATIVE_VERBS = [
    "forward", "send", "email", "post", "publish", "delete", "remove", "drop",
    "transfer", "wire", "pay", "grant", "disable", "exfiltrate", "upload", "share",
]
_IMPERATIVE_RES = {v: re.compile(r"\b" + v + r"\b") for v in _IMPERATIVE_VERBS}


def untrusted_imperatives(text: str) -> set[str]:
    t = (text or "").lower()
    return {v for v in _IMPERATIVE_VERBS if _IMPERATIVE_RES[v].search(t)}


def matches_imperative(tool_name: str, args: Any, verbs: set[str]) -> bool:
    if not verbs:
        return False
    blob = (tool_name or "").lower() + " " + _flatten(args)
    return any(re.search(r"\b" + v + r"\b", blob) for v in verbs)


def _result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result)
    except (TypeError, ValueError):
        return str(result)


def extract_safety(event: AgentToolEvent, session: Session) -> FeatureDict:
    """The 4 safety features for a proposed call, against taint reconstructed by
    replaying the session's tool_result/tool_call history (causal: only content
    seen BEFORE the call taints it). Mirrors the live SafetyTracker's per-call order.
    """
    tokens: set[str] = set()
    verbs: set[str] = set()
    cred_seen = False
    cred_exfil_chain = False

    for m in session.messages:
        if m.role == "tool_result":
            text = _result_to_text(m.result)
            if text:
                tokens |= extract_tokens(text)
                verbs |= untrusted_imperatives(text)
        elif m.role == "tool_call":
            # Complete the credential->external-send chain BEFORE recording credSeen
            # for this historical call (the external-send must come strictly after).
            if cred_seen and is_external_send(m.tool_name or ""):
                cred_exfil_chain = True
            if is_credential_access(m.tool_name or "", m.input):
                cred_seen = True

    # The proposed call (not in messages): complete the chain if it is the external-send.
    if cred_seen and is_external_send(event.tool_name):
        cred_exfil_chain = True

    return {
        "action-class": action_class(event.tool_name, event.input),
        "taint-flow": taint_flow(event.tool_name, event.input, tokens),
        "injected-imperative": "yes" if matches_imperative(event.tool_name, event.input, verbs) else "no",
        "cred-exfil-chain": "yes" if cred_exfil_chain else "no",
    }
