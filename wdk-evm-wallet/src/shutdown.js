// Coordinates an orderly shutdown: stop accepting connections, let in-flight
// requests finish, then exit. Vault writes are not atomic (see local_vault.js),
// so an abrupt exit mid-write can truncate a wallet file. Every dependency is
// injectable so the drain loop can be tested without real timers.
export function createShutdownCoordinator({
  closeServer,
  exit,
  now = () => Date.now(),
  schedule = (fn, ms) => setTimeout(fn, ms),
  graceMs = 8000,
  pollMs = 100,
  log = () => {},
}) {
  let inFlight = 0;
  let shuttingDown = false;

  function begin(signalName) {
    if (shuttingDown) return;
    shuttingDown = true;
    log(
      `wdk-evm-wallet received ${signalName}, draining ${inFlight} in-flight request(s)`,
    );
    closeServer();

    const deadline = now() + graceMs;
    const tick = () => {
      if (inFlight <= 0 || now() >= deadline) {
        exit(0);
        return;
      }
      schedule(tick, pollMs);
    };
    tick();
  }

  return {
    begin,
    trackStart() {
      inFlight += 1;
    },
    trackEnd() {
      if (inFlight > 0) inFlight -= 1;
    },
    isShuttingDown() {
      return shuttingDown;
    },
    get inFlight() {
      return inFlight;
    },
  };
}

// Track the lifetime of the handler itself, not the HTTP connection. A client
// can disconnect while a vault write or transaction is still running, and the
// response "close" event must not make shutdown treat that work as finished.
export async function withTrackedRequest(coordinator, handler) {
  coordinator.trackStart();
  try {
    return await handler();
  } finally {
    coordinator.trackEnd();
  }
}
