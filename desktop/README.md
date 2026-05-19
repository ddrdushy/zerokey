# ZeroKey Desktop

> Phase 2 of `docs/DESKTOP_PIVOT_PLAN.md`. The Electron shell that hosts
> the ZeroKey desktop app: a license-activation screen, a daily
> heartbeat to the cloud, and (in Phase 3) the full React UI talking to
> a bundled Django sidecar.

## Layout

```
desktop/
├── electron/         # Electron main process + preload (JavaScript)
│   ├── main.js       # entrypoint — spawn sidecar, create window, schedule heartbeat
│   ├── preload.js    # IPC bridge for the renderer
│   ├── sidecar.js    # subprocess lifecycle for the Python sidecar
│   └── license.js    # license-key + entitlement store backed by keytar
├── renderer/         # Phase 2: plain HTML activation flow.
│   ├── activate.html
│   ├── activate.css
│   └── activate.js
│   └── main.html     # Phase-3 placeholder — will redirect into the sidecar UI
├── sidecar/          # Bundled Python subprocess (Django on SQLite)
│   ├── pyproject.toml
│   ├── manage.py
│   ├── run_sidecar.py
│   └── zk_desktop/   # the Django project itself
└── package.json
```

## What ships in Phase 2 (this commit)

- A working Electron app: `npm run dev` opens the activation window.
- Activation talks to `/api/v1/licenses/validate/` on the cloud
  (defaults to `https://zerokey.symprio.com` — override with
  `ZK_LICENSE_API_BASE`).
- On a successful validation the entitlement is stored via keytar
  (Windows Credential Manager / macOS Keychain / GNOME libsecret) and
  the window navigates to a placeholder main screen.
- A 24-hour heartbeat ticks in the main process. Failures are logged
  but don't break the app — read-only enforcement lands in Phase 4.
- The sidecar boots and serves `/healthz` + `/version`. Phase 3 moves
  the full backend in.

## What's deferred

| Concern | Phase |
| --- | --- |
| Move tenant Django apps into the sidecar (submission, parse, validate, connectors…) | 3 |
| Verify entitlements offline against the embedded Ed25519 public key | 4 |
| Read-only mode when the cached entitlement expires | 4 |
| electron-builder configuration + signing + auto-update | 5 |
| Telemetry receiver on the cloud | 6 |

## Running locally

```bash
# 1. Make sure the cloud /api/v1/licenses/validate/ endpoint is reachable.
#    For local dev pointing at the dev backend:
export ZK_LICENSE_API_BASE=http://localhost:8000

# 2. Install + run.
cd desktop
npm install
npm run dev
```

The Electron window opens on `activate.html`. Paste a license key
issued by the super admin (`/admin/licenses` → Issue license). On
success it stores the entitlement and routes to `main.html`.

The sidecar runs at a random localhost port. The activation screen
does NOT talk to it; only the future main UI does.

## Building installers

Deferred to Phase 5. The plan is electron-builder producing an NSIS
installer for Windows (signed with an EV cert, auto-update via
electron-updater pointed at an S3 release feed).
