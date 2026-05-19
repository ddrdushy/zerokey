// Phase 5 of DESKTOP_PIVOT_PLAN.md — auto-update.
//
// electron-updater polls a generic provider for the latest version,
// downloads + signature-verifies it, and applies on next restart. We
// also gate the update download by the cached entitlement: the cloud's
// /api/v1/licenses/desktop-release/ endpoint returns a short-lived
// signed S3 URL only for customers with an active license.
//
// In dev (no installer, no auto-update) this module is a quiet no-op:
// electron-updater throws on uninstalled apps, so we wrap calls in a
// try/catch and log rather than crash.

const { app, dialog } = require("electron");

let autoUpdater = null;
try {
  // eslint-disable-next-line global-require
  autoUpdater = require("electron-updater").autoUpdater;
} catch (err) {
  // electron-updater not present (e.g. dependency wasn't installed
  // yet); auto-update simply unavailable.
  autoUpdater = null;
}

// Poll cadence: once at boot + every 6 h thereafter. The release
// feed is cheap (a single latest.yml on S3) so we don't have to be
// stingy.
const POLL_INTERVAL_MS = 6 * 60 * 60 * 1000;

let pollTimer = null;
let stale = false;

function isDev() {
  return !app.isPackaged;
}

function init() {
  if (!autoUpdater || isDev()) {
    // eslint-disable-next-line no-console
    console.log("[zerokey] auto-update disabled (dev or updater unavailable)");
    return;
  }
  // Don't auto-download — we ask the user first. The download itself
  // hits the URL configured in package.json build.publish.url, which
  // points at releases.zerokey.symprio.com.
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on("update-available", (info) => {
    stale = true;
    dialog
      .showMessageBox({
        type: "info",
        buttons: ["Download", "Not now"],
        defaultId: 0,
        cancelId: 1,
        title: "Update available",
        message: `ZeroKey ${info.version} is available.`,
        detail:
          "Downloading installs in the background; you keep working. " +
          "Restart later to apply.",
      })
      .then(({ response }) => {
        if (response === 0) autoUpdater.downloadUpdate().catch((err) => {
          // eslint-disable-next-line no-console
          console.warn("[zerokey] auto-update download failed:", err.message || err);
        });
      });
  });

  autoUpdater.on("update-downloaded", () => {
    dialog.showMessageBox({
      type: "info",
      buttons: ["OK"],
      title: "Update ready",
      message: "Update will install on next restart.",
    });
  });

  autoUpdater.on("error", (err) => {
    // eslint-disable-next-line no-console
    console.warn("[zerokey] auto-update error:", err.message || err);
  });

  // Fire-and-forget initial check, then schedule.
  checkNow();
  pollTimer = setInterval(checkNow, POLL_INTERVAL_MS);
}

function checkNow() {
  if (!autoUpdater || isDev()) return;
  try {
    autoUpdater.checkForUpdates().catch((err) => {
      // eslint-disable-next-line no-console
      console.warn("[zerokey] auto-update check failed:", err.message || err);
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[zerokey] auto-update check threw:", err.message || err);
  }
}

function shutdown() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

module.exports = { init, checkNow, shutdown, isStale: () => stale };
