// index.ts — credence-openclaw OpenClaw-plugin body.
//
// Governs the pi/OpenClaw agent loop by intercepting tool calls and
// routing the decision to the credence-openclaw Julia daemon (the opaque
// brain). Reuses credence-openclaw's async wire UNCHANGED: POST /sensor (a
// tool-proposed sensor event) then await the correlated effector signal
// off the SSE /signals stream; map it to OpenClaw's before_tool_call
// result. Also logs tool outcomes and reconstructed per-turn cost so the
// observation log accumulates the data the dollars-saved surface (Move 2)
// needs.
//
// Discipline (matches the pi-extension body):
//   - The BRAIN decides; the body only translates. ask -> requireApproval
//     (OpenClaw enforces the user's choice natively); the body posts
//     user-responded via onResolution so the brain learns, but does not
//     itself decide proceed/block on the reply.
//   - Fail-open everywhere: daemon unreachable / slow ⇒ the tool proceeds,
//     with one warning per outage.
//
// The orchestration lives in `createGovernor`, separated from `register`
// so it can be unit-tested with an injected DaemonClient (see
// tests/index.test.ts).

import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { openSync, closeSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";

import {
  createDaemonClient,
  type DaemonClient,
  type SignalEnvelope,
  type Logger,
} from "./daemon-client.js";
import { SessionTracker } from "./session.js";
import { extractRoutingFeatures } from "./routing-features.js";
import { buildRoster, type RoutingModel } from "./roster.js";
import { buildPriceTable, computeTurnCost, type PriceTable } from "./cost.js";
import { resolveProfile, type Profile } from "./profile.js";
import type {
  PluginEntry,
  BeforeToolCallEvent,
  BeforeToolCallResult,
  AfterToolCallEvent,
  LlmOutputEvent,
  BeforeModelResolveEvent,
  BeforeModelResolveResult,
  ToolContext,
  RequireApprovalPayload,
} from "./openclaw-types.js";

const DEFAULT_DAEMON_URL = "http://127.0.0.1:8787";
const DEFAULT_HOOK_TIMEOUT_MS = 3_000;
// How long OpenClaw waits for the human on an `ask` (requireApproval).
// Distinct from the daemon-decision timeout above.
const DEFAULT_APPROVAL_TIMEOUT_MS = 120_000;

// The daemon the adapter talks to. Single source for the start command + the "is it up?"
// probe budget, shared by the startup health-check AND the fail-open warnings (DRY).
const DAEMON_START_COMMAND = "credence-governor-daemon";
const AUTOSTART_ENV = "CREDENCE_GOVERNOR_AUTOSTART";
const READY_PROBE_TIMEOUT_MS = 2_000; // matches logSessionSummary's /report budget
// Appended to every fail-open warning so the fix is always one copy-paste away.
const DAEMON_HINT = `Start it: ${DAEMON_START_COMMAND}`;

function newEventId(): string {
  return `evt_${randomUUID().slice(0, 12)}`;
}

// Cap the correlation maps (toolCallId→governance eventId, session→last governance eventId)
// so a long run — or a tool call that never completes — can't grow them without bound. When
// full, the oldest entry is evicted (a Map preserves insertion order).
const MAX_CORRELATION_ENTRIES = 1024;
function rememberBounded<K, V>(map: Map<K, V>, key: K, value: V): void {
  map.set(key, value);
  if (map.size > MAX_CORRELATION_ENTRIES) {
    const oldest = map.keys().next().value as K | undefined;
    if (oldest !== undefined) map.delete(oldest);
  }
}

// ── startup daemon health-check ──────────────────────────────────────────────────
// Proactive: at plugin load, tell the operator if the daemon is down (governance and
// routing are a silent fail-open no-op without it) with the exact fix — and, only if
// they opt in, bring it up. A read-only inline GET /ready probe, exactly like
// logSessionSummary's /report call, so the vendored daemon-client stays verbatim.

/** One-shot GET /ready, AbortController-bounded. Never throws; any error ⇒ false (down). */
export async function daemonIsReady(
  daemonUrl: string,
  timeoutMs: number = READY_PROBE_TIMEOUT_MS,
): Promise<boolean> {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(`${daemonUrl.replace(/\/+$/, "")}/ready`, { signal: ctrl.signal });
      return res.ok;
    } finally {
      clearTimeout(t);
    }
  } catch {
    return false; // ECONNREFUSED (down) or timeout (hung) ⇒ treat as down
  }
}

