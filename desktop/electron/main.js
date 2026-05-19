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
    // eslint-disable-next-line no-console
    console.log("[zerokey] heartbeat ok");
  } catch (err) {
    // Offline grace: a single failed heartbeat doesn't change behaviour.
    // Phase 4 will track consecutive failures and surface a banner.
    // eslint-disable-next-line no-console
    console.warn("[zerokey] heartbeat failed:", err.message || err);
  }
}

// --- IPC surface (called from preload.js) ----------------------------------

ipcMain.handle("license:get", async () => {
  return await getCachedEntitlement();
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
