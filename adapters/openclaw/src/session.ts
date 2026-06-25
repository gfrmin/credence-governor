// session.ts — the body's per-run MESSAGE BUFFER.
//
// Replaces the old client-side FeatureTracker + SafetyTracker. Feature & taint
// extraction now lives SERVER-SIDE in the governor daemon (single-sourced in
// credence-governor-core's Python extractors), so the body's only job is to maintain
// the harness-neutral message history the daemon extracts from — the SAME
// `session.messages` shape the Claude Code adapter builds from its transcript. OpenClaw
// has no transcript file, so we accumulate it here from before/after_tool_call.
//
// Two contracts the server-side extractors depend on (mirrored from the Python side):
//   • the PROPOSED call is NOT in the snapshot — repetition/identical-call count PRIOR
//     calls only. snapshot() returns the buffer-before, then records the current call.
//   • tool RESULTS are the taint SOURCE — recordResult() appends them so a later sink
//     carrying their tokens is flagged (causal: only results seen before a call taint it).

import type {
  AfterToolCallEvent,
  BeforeToolCallEvent,
  ToolContext,
} from "./openclaw-types.js";

// ~200 call/result pairs — keeps the session-wide identical-call window meaningful
// while bounding memory on long-running agents.
const HISTORY_CAP = 400;

export interface WireMessage {
  role: "user" | "assistant" | "tool_call" | "tool_result";
  tool_name?: string;
  input?: unknown;
  timestamp?: string;
  result?: string;
}

export interface WireSession {
  cwd: string;
  project_root: string;
  messages: WireMessage[];
}

export interface DecisionRequest {
  tool_name: string;
  input: unknown;
  session: WireSession;
}

interface RunState {
  messages: WireMessage[];
}

function runKey(ctx: ToolContext): string {
  return ctx.runId ?? ctx.sessionKey ?? ctx.sessionId ?? "default";
}

function resultToText(result: unknown): string {
  if (result == null) return "";
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result);
  } catch {
    return String(result);
  }
}

// cwd for a tool call = the path it operates on (its first derived path), classified
// server-side against project_root (= the workspace dir): a path inside the workspace
// buckets to project-root/subdirectory, one outside to outside-project, and a pathless
// tool (bare bash) to no-path. Single-path: a multi-path tool straddling the boundary is
// classified by its first path — best-effort, matching the pre-refactor behaviour.
function callCwd(event: BeforeToolCallEvent): string {
  const paths = event.derivedPaths ?? [];
  return paths.length > 0 ? paths[0] : "";
}

export class SessionTracker {
  private runs = new Map<string, RunState>();

  private state(ctx: ToolContext): RunState {
    const k = runKey(ctx);
    let s = this.runs.get(k);
    if (!s) {
      s = { messages: [] };
      this.runs.set(k, s);
    }
    return s;
  }

  private push(ctx: ToolContext, m: WireMessage): void {
    const s = this.state(ctx);
    s.messages.push(m);
    if (s.messages.length > HISTORY_CAP) s.messages.shift();
  }

  /** Best-effort user-message marker (drives time-since-last-user-message). Unwired
   *  today — OpenClaw exposes no user-message hook — kept for when one lands. */
  markUserMessage(ctx: ToolContext, ts: string = new Date().toISOString()): void {
    this.push(ctx, { role: "user", timestamp: ts });
  }

  /** Record a tool RESULT (the taint source). Empty results are skipped — they carry
   *  no tokens and only bloat the buffer. */
  recordResult(event: AfterToolCallEvent, ctx: ToolContext): void {
    const text = resultToText(event.result);
    if (!text) return;
    this.push(ctx, {
      role: "tool_result",
      result: text,
      timestamp: new Date().toISOString(),
    });
  }

  /** Snapshot the decision request for a proposed call (PRIOR messages only), THEN
   *  record the call so the next snapshot sees it as a prior. */
  snapshot(event: BeforeToolCallEvent, ctx: ToolContext): DecisionRequest {
    const s = this.state(ctx);
    const req: DecisionRequest = {
      tool_name: event.toolName,
      input: event.params,
      session: {
        cwd: callCwd(event),
        project_root: ctx.workspaceDir ?? "",
        messages: [...s.messages],
      },
    };
    this.push(ctx, {
      role: "tool_call",
      tool_name: event.toolName,
      input: event.params,
      timestamp: new Date().toISOString(),
    });
    return req;
  }

  /** Drop a run's buffer (call on agent_end to bound memory). */
  clearRun(ctx: ToolContext): void {
    this.runs.delete(runKey(ctx));
  }

  /** Test/inspection accessor. */
  runCount(): number {
    return this.runs.size;
  }
}
