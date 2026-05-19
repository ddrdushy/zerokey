// Phase 4 of DESKTOP_PIVOT_PLAN.md — Electron-side entitlement
// verification.
//
// Mirror of desktop/sidecar/zk_desktop/entitlement_verify.py in JS,
// using Node's built-in crypto for Ed25519. The wire format is the
// SAME as the sidecar:
//
//     <b64url(payload_json)> . <b64url(signature)>
//
// where payload_json is canonical JSON (sorted keys, no whitespace).
//
// Why we verify here too, not just on the sidecar:
//   - The Electron main process makes the heartbeat call, caches the
//     entitlement, and decides whether to surface a "read-only" /
//     "expiring soon" banner. It needs to trust the entitlement
//     before reading expires_at, status, plan, etc.
//   - Defence in depth: even if an attacker poisons the keytar entry,
//     the main process refuses to honour a forged blob.
//
// The public key is pinned via env in dev
// (ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM); Phase 5 will embed it at
// electron-builder time so a tampered binary can't trust an
// attacker-signed entitlement.

const crypto = require("node:crypto");

class EntitlementError extends Error {}

function getPublicKey() {
  const pem = process.env.ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM || "";
  if (!pem) {
    throw new EntitlementError(
      "ZK_DESKTOP_LICENSING_PUBLIC_KEY_PEM is not set. The desktop " +
        "needs the cloud's Ed25519 public key to verify entitlements.",
    );
  }
  // node's crypto can load PEMs directly; no PEM-parsing dance.
  return crypto.createPublicKey(pem);
}

function b64urlDecode(data) {
  const pad = "=".repeat((4 - (data.length % 4)) % 4);
  const b64 = (data + pad).replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(b64, "base64");
}

/**
 * Verify a wire-format entitlement and return its parsed payload.
 * Throws EntitlementError on any failure.
 *
 * @param {string} wire
 * @returns {{
 *   license_id: string,
 *   organization_tin: string,
 *   organization_legal_name: string,
 *   plan: string,
 *   status: "active"|"suspended"|"revoked"|"expired",
 *   features: string[],
 *   signing_modes_allowed: string[],
 *   issued_at: string,
 *   expires_at: string,
 *   machine_fingerprint_hash: string
 * }}
 */
function verify(wire) {
  if (!wire || !wire.includes(".")) {
    throw new EntitlementError("Malformed entitlement (missing '.')");
  }
  const [b64Payload, b64Sig] = wire.split(".", 2);
  const payloadBytes = b64urlDecode(b64Payload);
  const sig = b64urlDecode(b64Sig);

  const pub = getPublicKey();
  // Ed25519 in node: pass null for the digest algorithm — Ed25519 is
  // its own hash. The signature is over the raw payload bytes.
  const ok = crypto.verify(null, payloadBytes, pub, sig);
  if (!ok) throw new EntitlementError("Entitlement signature invalid");

  let payload;
  try {
    payload = JSON.parse(payloadBytes.toString("utf-8"));
  } catch (err) {
    throw new EntitlementError(`Entitlement payload not valid JSON: ${err.message}`);
  }

  // Light shape validation. The cloud is the source of truth for the
  // full schema; we just refuse anything we can't make sense of.
  for (const key of [
    "license_id",
    "organization_tin",
    "organization_legal_name",
    "plan",
    "status",
    "issued_at",
    "expires_at",
  ]) {
    if (typeof payload[key] !== "string" || payload[key].length === 0) {
      throw new EntitlementError(`Entitlement payload missing field: ${key}`);
    }
  }
  return payload;
}

/**
 * Classify a verified entitlement into a policy state the UI can act on.
 * Returns one of:
 *   { state: "active",        daysRemaining: number }
 *   { state: "expiring_soon", daysRemaining: number }   // ≤ 7 days
 *   { state: "read_only",     daysOverdue: number }     // expired
 *   { state: "blocked",       reason: "revoked"|"suspended" }
 */
function policyFor(payload) {
  if (payload.status === "revoked") {
    return { state: "blocked", reason: "revoked" };
  }
  if (payload.status === "suspended") {
    return { state: "blocked", reason: "suspended" };
  }
  const expires = Date.parse(payload.expires_at);
  if (Number.isNaN(expires)) {
    return { state: "blocked", reason: "invalid_expiry" };
  }
  const now = Date.now();
  const dayMs = 86_400_000;
  if (expires < now) {
    return { state: "read_only", daysOverdue: Math.ceil((now - expires) / dayMs) };
  }
  const daysRemaining = Math.ceil((expires - now) / dayMs);
  if (daysRemaining <= 7) return { state: "expiring_soon", daysRemaining };
  return { state: "active", daysRemaining };
}

module.exports = { verify, policyFor, EntitlementError };