/** True for a daemonUrl we may locally autostart (loopback). A remote URL means a daemon
 * on another host that must not be launched here — warn-only there. */
export function isLoopbackUrl(daemonUrl: string): boolean {
  try {
    const h = new URL(daemonUrl).hostname.toLowerCase().replace(/^\[|\]$/g, "");
    return h === "127.0.0.1" || h === "localhost" || h === "::1" || h === "";
  } catch {
    return false;
  }
}

/** Spawn the daemon DETACHED so it survives the gateway. The daemon binds the host/port
 * from `daemonUrl`, so it answers at exactly the URL we probe (not a stale default).
 * Boot diagnostics go to ~/.credence-governor/daemon.log (so a failed autostart is
 * debuggable). Fail-open: a missing command (ENOENT — core not installed) is swallowed
 * via on('error'), never thrown. We never watch the child, so a loser that fails to bind
 * the port just exits harmlessly (the daemon binds before booting the engine). */
export function spawnDaemonDetached(daemonUrl: string, log: Logger): void {
  try {
    const u = new URL(daemonUrl);
    const env = {
      ...process.env,
      CREDENCE_GOVERNOR_HOST: u.hostname.replace(/^\[|\]$/g, ""),
      CREDENCE_GOVERNOR_PORT: u.port || "8787",
    };
    // Capture the spawned daemon's stdout/stderr to a log file so "why didn't autostart
    // work?" is answerable; fall back to ignore if the file can't be opened.
    let stdio: "ignore" | ["ignore", number, number] = "ignore";
    let logFd: number | undefined;
    try {
      const logPath = join(homedir(), ".credence-governor", "daemon.log");
      mkdirSync(dirname(logPath), { recursive: true });
      logFd = openSync(logPath, "a");
      stdio = ["ignore", logFd, logFd];
    } catch {
      /* no log file — proceed with ignore */
    }
    const child = spawn(DAEMON_START_COMMAND, [], { detached: true, stdio, env });
    child.on("error", (err) => {
      log(
        `credence-openclaw: could not auto-start the daemon (is ${DAEMON_START_COMMAND} ` +
          `installed?). Install it: pip install credence-governor-core`,
        err,
      );
    });
    child.unref();
    if (logFd !== undefined) closeSync(logFd); // the detached child kept its own dup
  } catch (err) {
    log("credence-openclaw: daemon auto-start failed (failing open)", err);
  }
}

/** Fire-and-forget startup check: silent if up; if down, warn with the start command
 * (and optionally auto-start). Never throws — preserves the fail-open guarantee. The
 * injectable deps keep it unit-testable without real fetch/spawn. */
export async function runStartupDaemonCheck(
  daemonUrl: string,
  autostart: boolean,
  log: Logger,
  deps: {
    probe?: (url: string) => Promise<boolean>;
    spawnDaemon?: (daemonUrl: string, log: Logger) => void;
  } = {},
): Promise<void> {
  const probe = deps.probe ?? ((u: string) => daemonIsReady(u));
  const spawnDaemon = deps.spawnDaemon ?? spawnDaemonDetached;
  try {
    if (await probe(daemonUrl)) return; // up ⇒ silent (no per-start spam)
    // Autostart only a LOCAL daemon — a remote daemonUrl can't be launched from here.
    if (autostart && isLoopbackUrl(daemonUrl)) {
      log(
        `credence-openclaw: governor daemon is DOWN at ${daemonUrl} — routing and governance ` +
          `are OFF; auto-starting \`${DAEMON_START_COMMAND}\` (engine boot ~18s; tool calls ` +
          `proceed UNGUARDED until it is up).`,
      );
      spawnDaemon(daemonUrl, log);
      return;
    }
    log(
      `credence-openclaw: ⚠ governor daemon is DOWN at ${daemonUrl} — routing and governance ` +
        `are OFF (tool calls proceed UNGUARDED) until it is up. ${DAEMON_HINT}  ` +
        `(or set autostartDaemon:true / ${AUTOSTART_ENV}=1 to auto-launch it).`,
    );
  } catch {
    /* never let the startup check break plugin load */
  }
}

