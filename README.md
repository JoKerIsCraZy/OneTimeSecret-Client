<div align="center">

<img src="assets/onetime_preview.png" alt="OneTimeSecret Client" width="120" />

# OneTimeSecret Client

**A polished Windows desktop client for [OneTimeSecret](https://onetimesecret.com)**
Encrypted messages · single-use · self-destructing.

[![Build](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/build.yml/badge.svg)](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/build.yml)
[![Lint](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/lint.yml/badge.svg)](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/lint.yml)
[![CodeQL](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/codeql.yml/badge.svg)](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/actions/workflows/codeql.yml)
[![Release](https://img.shields.io/github/v/release/JoKerIsCraZy/OneTimeSecret-Client?color=22d3ee&label=release)](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776ab.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078d6.svg)](#)

</div>

---

## Overview

A native Tkinter GUI built on the OneTimeSecret **v2 API**. Send encrypted, single-use links from your desktop, track their state in a built-in history, and configure everything — region, language, credentials — without ever touching a config file by hand.

The API key is stored in the **Windows Credential Manager** (DPAPI-encrypted) via [`keyring`](https://pypi.org/project/keyring/). No secrets in source, no plaintext on disk.

## Features

- **Send** — Compose and conceal secrets with TTL presets (5 min … 14 days)
- **History** — Track every secret you create, with live state polling (`waiting / shared / retrieved / burned / expired`)
- **Status check** — Verify whether a recipient has opened the link, via `GET /api/v2/receipt/<id>`
- **Multi-region** — EU, Global, US, UK, CA, NZ, or a custom host
- **i18n** — English (default) and German, switchable at runtime
- **Settings panel** — In-app config for credentials, region, default TTL, network timeout
- **Secure storage** — API key in Windows Credential Manager (DPAPI), settings in `%APPDATA%\OneTimeSecret\`
- **Modern UI** — "Vault" theme: deep-navy + cyan, sidebar nav, custom thin scrollbars
- **Single-file `.exe`** — Built with PyInstaller, no Python install required on the target machine

## Quick start

### Option A — Download the prebuilt `.exe`

1. Grab the latest `OneTimeSecret-Client-vX.Y.Z.exe` from the [**Releases**](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/releases) page
2. Run it — no installation needed
3. On first launch, open **Settings**, enter your OneTimeSecret email + API key, pick a region, save

### Option B — Run from source

```powershell
git clone https://github.com/JoKerIsCraZy/OneTimeSecret-Client.git
cd OneTimeSecret-Client

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
python OneTimeSecret_Client.py
```

Requirements: **Python 3.12+** on **Windows 10/11**.

## Configuration

All settings are managed in the in-app **Settings** panel. Nothing is hardcoded.

| Setting          | Where it lives                                  |
| ---------------- | ----------------------------------------------- |
| API key          | Windows Credential Manager (DPAPI, via keyring) |
| Email / region   | `%APPDATA%\OneTimeSecret\settings.json`         |
| Default TTL      | `%APPDATA%\OneTimeSecret\settings.json`         |
| Network timeout  | `%APPDATA%\OneTimeSecret\settings.json`         |
| History          | `%APPDATA%\OneTimeSecret\history.json`          |

> Get an API key at [eu.onetimesecret.com/account](https://eu.onetimesecret.com/account) (or your chosen region).

## Build the `.exe` locally

```powershell
build.bat
```

This produces `dist\OneTimeSecret-Client.exe`. The script wraps PyInstaller with the right hidden imports for `keyring` on Windows.

For tagged releases, the `release.yml` workflow builds, versions, and publishes the `.exe` automatically — push a tag like `v1.2.3` and a GitHub Release appears with the binary attached.

## CI / CD

| Workflow                | Trigger                       | Purpose                                                |
| ----------------------- | ----------------------------- | ------------------------------------------------------ |
| `build.yml`             | Push / PR to `main`           | Compile sanity + PyInstaller build (artifact)          |
| `release-drafter.yml`   | Push to `main` + PR events    | Maintain a draft release with auto-categorised changelog; auto-label PRs by title prefix |
| `release.yml`           | Tag `v*.*.*` or manual        | Build the `.exe` and attach it to the GitHub Release   |
| `lint.yml`              | Push / PR                     | Ruff lint + format check (advisory)                    |
| `codeql.yml`            | Push / PR + weekly cron       | Security & quality scanning                            |
| `dependabot.yml`        | Weekly                        | Grouped dependency updates with rebase strategy        |

### Release flow

1. Open PRs with Conventional-Commit-style titles (`feat: …`, `fix: …`, `docs: …`, `ci: …`). The autolabeler tags each PR with `feature`, `fix`, `docs`, etc. based on the title prefix.
2. On merge, `release-drafter.yml` updates a single **draft release** on the Releases page — categorised changelog, suggested next version (patch by default; minor for `feature`, major for `breaking`/`major` labels).
3. When you're ready to ship, open the draft on GitHub and click **Publish release**. That creates the tag `vX.Y.Z`.
4. The tag push fires `release.yml`, which builds the `.exe` and attaches it to that Release.

Manual tagging still works (`git tag v1.2.3 && git push origin v1.2.3`) and bypasses the drafter — useful for hotfixes.

## Project layout

```
OneTimeSecret-Client/
├── OneTimeSecret_Client.py            # Single-file Tkinter app (~1.7k lines)
├── requirements.txt                   # requests, keyring
├── build.bat                          # Local PyInstaller build
├── assets/
│   ├── onetime.ico                    # App icon (multi-res, 16-256)
│   ├── onetime_preview.png            # 512px preview / README header
│   └── generate_icon.py               # Reproducible icon generator (Pillow)
└── .github/
    ├── workflows/                     # build, release, release-drafter, lint, codeql
    ├── release-drafter.yml            # Categories, version-resolver, autolabeler config
    ├── ISSUE_TEMPLATE/                # bug_report, feature_request
    ├── PULL_REQUEST_TEMPLATE.md
    └── dependabot.yml
```

## Tech stack

- **Python 3.12** · **Tkinter / ttk** for the GUI
- **requests** for HTTP, **keyring** for DPAPI-backed credential storage
- **OneTimeSecret v2 REST API** (Basic Auth + JSON)
- **PyInstaller** for `--onefile --windowed` builds
- **Ruff** · **CodeQL** · **Dependabot** for code health

## Security

- No credentials in source code
- API key encrypted at rest via Windows DPAPI (per-user)
- HTTPS-only requests; configurable timeout
- Status checked via API, never by opening the recipient link (which would consume it)

If you find a security issue, please open a private [security advisory](https://github.com/JoKerIsCraZy/OneTimeSecret-Client/security/advisories/new) instead of a public issue.

## Contributing

Issues and pull requests are welcome. See [`PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) for the checklist.

## License

Not yet licensed. Until a license file is added, all rights reserved by the author.

---

<div align="center">
<sub>Built for the OneTimeSecret <a href="https://docs.onetimesecret.com/en/rest-api/">v2 API</a>. Not affiliated with OneTimeSecret.</sub>
</div>
