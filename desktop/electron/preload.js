// Preload script — exposes a narrow IPC surface to the renderer.
// Renderer cannot import Node or call Electron APIs directly; it can
// only call the verbs we declare here.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zk", {
  // License / activation
  getLicense: () => ipcRenderer.invoke("license:get"),
  // Phase 4 — composite status for the banner / read-only logic.
  licenseStatus: () => ipcRenderer.invoke("license:status"),
  activate: (key) => ipcRenderer.invoke("license:activate", key),
  signOut: () => ipcRenderer.invoke("license:signOut"),
  // Sidecar
  sidecarUrl: () => ipcRenderer.invoke("sidecar:url"),
  // Phase 4 — proxy HTTP call to the sidecar with the entitlement
  // header attached. The renderer never sees the entitlement string.
  // Body is JSON-stringified for non-GET; returns { ok, status, body }.
  fetch: (path, options = {}) =>
    ipcRenderer.invoke("sidecar:fetch", {
      path,
      method: options.method || "GET",
      body: options.body || null,
    }),
  // Navigation between Electron-hosted pages.
  goToMain: () => ipcRenderer.invoke("nav:toMain"),
  goToActivate: () => ipcRenderer.invoke("nav:toActivate"),
});
