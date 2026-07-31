# Architecture

The complete Chinese product plan and implementation history are maintained in:

- [Codex Sync Desktop 总体方案](PRODUCT_SOLUTION_ZH.md)
- [Codex Sync Desktop 已实施修改记录](IMPLEMENTED_CHANGES_ZH.md)

## Data flow

```text
Codex JSONL
  -> active-session selection
  -> recursive record preservation
  -> inline media and binary omission
  -> title extraction
  -> SHA-256 manifest
  -> private GitHub vault
  -> manifest verification
  -> append or semantic/time merge
  -> SQLite/index repair
```

The synchronization repository stores one directory per device under
`sessions-text/devices/<device>/`. Format 4 manifests contain paths rooted at
the Codex home. Older manifests from `project-sync-vault` remain
import-compatible.

## Safety invariants

1. A manifest path may not be absolute or contain `..`.
2. A source file must match its manifest hash before any import is applied.
3. Different content is merged by normalized semantic records and timestamps instead of blindly overwriting by ID.
4. Database changes happen only after a consistent transaction backup.
5. Repair inserts missing rows and updates paths/timestamps while preserving valid human titles or applying an explicit imported title.
6. Authentication files and raw Codex databases are never uploaded by the exporter.
7. User, assistant, command, tool, reasoning, task-state, and sensitive textual fields are preserved; only media and binary content are omitted.
8. Only active sessions are exported. Archived or deleted local sessions are removed from the current device's next export.

## Storage

The source tree has no heavy runtime framework dependencies. Packaged builders
install PyInstaller temporarily. Local transaction backups include affected
session files, state databases, and small index files. Only the most recent
rollback point is retained by default, keeping routine storage use bounded.
