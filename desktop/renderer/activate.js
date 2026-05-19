// Activation screen logic. The renderer reaches the cloud via the
// IPC-exposed window.zk surface (preload.js); no direct network from
// the renderer.

const form = document.getElementById("activate-form");
const input = document.getElementById("key");
const button = document.getElementById("submit");
const statusEl = document.getElementById("status");

function showStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = `status ${kind}`;
  statusEl.hidden = false;
}

function hideStatus() {
  statusEl.hidden = true;
  statusEl.textContent = "";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideStatus();
  const key = input.value.trim();
  if (!key) return;

  button.disabled = true;
  button.textContent = "Activating…";
  try {
    const result = await window.zk.activate(key);
    showStatus(
      `Activated for ${result.organization_legal_name}. Loading…`,
      "success",
    );
    // Give the user a beat to read the success line before we navigate.
    setTimeout(() => window.zk.goToMain(), 600);
  } catch (err) {
    showStatus(err.message || "Activation failed.", "error");
    button.disabled = false;
    button.textContent = "Activate";
  }
});
