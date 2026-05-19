// Spawns + supervises the Python sidecar.
//
// In dev: invokes `python desktop/sidecar/run_sidecar.py --port <p>`.
// In a packaged build (Phase 5): invokes the PyInstaller-built binary
// shipped under `resources/sidecar/zk-sidecar(.exe)`.
//
// Sidecar contract:
//   - It listens on the port we hand it via --port.
//   - It exposes /healthz returning {"status":"ok"} when ready.
//   - Phase 3 adds the rest of the API surface.

const { spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");

const SIDECAR_BOOT_TIMEOUT_MS = 15_000;
const SIDECAR_POLL_INTERVAL_MS = 200;

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHealthz(port) {
  const deadline = Date.now() + SIDECAR_BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/healthz`, {
        signal: AbortSignal.timeout(500),
      });
      if (res.ok) return true;
    } catch {
      // Not up yet; loop.
    }
    await new Promise((r) => setTimeout(r, SIDECAR_POLL_INTERVAL_MS));
  }
  throw new Error("Sidecar did not become healthy within timeout");
}

function resolveSidecarCommand() {
  // In dev we run the Python script directly. Phase 5 swaps this to
  // the PyInstaller-built binary path under resources/sidecar/.
  const python = process.env.ZK_SIDECAR_PYTHON || "python3";
  const script = path.join(__dirname, "..", "sidecar", "run_sidecar.py");
  return { cmd: python, args: [script] };
}

async function startSidecar() {
  const port = await findFreePort();
  const { cmd, args } = resolveSidecarCommand();
  const fullArgs = [...args, "--port", String(port)];

  // eslint-disable-next-line no-console
  console.log(`[zerokey] launching sidecar: ${cmd} ${fullArgs.join(" ")}`);
  const child = spawn(cmd, fullArgs, {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ZK_SIDECAR_PORT: String(port) },
  });

  child.stdout.on("data", (chunk) => {
    process.stdout.write(`[sidecar] ${chunk}`);
  });
  child.stderr.on("data", (chunk) => {
    process.stderr.write(`[sidecar:err] ${chunk}`);
  });

  const handle = { child, port, stopped: false };
  child.on("exit", (code, signal) => {
    handle.stopped = true;
    // eslint-disable-next-line no-console
    console.log(`[zerokey] sidecar exited code=${code} signal=${signal}`);
  });

  try {
    await waitForHealthz(port);
  } catch (err) {
    // Sidecar failed to boot — kill it so we don't leak a process.
    try {
      child.kill("SIGTERM");
    } catch {
      /* best effort */
    }
    throw err;
  }
  return handle;
}

function stopSidecar(handle) {
  return new Promise((resolve) => {
    if (!handle || handle.stopped) {
      resolve();
      return;
    }
    const finish = () => {
      handle.stopped = true;
      resolve();
    };
    handle.child.once("exit", finish);
    try {
      handle.child.kill("SIGTERM");
    } catch {
      finish();
      return;
    }
    // Hard kill if it ignores SIGTERM for 3s.
    setTimeout(() => {
      if (!handle.stopped) {
        try {
          handle.child.kill("SIGKILL");
        } catch {
          /* ignore */
        }
        finish();
      }
    }, 3000);
  });
}

module.exports = { startSidecar, stopSidecar };
