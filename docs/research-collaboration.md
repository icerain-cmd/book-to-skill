# Shared workspace collaboration

Research-to-Skill supports a portable single-writer protocol for research projects stored on Windows/WSL shared filesystems.

## Storage boundary

Keep canonical repositories, projects, sources, semantic artifacts, and collaboration documents in the shared workspace. Keep `.venv`, `__pycache__`, pip caches, `node_modules`, build output, test output, and OS-specific runtime files on each machine's local filesystem.

## Writer lock

The lock file is `<project>/.research-to-skill.lock`. It is created with exclusive file creation and does not depend on symlinks, `chmod`, `fcntl`, or other Unix-only locking behavior. Its default TTL is two hours.

```bash
research-to-skill lock status --project <project>
research-to-skill lock acquire --project <project> --owner codex --operation semantic-write
research-to-skill lock release --project <project> --owner codex
```

`add`, `remove`, `compile`, and `compile --complete` acquire and release this lock automatically. If an operation fails, it attempts lock cleanup in `finally`.

Expired locks are reported as stale but are never removed automatically. After confirming that no writer is active, remove one explicitly:

```bash
research-to-skill lock break --project <project> --force
```

## Machine identity

Optionally configure a local identity outside the shared workspace at `~/.config/research-to-skill/config.json`:

```json
{
  "agent": "codex",
  "machine": "PC1"
}
```

The fallback agent is `local`; the fallback machine is the hostname.

## Session protocol

Start a session by checking Git, running preflight, and checking the lock:

```bash
git status
research-to-skill preflight --project <project>
research-to-skill lock status --project <project>
git log -1 --oneline
```

End a session by validating, checking status and lock cleanup, reviewing the diff, committing intentional changes, and generating a handoff:

```bash
research-to-skill validate --project <project>
research-to-skill status --project <project>
research-to-skill lock status --project <project>
git diff
git status
research-to-skill handoff --project <project>
```

`preflight` summarizes the stable project UUID, project counts, validation, lock state, and Git state. `handoff` writes an automatically generated `<project>/HANDOFF.md` for the next agent.
