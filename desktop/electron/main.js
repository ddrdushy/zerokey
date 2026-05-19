// Phase 2 of DESKTOP_PIVOT_PLAN.md — Electron main process.
//
// Lifecycle:
//   1. App ready  → spawn the Python sidecar, wait for /healthz.
//   2. Read the cached entitlement from keytar. If present + valid,
//      load main.html. Otherwise load activate.html.
//   3. Schedule the 24h license-heartbeat ticker. First fire happens
//      300 ms after window-loaded so we don't compete with first paint.
//   4. On quit → kill the sidecar cleanly.
//
// Phase 4 will tighten the entitlement check (verify the Ed25519
// signature against the embedded public key; flip to read-only when
// expired). For Phase 2 we only check "is there a cached entitlement
// at all" — enough to exercise the activation flow end-to-end.

const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("node:path");

const { startSidecar, stopSidecar } = require("./sidecar");
const {
  getCachedEntitlement,
  setCachedEntitlement,
  clearCachedEntitlement,
  validateLicenseKey,
  heartbeatLicense,
  machineFingerprint,
  desktopVersion,
  getHeartbeatState,
  recordHeartbeatSuccess,
  recordHeartbeatFailure,
} = require("./license");

const HEARTBEAT_INTERVAL_MS = 24 * 60 * 60 * 1000;

let mainWindow = null;
let heartbeatTimer = null;
let sidecarHandle = null;

function createWindow(initialFile) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: "#FBFAF7",
    title: "ZeroKey",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false, // we expose a tiny IPC surface from preload
    },
  });
  mainWindow.loadFile(path.join(__dirname, "..", "renderer", initialFile));
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // External links open in the OS browser, not inside Electron.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

async function bootstrap() {
  try {
    sidecarHandle = await startSidecar();
    // eslint-disable-next-line no-console
    console.log(`[zerokey] sidecar up on http://127.0.0.1:${sidecarHandle.port}`);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.error("[zerokey] sidecar failed to start:", err);
    // Don't crash — activation can still happen without the sidecar;
    // the main UI will surface the failure on first interaction.
  }

  const entitlement = await getCachedEntitlement();
  const initial = entitlement ? "main.html" : "activate.html";
  createWindow(initial);
  scheduleHeartbeat();
}

function scheduleHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(runHeartbeat, HEARTBEAT_INTERVAL_MS);
  // First tick a few hundred ms after boot so we don't fight first paint.
  setTimeout(runHeartbeat, 300);
}

async function runHeartbeat() {
  const cached = await getCachedEntitlement();
  if (!cached) return; // not activated yet; nothing to heartbeat.
  try {
    const result = await heartbeatLicense({
      licenseId: cached.license_id,
      fingerprint: machineFingerprint(),
      version: desktopVersion(),
    });
    await setCachedEntitlement(result);
    await recordHeartbeatSuccess();
    // eslint-disable-next-line no-console
    console.log("[zerokey] heartbeat ok");
  } catch (err) {
    await recordHeartbeatFailure(err.message || String(err));
    // Offline grace: a single failure is OK. Phase 4 surfaces the
    // consecutive-failure count to the renderer banner.
    // eslint-disable-next-line no-console
    console.warn("[zerokey] heartbeat failed:", err.message || err);
  }
}

// --- IPC surface (called from preload.js) ----------------------------------

ipcMain.handle("license:get", async () => {
  return await getCachedEntitlement();
});

ipcMain.handle("license:status", async () => {
  // Composite shape for the renderer banner: trust state, calendar
  // state, heartbeat state. Renderer formats; main just reports.
  const cached = await getCachedEntitlement();
  const hb = await getHeartbeatState();
  if (!cached) {
    return { activated: false, policy: null, heartbeat: hb };
  }
  return {
    activated: true,
    license_id: cached.license_id,
    organization_legal_name: cached.organization_legal_name,
    plan: cached.plan,
    status: cached.status,
    expires_at: cached.expires_at,
    policy: cached._policy || null,
    heartbeat: hb,
  };
});

ipcMain.handle("license:activate", async (_event, key) => {
  const result = await validateLicenseKey({
    key,
    fingerprint: machineFingerprint(),
    version: desktopVersion(),
  });
  await setCachedEntitlement(result);
  return result;
});

ipcMain.handle("license:signOut", async () => {
  await clearCachedEntitlement();
  return true;
});

ipcMain.handle("sidecar:url", () => {
  return sidecarHandle ? `http://127.0.0.1:${sidecarHandle.port}` : null;
});

// Phase 4 — sidecar HTTP proxy IPC.
//
// The renderer doesn't talk to the sidecar directly because doing so
// would require the renderer to handle the entitlement header itself
// (and have access to it — which we keep out of the renderer for
// XSS-defence reasons). Instead the renderer calls window.zk.fetch()
// here; we attach the cached entitlement and proxy to the sidecar.
//
// Read-only mode: if the cached entitlement's policy is "read_only"
// or "blocked", we reject any non-GET request before sending it.
ipcMain.handle("sidecar:fetch", async (_event, { path, method, body }) => {
  if (!sidecarHandle) {
    return { ok: false, status: 0, body: { detail: "Sidecar not running." } };
  }
  const cached = await getCachedEntitlement();
  if (!cached) {
    return { ok: false, status: 401, body: { detail: "Not activated." } };
  }
  const policy = cached._policy;
  const verb = String(method || "GET").toUpperCase();
  if (verb !== "GET" && policy && policy.state !== "active" && policy.state !== "expiring_soon") {
    return {
      ok: false,
      status: 403,
      body: {
        detail: `Desktop is in ${policy.state} mode — mutating requests are blocked.`,
        code: policy.state,
      },
    };
  }

  const url = `http://127.0.0.1:${sidecarHandle.port}${path}`;
  try {
    const res = await fetch(url, {
      method: verb,
      headers: {
        "content-type": "application/json",
        "x-zk-entitlement": cached.entitlement || "",
      },
      body: body && verb !== "GET" ? JSON.stringify(body) : undefined,
    });
    let responseBody;
    try {
      responseBody = await res.json();
    } catch {
      responseBody = { detail: `non-JSON response (status ${res.status})` };
    }
    return { ok: res.ok, status: res.status, body: responseBody };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      body: { detail: `Sidecar request failed: ${err.message || err}` },
    };
  }
});

ipcMain.handle("nav:toMain", () => {
  if (mainWindow) {
    mainWindow.loadFile(path.join(__dirname, "..", "renderer", "main.html"));
  }
});

ipcMain.handle("nav:toActivate", () => {
  if (mainWindow) {
    mainWindow.loadFile(path.join(__dirname, "..", "renderer", "activate.html"));
  }
});

// --- App lifecycle --------------------------------------------------------

app.whenReady().then(bootstrap);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) bootstrap();
});

app.on("before-quit", async (event) => {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  if (sidecarHandle && !sidecarHandle.stopped) {
    event.preventDefault();
    try {
      await stopSidecar(sidecarHandle);
    } finally {
      sidecarHandle = null;
      app.quit();
    }
  }
});