// Build an OVERRIDABLE approval (the human resolves allow/deny). Shared by the `ask`
// effector and — by default — by `block`, so both surface to the operator rather than
// hard-refusing. onResolution posts the mapped user-responded back to the brain.
function approvalResult(
  description: string,
  originatingEventId: string,
  client: DaemonClient,
  approvalTimeoutMs: number,
): BeforeToolCallResult {
  const requireApproval: RequireApprovalPayload = {
    title: "credence-openclaw governance",
    description,
    severity: "warning",
    timeoutMs: approvalTimeoutMs,
    timeoutBehavior: "deny",
    allowedDecisions: ["allow-once", "allow-always", "deny"],
    onResolution: async (decision) => {
      const response =
        decision === "allow-once" || decision === "allow-always"
          ? "yes"
          : decision === "deny"
            ? "no"
            : "timeout";
      // Fire-and-forget: the brain conditions on the reply; OpenClaw has already
      // enforced the decision. The daemon's follow-up signal is harmlessly dropped.
      await client.postSensor({
        event_type: "user-responded",
        event_id: newEventId(),
        in_response_to: originatingEventId,
        timestamp: new Date().toISOString(),
        response,
      });
    },
  };
  return { requireApproval };
}

export function mapSignal(
  sig: SignalEnvelope | undefined,
  originatingEventId: string,
  client: DaemonClient,
  approvalTimeoutMs: number,
  hardBlock = false,
): BeforeToolCallResult | undefined {
  if (!sig) return undefined; // timeout / fail-open ⇒ proceed
  const p = sig.parameters ?? {};
  switch (sig.effector) {
    case "proceed":
      return undefined;
    case "block": {
      const reason =
        typeof p.reason === "string"
          ? p.reason
          : "tool call vetoed by expected-utility calculation";
      // OVERRIDABLE by default: the governor surfaces the block for the human to
      // resolve (the operator is the final authority; with finite harm-cost EU an
      // override is admissible evidence, so nothing is categorically un-overridable).
      // An operator wanting hard enforcement sets config.hardBlock (=> a true block).
      if (hardBlock) {
        return { block: true, blockReason: `credence-openclaw: ${reason}` };
      }
      return approvalResult(
        `credence-openclaw flags this call: ${reason}. Approve to run anyway.`,
        originatingEventId,
        client,
        approvalTimeoutMs,
      );
    }
    case "ask":
      return approvalResult(
        typeof p.text === "string" ? p.text : "Confirm this tool call?",
        originatingEventId,
        client,
        approvalTimeoutMs,
      );
    default:
      return undefined; // unknown effector ⇒ fail open
  }
}

// Map a `route` effector signal to OpenClaw's model override. A missing/timed-out/
// non-route signal ⇒ undefined ⇒ OpenClaw keeps its configured model (fail open, exactly
// like the daemon being down). In shadow mode we log the would-route and still defer, so
// operators can see routing decisions on real traffic without changing the model used.
export function mapRouteSignal(
  sig: SignalEnvelope | undefined,
  shadowMode: boolean,
  log: Logger,
): BeforeModelResolveResult | undefined {
  if (!sig || sig.effector !== "route") return undefined;
  const p = sig.parameters ?? {};
  const model = typeof p.model === "string" ? p.model : undefined;
  const provider = typeof p.provider === "string" ? p.provider : undefined;
  if (!model) return undefined;
  if (shadowMode) {
    log(
      `credence-openclaw[shadow]: would route to ${provider ?? "?"}/${model} — keeping OpenClaw's model (shadow mode)`,
    );
    return undefined;
  }
  const result: BeforeModelResolveResult = { modelOverride: model };
  if (provider) result.providerOverride = provider;
  return result;
}

