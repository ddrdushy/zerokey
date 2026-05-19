// Main-screen logic. All HTTP goes through window.zk.fetch which
// proxies to the sidecar with the entitlement header attached.

const $ = (id) => document.getElementById(id);

function showBanner(kind, text) {
  const el = $("banner");
  el.className = `banner ${kind}`;
  el.textContent = text;
  el.hidden = false;
}

function hideBanner() {
  $("banner").hidden = true;
}

function bannerForPolicy(status) {
  if (!status || !status.policy) {
    hideBanner();
    return;
  }
  const p = status.policy;
  if (p.state === "active") {
    hideBanner();
    return;
  }
  if (p.state === "expiring_soon") {
    showBanner(
      "warning",
      `License expires in ${p.daysRemaining} day${p.daysRemaining === 1 ? "" : "s"}. Renew via your Symprio portal.`,
    );
    return;
  }
  if (p.state === "read_only") {
    showBanner(
      "error",
      `License expired ${p.daysOverdue} day${p.daysOverdue === 1 ? "" : "s"} ago — read-only mode. New invoices, signing and LHDN submission are blocked until you renew.`,
    );
    return;
  }
  if (p.state === "blocked") {
    showBanner(
      "error",
      `License is ${p.reason} — read-only mode. Contact Symprio support.`,
    );
    return;
  }
}

function formatRelative(iso) {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

async function loadStatus() {
  const status = await window.zk.licenseStatus();
  if (!status.activated) {
    // Shouldn't happen — main.js only runs once activation completed.
    // But if it does, kick back to activation.
    await window.zk.goToActivate();
    return;
  }
  $("topbar-org").textContent = status.organization_legal_name || "";
  $("topbar-plan").textContent = status.plan || "";
  $("sc-url").textContent = (await window.zk.sidecarUrl()) || "(not running)";
  $("sc-heartbeat").textContent = formatRelative(status.heartbeat.lastSuccessAt);
  $("sc-hb-fail").textContent = String(status.heartbeat.consecutiveFailures || 0);
  bannerForPolicy(status);
}

async function loadIdentity() {
  const r = await window.zk.fetch("/api/v1/identity/me/");
  if (!r.ok) {
    $("sc-me").textContent = `error: ${r.body.detail || r.status}`;
    return;
  }
  $("sc-me").textContent = r.body.email || "(unknown)";
}

async function loadInvoices() {
  const r = await window.zk.fetch("/api/v1/invoices/");
  const list = $("invoice-list");
  const meta = $("invoices-meta");
  if (!r.ok) {
    meta.textContent = `Failed to load invoices: ${r.body.detail || r.status}`;
    list.innerHTML = "";
    return;
  }
  const items = r.body.results || [];
  meta.textContent = `${items.length} invoice${items.length === 1 ? "" : "s"}`;
  if (items.length === 0) {
    list.innerHTML = '<li class="empty">No invoices yet.</li>';
    return;
  }
  list.innerHTML = "";
  for (const inv of items.slice(0, 50)) {
    const li = document.createElement("li");
    li.textContent = `${inv.invoice_number || inv.id} · ${inv.status || ""} · ${inv.grand_total || "0.00"}`;
    list.appendChild(li);
  }
}

async function init() {
  await loadStatus();
  await loadIdentity();
  await loadInvoices();
}

$("sign-out").addEventListener("click", async () => {
  await window.zk.signOut();
  await window.zk.goToActivate();
});

init().catch((err) => {
  showBanner("error", `Failed to load: ${err.message || err}`);
});
