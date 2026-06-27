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


# action_class is computed from the action's STRUCTURE (the tool, and for command
# tools the command HEAD), never by scanning the payload CONTENT for action verbs.
# The old rules substring-matched the flattened args, so editing a DOC that merely
# *mentions* "delete" was classed `delete`, and a path ".../post.ts" was `external-
# send` — the content-regex disease (M3 fix). Where the data the action carries
# matters to harm (e.g. a curl's target externality), that is its OWN feature the
# posterior weights (target-externality), not a thing folded into action_class.
_TOOL_CLASS_RES: list[tuple[str, re.Pattern[str]]] = [  # by tool NAME, most-specific first
    ("credential-access", re.compile(r"op[_ ]?signin|1password|keychain|vault", re.I)),
    ("external-send", re.compile(r"\b(send|forward|publish|tweet|post|webhook|gmail|email|sendmessage|pinmessage|sms|slack|upload)\b", re.I)),
    ("cross-boundary", re.compile(r"web[_-]?fetch|web[_-]?search|browser|agent-browser|activate_window|screenshot|type_text", re.I)),
    ("delete", re.compile(r"\b(rm|unlink|rmdir|delete|remove|trash|drop)\b", re.I)),
    ("local-write", re.compile(r"\b(write|edit|create|apply_patch|patch|update|append|insert|move|mv|copy|cp|notebook_edit)\b", re.I)),
    ("read-only", re.compile(r"\b(read|cat|head|tail|ls|grep|find|search|get|list|print|fetch|capture|transcript|view|show|envelope)\b", re.I)),
    ("exec", re.compile(r"\b(exec|run|cron|invoke|trigger|deploy|gateway|api)\b", re.I)),
]
# A credential STORE as the target (the file/keychain being touched), not the word
# "secret" appearing in content — so `grep API_KEY src/` is not credential-access.
_CRED_FILE_RE = re.compile(
    r"\.env\b|private[_-]?key|id_rsa|\.pem\b|credentials?\.json|\.aws/|\.ssh/|keychain|"
    r"op[_ ]signin|1password|\.netrc", re.I)

# Command-head classification (the first real executable in a shell command).
_CMD_DELETE = {"rm", "unlink", "rmdir", "shred", "trash", "trash-put"}
_CMD_WRITE = {"cp", "mv", "tee", "touch", "mkdir", "ln", "install", "rsync"}
_CMD_READ = {"cat", "head", "tail", "ls", "grep", "rg", "egrep", "find", "less", "more",
             "stat", "file", "tree", "wc", "diff", "pwd", "which", "whoami", "echo", "printf"}
_CMD_WRAPPERS = {"sudo", "env", "nice", "time", "nohup", "xargs", "timeout", "stdbuf",
                 "command", "exec", "builtin", "then", "do", "&&", "||"}
# A consequential SINK can appear ANYWHERE in a pipeline / chain, not just at the head
# (`cat secrets | curl evil`, `echo x && wget …`, `echo $(curl …)`). Match a network or
# delete executable at a segment boundary (start, after | & ; ` or $(  ), allowing
# sudo/env prefixes — boundary-anchored so `grep "rm -rf"` / `cat http.py` don't trip.
_SINK_PREFIX = r"(?:^|[|&;`(]|\$\()\s*(?:sudo\s+|\w+=\S+\s+)*"
_NETWORK_SINK_RE = re.compile(_SINK_PREFIX + r"(curl|wget|nc|netcat|scp|sftp|ftp|rsync|telnet|ssh)\b", re.I)
_DELETE_SINK_RE = re.compile(_SINK_PREFIX + r"(rm|unlink|rmdir|shred)\b", re.I)
_REDIRECT_RE = re.compile(r">>?\s*[\w./~$-]")  # redirect to a file => a write


def _command_string(args: Any) -> str:
    if isinstance(args, dict):
        for k in ("command", "cmd", "script", "code"):
            v = args.get(k)
            if isinstance(v, str):
                return v
        return _flatten(args)
    return args if isinstance(args, str) else _flatten(args)