export interface GovernorOpts {
  hookTimeoutMs: number;
  approvalTimeoutMs: number;
  priceTable: PriceTable;
  redactToolInputs: boolean;
  /** Observe-only: the brain still decides and the daemon still logs the
   *  decision, but the body NEVER enforces (always proceeds). Lets operators
   *  measure what governance WOULD do on real usage without affecting runs —
   *  the basis for counterfactual telemetry. Default false (enforcing). */
  shadowMode: boolean;
  /** Overridability policy. Default false ⇒ a `block` is surfaced as an OVERRIDABLE
   *  approval (the human is the final authority). Set true to make blocks a hard,
   *  non-overridable refusal — the opt-in for operators who want strict enforcement. */
  hardBlock: boolean;
  /** The user's model roster (discovered from api.config), sent in each route-request so the
   *  brain routes over the models OpenClaw actually has. Empty ⇒ routing is not registered. */
  roster: RoutingModel[];
  /** The user's utility profile (cost/time/quality/risk trade-offs), sent in each sensor event
   *  so the daemon applies the user's preferences per-request (no restart). The brain does the
   *  EU-max; this is preference DATA the body ships. */
  profile: Profile;
  log: Logger;
}

export interface Governor {
  beforeToolCall: (
    event: BeforeToolCallEvent,
    ctx: ToolContext,
  ) => Promise<BeforeToolCallResult | undefined>;
  beforeModelResolve: (
    event: BeforeModelResolveEvent,
    ctx: ToolContext,
  ) => Promise<BeforeModelResolveResult | undefined>;
  afterToolCall: (event: AfterToolCallEvent, ctx: ToolContext) => Promise<void>;
  llmOutput: (event: LlmOutputEvent, ctx: ToolContext) => Promise<void>;
  cleanup: () => void;
  /** Test/inspection accessor: in-flight sensor awaiters (tool-call + route). */
  pendingCount: () => number;
}

