// Preload script — exposes a narrow IPC surface to the renderer.
// Renderer cannot import Node or call Electron APIs directly; it can
// only call the verbs we declare here.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("zk", {
  // License / activation
  getLicense: () => ipcRenderer.invoke("license:get"),
  activate: (key) => ipcRenderer.invoke("license:activate", key),
  signOut: () => ipcRenderer.invoke("license:signOut"),
  // Sidecar
  sidecarUrl: () => ipcRenderer.invoke("sidecar:url"),
  // Navigation between Electron-hosted pages.
  goToMain: () => ipcRenderer.invoke("nav:toMain"),
  goToActivate: () => ipcRenderer.invoke("nav:toActivate"),
});
