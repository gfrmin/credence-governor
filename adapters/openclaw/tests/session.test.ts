import { test } from "node:test";
import assert from "node:assert/strict";

import { SessionTracker } from "../src/session.js";
import type { BeforeToolCallEvent, ToolContext } from "../src/openclaw-types.js";

// The heavy extraction parity (bucketing, fingerprints, taint-flow) is asserted in the
// Python parity tests (governor-core) — extraction is single-sourced there now. These
// tests cover only the body's remaining job: building the neutral message buffer with the
// "priors only" + "results-as-taint-source" contracts the daemon's extractors depend on.

const ctx: ToolContext = { runId: "r1", workspaceDir: "/proj" };
const ev = (toolName: string, over: Partial<BeforeToolCallEvent> = {}): BeforeToolCallEvent => ({
  toolName,
  params: { command: "x" },
  ...over,
});

test("snapshot excludes the proposed call; the NEXT snapshot sees it as a prior", () => {
  const s = new SessionTracker();
  const first = s.snapshot(ev("bash", { params: { command: "ls" } }), ctx);
  // First call has no priors.
  assert.deepEqual(first.session.messages, []);
  assert.equal(first.tool_name, "bash");
  assert.deepEqual(first.input, { command: "ls" });

  const second = s.snapshot(ev("bash", { params: { command: "pwd" } }), ctx);
  // The first call is now a prior tool_call; the second (current) is NOT present.
  const calls = second.session.messages.filter((m) => m.role === "tool_call");
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].input, { command: "ls" });
});

test("recordResult appends a tool_result (the taint source); empties are skipped", () => {
  const s = new SessionTracker();
  s.recordResult({ toolName: "read", params: {}, result: "secret@evil.com" }, ctx);
  s.recordResult({ toolName: "read", params: {}, result: "" }, ctx); // skipped
  const req = s.snapshot(ev("bash"), ctx);
  const results = req.session.messages.filter((m) => m.role === "tool_result");
  assert.equal(results.length, 1);
  assert.match(results[0].result ?? "", /evil\.com/);
});

test("cwd is the tool's first derived path; project_root is the workspace; pathless → ''", () => {
  const s = new SessionTracker();
  const withPath = s.snapshot(ev("read", { derivedPaths: ["/proj/src/a.ts"] }), ctx);
  assert.equal(withPath.session.cwd, "/proj/src/a.ts");
  assert.equal(withPath.session.project_root, "/proj");

  const pathless = s.snapshot(ev("bash"), ctx);
  assert.equal(pathless.session.cwd, ""); // → daemon buckets "no-path"
});

test("runs are isolated by runKey; clearRun drops a buffer", () => {
  const s = new SessionTracker();
  s.snapshot(ev("bash"), { runId: "a" });
  s.snapshot(ev("bash"), { runId: "b" });
  assert.equal(s.runCount(), 2);
  s.clearRun({ runId: "a" });
  assert.equal(s.runCount(), 1);
});