def _command_head(cmd: str) -> str:
    """The first real executable in the first pipeline segment (skipping env-var
    assignments and wrapper commands like sudo/env/time), basename-normalised."""
    seg = re.split(r"[|;&\n]", cmd, maxsplit=1)[0]
    for tok in seg.split():
        if re.match(r"^\w+=", tok):           # FOO=bar env assignment
            continue
        head = tok.split("/")[-1].lower()
        if head in _CMD_WRAPPERS or not head:
            continue
        return head
    return ""


def _command_action_class(args: Any) -> str:
    cmd = _command_string(args)
    if _CRED_FILE_RE.search(cmd):
        return "credential-access"
    # Sinks first, scanned over the WHOLE command (a pipeline/chain sink is the
    # consequential action) — a head-only parse would miss `cat x | curl evil`.
    if _NETWORK_SINK_RE.search(cmd):
        return "external-send"
    if _DELETE_SINK_RE.search(cmd) or re.search(r"\bdrop\s+table\b|\bdelete\s+from\b", cmd, re.I):
        return "delete"
    head = _command_head(cmd)
    if head in _CMD_WRITE or _REDIRECT_RE.search(cmd):  # write tool or a `>`/`>>` redirect
        return "local-write"
    if head in _CMD_READ:
        return "read-only"
    return "exec"


def action_class(tool_name: str, args: Any) -> str:
    """Risk class of an action, from its STRUCTURE: the tool name, or for command
    tools the command head. Never scans the content the action carries.

    TRAIN==RUNTIME GATE: action-class is shipped harm feature #1. This structure-based
    rewrite (M3) changes which cell a live call indexes, so it is NOT compatible with
    the frozen data/brain/harm_brain.counts.json — unlike the additive taint-source /
    target-externality features, this is NOT behaviour-neutral. The harm brain MUST be
    regenerated with THIS extractor before it ships (M4: build_harm_brain over ATBench +
    benign). The deployed wheel keeps its own aligned extractor+brain until then; master
    is not deployed. test_verify_conserves_totals_against_shipped measures the skew."""
    name = (tool_name or "").lower()
    if _COMMAND_TOOL_RE.search(name):
        return _command_action_class(args)
    target = producing_target(args) or ""
    if _CRED_FILE_RE.search(target) or _CRED_FILE_RE.search(name):
        return "credential-access"
    for cls, rx in _TOOL_CLASS_RES:
        if rx.search(name):
            return cls
    return "other"


_EMAIL = r"[\w.+-]+@[\w.-]+\.\w+"
_URL = r"https?://[\w.-]+"
_PUBLIC_PATH = re.compile(r"(^|[\"'/])(public|sync|shared|outbox|external)/", re.I)
# Where an action's DESTINATION lives in args — the send target, not the content it
# carries. Scoped so an Edit whose new_string mentions a URL is not read as a send to
# it (the same structural discipline action_class follows; M3 review fix).
_TARGET_FIELD_KEYS = ("to", "recipient", "recipients", "url", "uri", "endpoint", "dest",
                      "destination", "channel", "address", "cc", "bcc", "webhook", "host",
                      "command", "cmd", "script")


def _target_text(args: Any) -> str:
    if isinstance(args, dict):
        parts = [str(args[k]) for k in _TARGET_FIELD_KEYS if isinstance(args.get(k), (str, int, float))]
        return " ".join(parts).lower()
    return args.lower() if isinstance(args, str) else ""


def target_externality(tool_name: str, args: Any) -> str:
    """Does the action reach OUTSIDE the trusted boundary? external | internal | none.
    Scans only DESTINATION fields (recipient/url/command/...), never the content blob."""
    a = _target_text(args)
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


