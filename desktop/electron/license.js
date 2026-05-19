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

const entitlement = require("./entitlement");

const SERVICE = "ZeroKey";
const ACCOUNT = "entitlement";
const HEARTBEAT_ACCOUNT = "heartbeat_state";

const API_BASE =
  process.env.ZK_LICENSE_API_BASE || "https://zerokey.symprio.com";

async function getCachedEntitlement() {
  const raw = await keytar.getPassword(SERVICE, ACCOUNT);
  if (!raw) return null;
  let record;
  try {
    record = JSON.parse(raw);
  } catch {
    await keytar.deletePassword(SERVICE, ACCOUNT);
    return null;
  }
  // Phase 4: verify the wire-format signature against the embedded
  // public key BEFORE returning. A tampered keytar entry (or one
  // signed by a key we don't trust) is treated as if no license is
  // cached — the user lands on the activation screen.
  if (!record.entitlement) {
    return null;
  }
  try {
    record._payload = entitlement.verify(record.entitlement);
    record._policy = entitlement.policyFor(record._payload);
  } catch (err) {
    // Keep the record but flag it. main.js reads _policy to surface
    // a banner. Don't clear it automatically — preserve the user's
    // ability to see what we won't honour.
    record._payload = null;
    record._policy = { state: "blocked", reason: "untrusted_signature" };
  }
  return record;
}

async function setCachedEntitlement(record) {
  // Strip any derived fields (_payload, _policy) so we only persist
  // the cloud's response shape.
  const persistable = {
    license_id: record.license_id,
    organization_legal_name: record.organization_legal_name,
    plan: record.plan,
    status: record.status,
    expires_at: record.expires_at,
    entitlement: record.entitlement,
  };
  await keytar.setPassword(SERVICE, ACCOUNT, JSON.stringify(persistable));
}

async function clearCachedEntitlement() {
  await keytar.deletePassword(SERVICE, ACCOUNT);
  await keytar.deletePassword(SERVICE, HEARTBEAT_ACCOUNT);
}

// --- Heartbeat-failure tracking --------------------------------------------
//
// Phase 4: track consecutive heartbeat failures so the UI can surface
// "haven't reached the cloud in N days — N more until read-only".

async function getHeartbeatState() {
  const raw = await keytar.getPassword(SERVICE, HEARTBEAT_ACCOUNT);
  if (!raw) {
    return { lastSuccessAt: null, consecutiveFailures: 0, lastError: "" };
  }
  try {
    return JSON.parse(raw);
  } catch {
    return { lastSuccessAt: null, consecutiveFailures: 0, lastError: "" };
  }
}

async function recordHeartbeatSuccess() {
  await keytar.setPassword(
    SERVICE,
    HEARTBEAT_ACCOUNT,
    JSON.stringify({
      lastSuccessAt: new Date().toISOString(),
      consecutiveFailures: 0,
      lastError: "",
    }),
  );
}

async function recordHeartbeatFailure(message) {
  const cur = await getHeartbeatState();
  await keytar.setPassword(
    SERVICE,
    HEARTBEAT_ACCOUNT,
    JSON.stringify({
      lastSuccessAt: cur.lastSuccessAt,
      consecutiveFailures: (cur.consecutiveFailures || 0) + 1,
      lastError: String(message || "unknown"),
    }),
  );
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
  getHeartbeatState,
  recordHeartbeatSuccess,
  recordHeartbeatFailure,
};