// The governance orchestration over an injected DaemonClient. register()
// wires this to the OpenClaw hook API; tests drive it with a fake client.
export function createGovernor(
  client: DaemonClient,
  opts: GovernorOpts,
): Governor {
  const { hookTimeoutMs, approvalTimeoutMs, priceTable, redactToolInputs,
    shadowMode, hardBlock, roster, profile, log } = opts;
  // One per-run message buffer. Feature & taint extraction is server-side in the daemon
  // (single-sourced in credence-governor-core); the body only maintains the neutral
  // session history the daemon extracts from — see session.ts.
  const session = new SessionTracker();

  // event_id -> resolver for the awaited effector signal. The single SSE
  // consumer dispatches signals here by in_response_to. Unmatched signals
  // (e.g. an ask-followup after the hook already resolved) find no resolver
  // and are dropped.
  const awaiters = new Map<string, (sig: SignalEnvelope | undefined) => void>();

  // Correlate a tool's completion + a turn's cost back to the GOVERNANCE decision they
  // followed. beforeToolCall remembers its eventId under the tool-call id and the session;
  // afterToolCall pops the tool-call id → the governance eventId (so the daemon links the
  // OUTCOME to the decision, not to the tool-call id); llmOutput reads the session's most
  // recent governance eventId. Both bounded (rememberBounded) so a long run can't leak.
  const govEventByToolCall = new Map<string, string>();
  const lastGovEventBySession = new Map<string, string>();

  const sse = client.connectSignalsStream((sig) => {
    const resolve = awaiters.get(sig.in_response_to);
    if (resolve) resolve(sig);
  });

  let warnedDown = false;
  let announcedUp = false;
  let down = false;

  // Register an awaiter for the correlated effector signal (dispatched by the single SSE
  // consumer on `in_response_to == eventId`) and a fail-open timeout. Shared by
  // beforeToolCall (tool-proposed → proceed/block/ask) and beforeModelResolve
  // (route-request → route): same wire, same correlation, same timeout discipline.
  function awaitSignal(eventId: string): Promise<SignalEnvelope | undefined> {
    return new Promise<SignalEnvelope | undefined>((resolve) => {
      const timer = setTimeout(() => {
        awaiters.delete(eventId);
        resolve(undefined);
      }, hookTimeoutMs);
      awaiters.set(eventId, (sig) => {
        clearTimeout(timer);
        awaiters.delete(eventId);
        resolve(sig);
      });
    });
  }

  async function beforeToolCall(
    event: BeforeToolCallEvent,
    ctx: ToolContext,
  ): Promise<BeforeToolCallResult | undefined> {
    const eventId = newEventId();
    const t0 = Date.now();
    const sid = ctx.sessionId ?? ctx.sessionKey ?? "";
    const signalPromise = awaitSignal(eventId);

    // Remember this governance decision so the coming tool-completion (by tool-call id) and
    // the turn's cost (by session) can correlate back to it. Set before the post so it holds
    // even on a fail-open path; the daemon only records an outcome when the eventId matches a
    // logged proposal, so an unlogged (failed-post) decision correlates to nothing.
    if (event.toolCallId) rememberBounded(govEventByToolCall, event.toolCallId, eventId);
    if (sid) rememberBounded(lastGovEventBySession, sid, eventId);

    // Build the neutral decision request (tool + input + prior session history) and let
    // the daemon extract features/taint server-side. The proposed call is excluded from
    // session.messages (the extractors count priors only); snapshot records it afterwards.
    const req = session.snapshot(event, ctx);
    const post = await client.postSensor({
      event_type: "tool-proposed",
      event_id: eventId,
      session_id: sid,
      timestamp: new Date().toISOString(),
      // The neutral event the daemon extracts from (tool-name / repetition / taint all
      // derive from these). `input` reaches the daemon transiently for extraction; it is
      // never logged raw (the observation log stores only the derived feature buckets).
      tool_name: req.tool_name,
      input: req.input,
      session: req.session,
      // The human-facing ask-text preview only. `redactToolInputs` blanks it so secrets
      // (commands, tokens) never surface in the approval UI; extraction still uses the
      // real `input` above.
      proposed_call: {
        tool_name: event.toolName,
        input: redactToolInputs ? null : event.params,
      },
      // The user's utility weights (λ/q/harm/w_time read here) — preference, not learning.
      profile,
    });

    if (!post.ok) {
      const r = awaiters.get(eventId);
      if (r) r(undefined); // clean up timer + awaiter
      if (!warnedDown) {
        log(
          `credence-openclaw: daemon unreachable at the configured URL; proceeding WITHOUT ` +
            `governance (fail-open, no error). ${DAEMON_HINT}`,
        );
        warnedDown = true;
      }
      down = true;
      announcedUp = false;
      return undefined; // fail open
    }
    if (down && !announcedUp) {
      log("credence-openclaw: daemon reachable again; governance resumed");
      announcedUp = true;
      down = false;
      warnedDown = false; // re-arm the unreachable warning for the next outage
    }

    const sig = await signalPromise;

    // Governance round-trip overhead (sensor POST + signal wait). Recorded for
    // the honest *time* accounting (governance adds latency). Fire-and-forget;
    // the daemon logs unknown event_types before warning, so it lands in the
    // observation log without affecting the decision.
    const latencyMs = Date.now() - t0;
    void client.postSensor({
      event_type: "governance-latency",
      event_id: newEventId(),
      in_response_to: eventId,
      timestamp: new Date().toISOString(),
      latency_ms: latencyMs,
    });

    // Observe-only: the brain decided and the daemon logged it; the body does
    // not enforce. We also durably RECORD the counterfactual (a body-owned fact,
    // like governance-latency above) so the dollars-saved surface can separate
    // "would have blocked" (shadow) from "actually prevented" (enforce). Without
    // it, the daemon's `decision` log is identical in both modes and /report
    // would count shadow would-blocks as real prevention.
    if (shadowMode) {
      if (sig && (sig.effector === "block" || sig.effector === "ask")) {
        log(
          `credence-openclaw[shadow]: would ${sig.effector} \`${event.toolName}\` — proceeding (shadow mode)`,
        );
        void client.postSensor({
          event_type: "counterfactual-decision",
          event_id: newEventId(),
          in_response_to: eventId,
          session_id: sid,
          timestamp: new Date().toISOString(),
          effector: sig.effector,
          tool_name: event.toolName,
        });
      }
      return undefined;
    }

    return mapSignal(sig, eventId, client, approvalTimeoutMs, hardBlock);
  }

  // before_model_resolve: route this turn to the EU-max model. Same wire as
  // beforeToolCall — post a route-request, await the correlated `route` signal — but the
  // signal carries {model, provider} the brain chose, mapped to OpenClaw's override.
  // Fail open everywhere (daemon down / slow / routing unconfigured ⇒ undefined ⇒
  // OpenClaw keeps its configured model). The brain decides; the body only translates.
  async function beforeModelResolve(
    event: BeforeModelResolveEvent,
    ctx: ToolContext,
  ): Promise<BeforeModelResolveResult | undefined> {
    const eventId = newEventId();
    const signalPromise = awaitSignal(eventId);

    const features = extractRoutingFeatures(event);
    const post = await client.postSensor({
      event_type: "route-request",
      event_id: eventId,
      session_id: ctx.sessionId ?? ctx.sessionKey ?? "",
      timestamp: new Date().toISOString(),
      features,
      // The user's live model roster (roster-aware routing): the brain routes over THESE
      // models + their costs, not a hardcoded list. Always ≥2 here (register gates on it).
      models: roster,
      // The user's utility weights (reward + w_time read here) — the time/money trade-off.
      profile,
    });

    if (!post.ok) {
      awaiters.get(eventId)?.(undefined); // clean up timer + awaiter
      if (!warnedDown) {
        log(
          `credence-openclaw: daemon unreachable; routing skipped (OpenClaw keeps its model). ${DAEMON_HINT}`,
        );
        warnedDown = true;
      }
      down = true;
      announcedUp = false;
      return undefined; // fail open
    }
    if (down && !announcedUp) {
      log("credence-openclaw: daemon reachable again; routing resumed");
      announcedUp = true;
      down = false;
      warnedDown = false;
    }

    const sig = await signalPromise;
    return mapRouteSignal(sig, shadowMode, log);
  }

  async function afterToolCall(
    event: AfterToolCallEvent,
    ctx: ToolContext,
  ): Promise<void> {
    // Taint SOURCE: the tool result is content from the outside world. Record it in the
    // session buffer so the daemon flags a later sink carrying its tokens (causal — only
    // results seen BEFORE a call can taint it; the daemon replays the buffer in order).
    session.recordResult(event, ctx);
    // Correlate the completion to the GOVERNANCE decision it followed: the eventId
    // beforeToolCall remembered under this tool-call id. Fall back to the tool-call id when
    // no decision was seen for it (a tool that skipped the gate) — the daemon then records no
    // outcome (it links only to a logged proposal). Pop so the map drains as calls complete.
    const toolCallId = event.toolCallId ?? "";
    const inResponseTo = (toolCallId && govEventByToolCall.get(toolCallId)) || toolCallId;
    if (toolCallId) govEventByToolCall.delete(toolCallId);
    const completed = event.error == null;
    const latencyS = event.durationMs != null ? event.durationMs / 1000 : null;
    await client.postSensor({
      event_type: "tool-completed",
      event_id: newEventId(),
      in_response_to: inResponseTo,
      // session_id lets the daemon credit this outcome to the turn's routed model
      // (online routing learning), correlated by session, not by in_response_to.
      session_id: ctx.sessionId ?? ctx.sessionKey ?? "",
      timestamp: new Date().toISOString(),
      // Top-level measured observables (mirroring outcome.*) so the event is self-describing.
      completed,
      latency_s: latencyS,
      outcome: {
        success: completed,
        duration_ms: event.durationMs ?? null,
        result_summary: null,
        error: event.error ?? null,
      },
    });
  }

  async function llmOutput(
    event: LlmOutputEvent,
    ctx: ToolContext,
  ): Promise<void> {
    const tc = computeTurnCost(event, priceTable);
    const sid = ctx.sessionId ?? event.sessionId ?? "";
    // Attach the session's most recent governance eventId when we know it, so a turn's cost
    // can be joined to the decision that turn belongs to. Session-only when unknown (a cost
    // event before any governed tool call) — never invented.
    const govEventId = sid ? lastGovEventBySession.get(sid) : undefined;
    const post: Record<string, unknown> = {
      event_type: "turn-cost",
      event_id: newEventId(),
      session_id: sid,
      timestamp: new Date().toISOString(),
      usd: tc.usd,
      total_tokens: tc.total_tokens,
      input_tokens: tc.input_tokens,
      output_tokens: tc.output_tokens,
      cache_read: tc.cache_read,
      cache_write: tc.cache_write,
      model: tc.model,
    };
    if (govEventId) post.in_response_to = govEventId;
    await client.postSensor(post);
  }

  function cleanup(): void {
    sse.close();
    for (const resolve of awaiters.values()) resolve(undefined);
    awaiters.clear();
    govEventByToolCall.clear();
    lastGovEventBySession.clear();
  }

  return {
    beforeToolCall,
    beforeModelResolve,
    afterToolCall,
    llmOutput,
    cleanup,
    pendingCount: () => awaiters.size,
  };
}

