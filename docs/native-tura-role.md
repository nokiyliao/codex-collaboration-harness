# Native Tura Role

## End-State Contract

The preferred Tura integration is a thin Native Codex agent role. Native Codex
is the sole owner of session and task persistence, child lifecycle, tools,
effects, interruption, terminal state, and direct-parent callback. Tura adds
only the execution policy needed to keep one mission on its first false
predicate and to abandon an unproductive route after one bounded attempt.

The canonical resource is packaged at:

```text
codex_collaboration_harness/agents/tura.toml
```

Its reviewed SHA-256 is:

```text
66fe64b57770f1155770e234706d074d55e467c15fc47c99683b2f43918cfb3b
```

The role does not contain or launch a Gateway, Router, Session DB, provider
runtime, daemon, MCP relay, queue, or callback transport. It also does not grant
authority: the parent task packet and Native Codex tool boundary remain
authoritative.

## Drift-Safe Installation

The following installs the exact packaged bytes into the standard Codex agent
directory. An identical target is a no-op; a different existing target fails
with `TARGET_PREIMAGE_DRIFT` instead of being overwritten.

```bash
python3 - <<'PY'
from importlib.resources import files
from pathlib import Path
import os
import tempfile

source = files("codex_collaboration_harness").joinpath("agents", "tura.toml")
payload = source.read_bytes()
target = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "agents" / "tura.toml"
target.parent.mkdir(parents=True, exist_ok=True)
descriptor, temporary_name = tempfile.mkstemp(
    dir=target.parent, prefix=".tura.", suffix=".tmp"
)
try:
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary_name, 0o644)
    try:
        os.link(temporary_name, target, follow_symlinks=False)
    except FileExistsError:
        if target.is_symlink() or not target.is_file() or target.read_bytes() != payload:
            raise SystemExit("TARGET_PREIMAGE_DRIFT")
finally:
    Path(temporary_name).unlink(missing_ok=True)
print(target)
PY
```

## Native Dispatch

A parent selects the `tura` agent role explicitly and sends a bounded task with
the five decision fields:

```text
MISSION
FIRST_FALSE_PREDICATE
SHORTEST_VALID_ROUTE
EXPECTED_PREDICATE_DELTA
ABANDON_IF
```

The child uses the same Native Codex persistence and tools as other Codex
children. Its terminal response returns over the same direct-parent callback.
No external Tura request or terminal-envelope transport participates in this
profile.

Deployment acceptance should prove the role is readable from the installed
package, the installed target digest matches the reviewed resource, a fresh
`tura` child returns to its direct parent, and that callback still works while
the optional external Tura services are unavailable.

## External Compatibility Profile

`TuraAdapter`, its wire schemas, and `components/tura-runtime.json` remain in
this repository for third-party external runtimes, protocol conformance, and
historical implementation provenance. They are not required by the Native
Codex role and must not be interpreted as a second lifecycle owner.
