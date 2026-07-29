import test from "node:test";
import assert from "node:assert/strict";

import { createShutdownCoordinator, withTrackedRequest } from "../src/shutdown.js";

function harness({ graceMs = 8000 } = {}) {
  const state = { closed: 0, exitCode: null, clock: 0, pending: [] };
  const coordinator = createShutdownCoordinator({
    closeServer: () => { state.closed += 1; },
    exit: (code) => { state.exitCode = code; },
    now: () => state.clock,
    schedule: (fn) => { state.pending.push(fn); },
    graceMs,
    pollMs: 100,
  });
  state.flush = () => {
    const queued = state.pending.splice(0, state.pending.length);
    for (const fn of queued) fn();
  };
  return { state, coordinator };
}

test("exits immediately when nothing is in flight", () => {
  const { state, coordinator } = harness();
  coordinator.begin("SIGTERM");
  assert.equal(state.closed, 1);
  assert.equal(state.exitCode, 0);
});

test("waits for an in-flight request before exiting", () => {
  const { state, coordinator } = harness();
  coordinator.trackStart();
  coordinator.begin("SIGTERM");
  assert.equal(state.exitCode, null, "must not exit while a request is in flight");

  coordinator.trackEnd();
  state.flush();
  assert.equal(state.exitCode, 0);
});

test("exits once the grace deadline passes even with work in flight", () => {
  const { state, coordinator } = harness({ graceMs: 8000 });
  coordinator.trackStart();
  coordinator.begin("SIGTERM");
  assert.equal(state.exitCode, null);

  state.clock = 8000;
  state.flush();
  assert.equal(state.exitCode, 0);
});

test("a second signal does not restart the drain", () => {
  const { state, coordinator } = harness();
  coordinator.trackStart();
  coordinator.begin("SIGTERM");
  coordinator.begin("SIGINT");
  assert.equal(state.closed, 1);
  assert.equal(coordinator.isShuttingDown(), true);
});

test("trackEnd never drives the counter negative", () => {
  const { coordinator } = harness();
  coordinator.trackEnd();
  coordinator.trackEnd();
  assert.equal(coordinator.inFlight, 0);
});

test("request tracking lasts until the handler settles", async () => {
  const { coordinator } = harness();
  let finish;
  const pending = new Promise((resolve) => {
    finish = resolve;
  });
  const tracked = withTrackedRequest(coordinator, () => pending);
  assert.equal(coordinator.inFlight, 1);

  finish("done");
  assert.equal(await tracked, "done");
  assert.equal(coordinator.inFlight, 0);
});

test("request tracking ends even when the handler rejects", async () => {
  const { coordinator } = harness();
  await assert.rejects(
    withTrackedRequest(coordinator, async () => {
      throw new Error("request failed");
    }),
    /request failed/,
  );
  assert.equal(coordinator.inFlight, 0);
});
