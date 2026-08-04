<p align="center">
  <img src="./assets/icon.png" width="112" alt="Codex Sync Desktop icon">
</p>

<h1 align="center">Codex Sync Desktop</h1>

<p align="center">
  Synchronize, merge, and restore textual Codex sessions across Windows and macOS through a private GitHub repository owned by the user.
</p>

<p align="center">
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-%3E%3D3.9-3776AB.svg">
  <img alt="Platforms" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS-36BFFA.svg">
</p>

<p align="center">
  <a href="./README.md">简体中文</a> · English
</p>

Codex Sync Desktop exports active textual Codex sessions without image or attachment binaries, stores one device directory in a private GitHub vault, verifies manifests, merges divergent content by semantic records and time, and repairs the target Codex SQLite/sidebar index.

> [!IMPORTANT]
> The application source is public, but conversation vaults must remain private. Tokens, secrets, commands, tool output, reasoning text, and other sensitive textual content are preserved. Never submit real sessions or credentials to this repository, Issues, Discussions, or a public sync vault.

> [!NOTE]
> This is a community open-source project. It is not an official OpenAI product and does not represent an OpenAI backup or migration guarantee.

## Highlights

- Guided Git/GitHub CLI setup and browser-based GitHub authorization
- New or existing private repository onboarding
- Windows, Intel macOS, and Apple Silicon macOS support
- Full textual records with media and binary attachments omitted
- Cross-platform SHA-256 verification resilient to Git line-ending conversion
- Content- and time-based merge instead of blind ID overwrite
- Editable full import preview and title synchronization
- SQLite and `session_index.jsonl` repair
- Transaction backup, one-step rollback, and bounded logs/backups
- Automatic recovery when a downloaded GitHub ZIP snapshot is selected instead of a real clone

## Quick Start

Download a build from [Releases](https://github.com/cieyyy/codex-sync-desktop/releases), open the first-run wizard, sign in to GitHub, and select or create a private conversation vault. On another device, select the same repository and choose the source device in **Sync & Import**.

Close ChatGPT/Codex/Codex++ before an operation that imports sessions, repairs indexes, or rolls back an import. Pull, export, preview, login, and diagnostics do not require closing Codex.

## Development

Python 3.9+ and Tk 8.6+ are required.

```powershell
python -m codex_sync_desktop
python -m unittest discover -s tests -v
```

See [Architecture](./docs/ARCHITECTURE.md), [Contributing](./CONTRIBUTING.md), and [Security](./SECURITY.md).

## Non-goals

- Real-time remote control of every device
- Synchronizing authentication files or the entire `.codex` directory
- Making public conversation repositories safe
- Replacing Codex, GitHub, or operating-system security controls

## License

[MIT License](./LICENSE)