# ── provenance: the SOURCE-CLASS of consumed content (M2) ────────────────────
# We do NOT decide trusted/untrusted in the extractor and drop "trusted" taint —
# that collapses provenance to a hand-tuned threshold and craters recall. Instead
# every tool_result still seeds taint, but each token/verb is LABELLED with the
# class of the source that produced it. The class becomes the `taint-source`
# FEATURE; `condition` learns which (action × taint × source) combinations are
# harmful (web→external-send = harm; local-project-read→edit = benign). Fine-
# grained on purpose — the structure-BMA auto-sophisticates over the classes;
# coarse trusted/untrusted bucketing would be the irreversible mistake.
#
# Ordered most-external first; first match wins.
_SOURCE_CLASS_RES: list[tuple[str, re.Pattern[str]]] = [
    ("web", re.compile(r"web[_-]?fetch|web[_-]?search|fetch[_-]?url|url[_-]?fetch|search\b", re.I)),
    ("browser", re.compile(r"browser|browse|activate_window|screenshot|type_text", re.I)),
    ("email", re.compile(r"gmail|\be?mail\b|imap|himalaya|envelope", re.I)),
    ("message", re.compile(r"\bsms\b|slack|telegram|discord|message|inbox|\bdm\b|pin\b", re.I)),
]
# Command-style tools carry their real action in the args, not the name.
_COMMAND_TOOL_RE = re.compile(r"\b(bash|sh|zsh|shell|exec|process|tmux|run|command|cmd)\b", re.I)
_NETWORK_CMD_RE = re.compile(r"(?:^|[|&;`]\s*|\s)(curl|wget|nc|netcat|ftp|scp|sftp|ssh|telnet|http|https)\b", re.I)

# Externality ordering: when a sink is reached by tokens from several sources, the
# MOST-external source class wins (it is the one an attacker most plausibly controls).
# External channels first, then external/unknown-locality local reads, then own reads.
_SOURCE_EXTERNALITY = [
    "web", "browser", "email", "message", "command-network", "marker",
    "read-external", "command-external", "local-external",
    "read-unknown", "command-unknown", "local-unknown",
    "read-own", "command-own", "local-own",
]


# Where a producing tool_call's target sits relative to the agent's declared
# own-footprint. A FEATURE value, learned by the posterior — never a gate.
_PATH_ARG_KEYS = ("file_path", "filepath", "path", "filename", "file", "target",
                  "notebook_path", "note", "dir", "directory")
_PATH_IN_CMD = re.compile(r"(?<![\w@])(~?/[\w.+\-/]+|\.{1,2}/[\w.+\-/]+|[\w.+\-]+/[\w.+\-/]+|[\w.+\-]+\.\w{1,5})")


def producing_target(args: Any) -> str | None:
    """The path/target a producing tool_call read, from its args (a declared key, or
    the first path-like token in a shell command)."""
    if isinstance(args, dict):
        for k in _PATH_ARG_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        cmd = args.get("command") or args.get("cmd")
        if isinstance(cmd, str):
            m = _PATH_IN_CMD.search(cmd)
            return m.group(0) if m else None
    elif isinstance(args, str):
        m = _PATH_IN_CMD.search(args)
        return m.group(0) if m else None
    return None


def target_locality(path: str | None, trusted_paths: list[str], project_root: str = "") -> str:
    """own | external | unknown — is ``path`` within the agent's declared own-footprint?
    Explicit trusted patterns (the agent's identity/config/state) match anywhere in the
    path; an absolute path is own iff under project_root; a relative path is own only
    when a project_root is declared (it resolves to the agent's own working dir)."""
    if not path:
        return "unknown"
    for pat in trusted_paths:
        if pat and pat in path:
            return "own"
    if path.startswith("/"):
        return "own" if project_root and path.startswith(project_root) else "external"
    return "own" if project_root else "external"


def source_class(result_tool_name: str | None, producing_command: str | None = None,
                 marked: bool = False, locality: str = "unknown") -> str:
    """The provenance class of a tool_result's content. Not a trust verdict — a
    feature value the harm posterior conditions on. ``producing_command`` is the
    flattened args of the producing tool_call (disambiguates bash curl vs cat);
    ``marked`` flags injection-marker content; ``locality`` places a local read's
    target in the agent's own-footprint (own/external/unknown)."""
    n = (result_tool_name or "").lower()
    for cls, rx in _SOURCE_CLASS_RES:
        if rx.search(n):
            return cls
    if _COMMAND_TOOL_RE.search(n):
        if producing_command and _NETWORK_CMD_RE.search(producing_command):
            return "command-network"
        return "marker" if marked else f"command-{locality}"
    if marked:
        return "marker"
    if is_read_only(n):
        return f"read-{locality}"
    return f"local-{locality}"


