// License + entitlement store, backed by the OS keychain via keytar.
//
// We store one record per install (single tenant per machine in v1).
// The record is the JSON the cloud returned from /validate or
// /heartbeat: license_id, plan, status, expires_at, entitlement
// (the signed wire blob).
//
// Phase 4 will:
//   - Verify the entitlement's Ed25519 signature against the embedded
//     public key BEFORE trusting it.
//   - Track consecutive heartbeat failures and surface a banner.
//   - Drop to read-only when expires_at < now.

const os = require("node:os");
const crypto = require("node:crypto");
const keytar = require("keytar");
const { app } = require("electron");

const SERVICE = "ZeroKey";
const ACCOUNT = "entitlement";

const API_BASE =
  process.env.ZK_LICENSE_API_BASE || "https://zerokey.symprio.com";

async function getCachedEntitlement() {
  const raw = await keytar.getPassword(SERVICE, ACCOUNT);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // Corrupt entry — clear it so we don't trap the user.
    await keytar.deletePassword(SERVICE, ACCOUNT);
    return null;
  }
}

async function setCachedEntitlement(record) {
  await keytar.setPassword(SERVICE, ACCOUNT, JSON.stringify(record));
}

async function clearCachedEntitlement() {
  await keytar.deletePassword(SERVICE, ACCOUNT);
}

// Hash machine identifiers so we never send raw hostname / MAC over
// the wire. The cloud only ever stores the hash.
function machineFingerprint() {
  const parts = [
    os.hostname() || "",
    os.platform(),
    os.arch(),
    os.userInfo().username || "",
  ];
  // Try the OS network interfaces for a stable MAC. Best-effort —
  // missing on hardened VMs.
  try {
    const ifaces = os.networkInterfaces();
    for (const list of Object.values(ifaces)) {
      for (const iface of list || []) {
        if (iface.mac && iface.mac !== "00:00:00:00:00:00") {
          parts.push(iface.mac);
          break;
        }
      }
    }
  } catch {
    /* ignore */
  }
  return crypto.createHash("sha256").update(parts.join("|")).digest("hex");
}

function desktopVersion() {
  try {
    return app.getVersion();
  } catch {
    return "0.0.0-dev";
  }
}

async function validateLicenseKey({ key, fingerprint, version }) {
  const res = await fetch(`${API_BASE}/api/v1/licenses/validate/`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      key,
      machine_fingerprint: fingerprint,
      desktop_version: version,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail || `HTTP ${res.status}`;
    const err = new Error(detail);
    err.code = body.code;
    err.status = res.status;
    throw err;
  }
  return body;
}

async function heartbeatLicense({ licenseId, fingerprint, version }) {
  const res = await fetch(`${API_BASE}/api/v1/licenses/heartbeat/`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      license_id: licenseId,
      machine_fingerprint: fingerprint,
      desktop_version: version,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.detail || `HTTP ${res.status}`);
    err.code = body.code;
    err.status = res.status;
    throw err;
  }
  return body;
}

module.exports = {
  getCachedEntitlement,
  setCachedEntitlement,
  clearCachedEntitlement,
  validateLicenseKey,
  heartbeatLicense,
  machineFingerprint,
  desktopVersion,
};
