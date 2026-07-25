# Architecture

## Data flow

```text
Codex JSONL
  -> record allow-list
  -> media/tool/reasoning omission
  -> credential redaction
  -> SHA-256 manifest
  -> private GitHub vault
  -> manifest verification
  -> append or quarantine
  -> SQLite/index repair
```

The synchronization repository stores one directory per device under
`sessions-text/devices/<device>/`. Format 2 manifests include paths rooted at
the Codex home (`sessions/...` or `archived_sessions/...`). Format 1 manifests
from `project-sync-vault` remain import-compatible.

## Safety invariants

1. A manifest path may not be absolute or contain `..`.
2. A source file must match its manifest hash before any import is applied.
3. Existing files are never overwritten when their hashes differ.
4. Database changes happen only after a consistent SQLite backup.
5. Repair inserts missing rows and updates file/path timestamps, but preserves titles.
6. Authentication files and raw Codex databases are never uploaded by the exporter.

## Storage

The source tree has no runtime dependencies. GitHub-hosted builders install
PyInstaller temporarily. Local backups include only state databases and small
index files, keeping routine storage use bounded.