const plugin: PluginEntry = {
  id: "credence-openclaw",
  name: "credence-openclaw governance",
  description:
    "Bayesian in-loop governance for the pi/OpenClaw agent — intercepts tool calls (allow/block/ask) via the credence-openclaw brain and logs outcomes + per-turn cost.",

  register(api) {
    const cfg = api.pluginConfig ?? {};
    const daemonUrl =
      typeof cfg.daemonUrl === "string" ? cfg.daemonUrl : DEFAULT_DAEMON_URL;
    const hookTimeoutMs =
      typeof cfg.hookTimeoutMs === "number"
        ? cfg.hookTimeoutMs
        : DEFAULT_HOOK_TIMEOUT_MS;
    const approvalTimeoutMs =
      typeof cfg.approvalTimeoutMs === "number"
        ? cfg.approvalTimeoutMs
        : DEFAULT_APPROVAL_TIMEOUT_MS;
    const silent = cfg.silent === true;
    const redactToolInputs = cfg.redactToolInputs === true;
    const shadowMode = cfg.shadowMode === true;
    // Overridability: default OFF ⇒ blocks are overridable approvals (the human decides).
    // Set hardBlock:true for strict, non-overridable enforcement.
    const hardBlock = cfg.hardBlock === true;
    const routingEnabled = cfg.routing !== false; // model routing is ON by default
    // Opt-in (default OFF): auto-start the daemon if it's down at load. Config key OR
    // the cross-harness CREDENCE_GOVERNOR_AUTOSTART env — either enables; both default off.
    const autostartDaemon =
      cfg.autostartDaemon === true ||
      ["1", "true", "yes", "on"].includes(String(process.env[AUTOSTART_ENV] ?? "").toLowerCase());
    const priceTable = buildPriceTable(cfg.pricing);
    // The user's utility profile: a named preset (default `balanced`) + an optional per-dial
    // override, resolved to the full weight vector sent with each sensor event. This is how a
    // user expresses their cost/time/quality/risk trade-off — no daemon restart, no Julia edit.
    const profile = resolveProfile(
      typeof cfg.profile === "string" ? cfg.profile : undefined,
      typeof cfg.profileOverride === "object" && cfg.profileOverride !== null
        ? (cfg.profileOverride as Record<string, unknown>)
        : undefined,
    );

    const log: Logger = (m, e) => {
      if (silent) return;
      const msg = e === undefined ? m : `${m} ${String(e)}`;
      api.logger?.warn?.(msg);
    };

    // Roster-aware routing: discover the user's models (+ costs) from the host config. Guarded —
    // a missing/odd config yields an empty roster ⇒ routing stays inactive (never mis-routes to
    // a hardcoded default). The body reads config (IO); the brain stays config-agnostic.
    let roster: RoutingModel[] = [];
    try {
      roster = buildRoster(api.config, priceTable);
    } catch (err) {
      log("credence-openclaw: could not read the model roster from config; routing inactive", err);
    }
    // Route only when there are ≥2 priceable models to choose between; else leave OpenClaw's.
    const routingActive = routingEnabled && roster.length >= 2;

    const client = createDaemonClient({
      baseUrl: daemonUrl,
      timeoutMs: hookTimeoutMs,
      logger: log,
    });
    const gov = createGovernor(client, {
      hookTimeoutMs,
      approvalTimeoutMs,
      priceTable,
      redactToolInputs,
      shadowMode,
      hardBlock,
      roster,
      profile,
      log,
    });
    if (shadowMode) log("credence-openclaw: SHADOW MODE — observing only, never enforcing");
    if (hardBlock) log("credence-openclaw: hardBlock ON — blocks are non-overridable denials");

    api.on("before_tool_call", gov.beforeToolCall, {
      priority: 100,
      timeoutMs: hookTimeoutMs + 1_000,
    });
    api.on("after_tool_call", gov.afterToolCall);

    // Per-turn cost REQUIRES plugins.entries.credence-openclaw.hooks
    // .allowConversationAccess: true. Wrapped so a blocked registration
    // never breaks governance — cost is just absent.
    try {
      api.on("llm_output", gov.llmOutput);
    } catch (err) {
      log(
        "credence-openclaw: llm_output hook unavailable (set hooks.allowConversationAccess:true for the cost signal)",
        err,
      );
    }

    // Model routing — ON by default, roster-aware. The body discovered the user's models from
    // config; route only when ≥2 are priceable (else OpenClaw keeps its model — a no-op, so
    // single-model installs and undiscoverable rosters are unaffected). Set `routing: false` to
    // disable. Fails open: daemon down / slow ⇒ OpenClaw's model.
    if (routingActive) {
      try {
        api.on("before_model_resolve", gov.beforeModelResolve, {
          priority: 100,
          timeoutMs: hookTimeoutMs + 1_000,
        });
        log(
          `credence-openclaw: model routing ACTIVE over ${roster.length} models ` +
            `(${roster.map((m) => m.model).join(", ")})`,
        );
      } catch (err) {
        log(
          "credence-openclaw: before_model_resolve hook unavailable on this host; routing disabled",
          err,
        );
      }
    } else if (routingEnabled) {
      log(
        `credence-openclaw: routing enabled but ${roster.length} priceable model(s) discovered ` +
          `(need ≥2); routing inactive — keeping OpenClaw's model`,
      );
    }

    // In-session VALUE SUMMARY: on cleanup (session end / reload), fetch the daemon's report
    // and log a one-line "what credence-openclaw did for you" — so the user SEES the value without a
    // manual CLI (the trust/tune loop). Best-effort + fail-open: a down daemon / bad response is
    // silently skipped, and it never throws on the cleanup path. Inline fetch (the shared
    // daemon-client stays verbatim — this is a read-only display call, not the core wire).
    async function logSessionSummary(): Promise<void> {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 2_000);
        const res = await fetch(`${daemonUrl.replace(/\/+$/, "")}/report`, { signal: ctrl.signal });
        clearTimeout(t);
        if (!res.ok) return;
        const r = (await res.json()) as Record<string, number>;
        const n = (k: string) => (typeof r[k] === "number" ? r[k] : 0);
        if (n("total_events") === 0) return;
        log(
          `credence-openclaw: this run — spend $${n("total_usd").toFixed(4)}; ` +
            `blocked ${n("prevented_calls")} waste call(s) (~$${n("estimated_prevented_usd").toFixed(4)} saved, est.); ` +
            `asked ${n("decided_ask")}, you denied ${n("denied")}. Full report: GET ${daemonUrl}/report`,
        );
        // Shadow mode: nothing was enforced, so report the counterfactual
        // separately — what governance WOULD have blocked, and the false-block
        // proxy split (write/edit=mutation vs not; bash ambiguous → counted as
        // a candidate re-run). Only shown when there were would-blocks.
        if (n("would_block_calls") > 0) {
          log(
            `credence-openclaw[shadow]: would have blocked ${n("would_block_calls")} call(s) ` +
              `(~$${n("estimated_counterfactual_usd").toFixed(4)} would-be-saved, est.) — NOT enforced; ` +
              `~${n("would_block_likely_waste")} look like waste, ` +
              `${n("would_block_candidate_legitimate")} like legitimate re-runs (proxy)`,
          );
        }
      } catch {
        /* best-effort display; never throws on cleanup */
      }
    }

    // Close the SSE stream + drain awaiters on reset/delete/reload so a
    // hot-reload does not accumulate daemon connections. Optional-chained
    // for hosts predating the lifecycle API.
    try {
      api.lifecycle?.registerRuntimeLifecycle?.({
        id: "credence-openclaw-governor",
        description:
          "Close the credence-openclaw daemon SSE stream and drain pending tool-call awaiters.",
        cleanup: () => {
          void logSessionSummary(); // fire-and-forget value summary
          gov.cleanup();
        },
      });
    } catch (err) {
      log("credence-openclaw: could not register lifecycle cleanup", err);
    }

    // Proactively tell the operator if the daemon is down (governance/routing are a silent
    // fail-open no-op without it) with the start command — and auto-start it only if they
    // opted in. Fire-and-forget: never delays plugin load, never throws (fail-open).
    void runStartupDaemonCheck(daemonUrl, autostartDaemon, log);
  },
};

export default plugin;