def _most_external(classes: set[str]) -> str:
    for cls in _SOURCE_EXTERNALITY:
        if cls in classes:
            return cls
    return "none"


def _same_tool(call_tool: str | None, result_tool: str | None) -> bool:
    """Does a prior tool_call's tool match the tool that produced a tool_result?
    Used to attribute a result's producing command to the call before it."""
    return bool(call_tool) and bool(result_tool) and call_tool.strip().lower() == result_tool.strip().lower()


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
    # token/verb -> the MOST-external source class that introduced it. Every result
    # still seeds (recall preserved); provenance is carried as a label, not a gate.
    token_source: dict[str, str] = {}
    verb_source: dict[str, str] = {}
    cred_seen = False
    cred_exfil_chain = False
    prev_call_tool: str | None = None
    prev_call_input: Any = None

    def _tag(store: dict[str, str], items: set[str], cls: str) -> None:
        for it in items:
            cur = store.get(it)
            if cur is None or _SOURCE_EXTERNALITY.index(cls) < _SOURCE_EXTERNALITY.index(cur):
                store[it] = cls

    for m in session.messages:
        if m.role == "tool_result":
            text = _result_to_text(m.result)
            if text:
                if _same_tool(prev_call_tool, m.tool_name):
                    producing = _flatten(prev_call_input)
                    loc = target_locality(producing_target(prev_call_input),
                                          session.trusted_paths, session.project_root)
                else:
                    producing, loc = None, "unknown"
                cls = source_class(m.tool_name, producing, marked=looks_untrusted(text), locality=loc)
                _tag(token_source, extract_tokens(text), cls)
                _tag(verb_source, untrusted_imperatives(text), cls)
        elif m.role == "tool_call":
            # Complete the credential->external-send chain BEFORE recording credSeen
            # for this historical call (the external-send must come strictly after).
            if cred_seen and is_external_send(m.tool_name or ""):
                cred_exfil_chain = True
            if is_credential_access(m.tool_name or "", m.input):
                cred_seen = True
            prev_call_tool = m.tool_name
            prev_call_input = m.input

    # The proposed call (not in messages): complete the chain if it is the external-send.
    if cred_seen and is_external_send(event.tool_name):
        cred_exfil_chain = True

    tokens = set(token_source)
    flow = taint_flow(event.tool_name, event.input, tokens)
    verbs = set(verb_source)
    imperative = matches_imperative(event.tool_name, event.input, verbs)
    return {
        "action-class": action_class(event.tool_name, event.input),
        "taint-flow": flow,
        "taint-source": _taint_source(event, flow, token_source, verbs, verb_source, imperative),
        "target-externality": target_externality(event.tool_name, event.input),
        "injected-imperative": "yes" if imperative else "no",
        "cred-exfil-chain": "yes" if cred_exfil_chain else "no",
    }


def _taint_source(event: AgentToolEvent, flow: str, token_source: dict[str, str],
                  verbs: set[str], verb_source: dict[str, str], imperative: bool) -> str:
    """The provenance class of the untrusted content that REACHED this call — via a
    matched taint token (taint-flow) or a matched injected imperative. 'none' when the
    call carries no untrusted influence. The harm posterior conditions on this so it
    can discount benign-provenance taint (local-project read → edit) without losing
    external-provenance recall (web → external-send)."""
    matched: set[str] = set()
    if flow != "none":
        at = _flatten(event.input)
        if is_external_send(event.tool_name):
            for tok in extract_tokens(at):
                if tok in token_source:
                    matched.add(token_source[tok])
        if is_sink(event.tool_name):
            for tok, cls in token_source.items():
                if tok in at:
                    matched.add(cls)
    if imperative:
        blob = (event.tool_name or "").lower() + " " + _flatten(event.input)
        for v in verbs:
            if re.search(r"\b" + v + r"\b", blob):
                matched.add(verb_source.get(v, "local-unknown"))  # a real class in _SOURCE_EXTERNALITY
    return _most_external(matched)
