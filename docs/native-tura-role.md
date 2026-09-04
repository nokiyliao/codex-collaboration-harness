# Native Tura Role

## End-State Contract

The preferred Tura integration is an explicitly invoked `$tura-kernel` Skill in
a first-class Native Codex task created by the parent Commander. Native Codex is
the sole owner of session and task persistence, tools, effects, provider turns,
interruption, and terminal state. Tura adds only the execution policy needed to
keep one mission on its first false predicate and returns one official
`send_message_to_thread` callback.

The canonical Skill resources are packaged at:

```text
codex_collaboration_harness/skills/tura-kernel/SKILL.md
codex_collaboration_harness/skills/tura-kernel/agents/openai.yaml
codex_collaboration_harness/skills/tura-kernel/references/native-topology.md
```

Install or verify those exact packaged bytes with:

```bash
tura-taskpacket install-skill
```

The command installs under `$CODEX_HOME/skills/tura-kernel` (defaulting to
`~/.codex/skills/tura-kernel`). An identical target is a no-op; an existing
different target fails with `SKILL_TARGET_PREIMAGE_DRIFT` and is not overwritten.

The packaged `agents/tura.toml` resource remains available for compatibility
with Native runtimes that expose named agent roles. It is not the first-class
task dispatch baseline used by this profile.

The canonical resource is packaged at:

```text
codex_collaboration_harness/agents/tura.toml
```

Its reviewed SHA-256 is:

```text
2383fb6d65b3d9c71f6e5b972ae6718e723a3f684c9b55c9139a7c9fccba8983
```

The role does not contain or launch a Gateway, Router, Session DB, provider
runtime, daemon, MCP relay, queue, or callback transport. It also does not grant
authority: the parent task packet and Native Codex tool boundary remain
authoritative.

When Native Codex cannot expose the dynamic parent message to the child, the
parent publishes one content-addressed task capsule revision under the child's
canonical task name. Follow-up turns add a higher immutable revision; no mutable
current pointer is used. The dependency-free `tura-taskpacket` command selects
the unique highest revision and verifies the capsule's
TaskPacket identity, callback binding, digest filename, regular-file shape,
mode, and link count before rendering the five decision fields. This is an
immutable input bootstrap, not a second task database or dispatcher.

## Compatibility Role Installation

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

A parent uses official `create_thread` and explicitly invokes `$tura-kernel` in
the initial prompt together with the five decision fields:

```text
MISSION
FIRST_FALSE_PREDICATE
SHORTEST_VALID_ROUTE
EXPECTED_PREDICATE_DELTA
ABANDON_IF
```

If the task uses an immutable capsule binding, the Skill runs exactly one:

```bash
tura-taskpacket load --task-name /root/example_task --format task
```

The task name is only a lookup key. On each unreadable Native turn, the child
loads the unique highest immutable revision and must use the verified capsule
contents, including the exact parent thread and callback identity, and must not
infer instructions from the name itself.

The task uses Native Codex persistence and tools. At terminal it performs one
official `send_message_to_thread` call to the bound parent. No external Tura
request, Session DB, Gateway, Router, or terminal-envelope transport
participates in this profile.

Deployment acceptance should prove the Skill is readable from the installed
package, the installed target digests match the reviewed resources, a fresh
first-class task can explicitly load `$tura-kernel`, and its callback works
while optional external Tura services are unavailable.

## External Compatibility Profile

`TuraAdapter`, its wire schemas, and `components/tura-runtime.json` remain in
this repository for third-party external runtimes, protocol conformance, and
historical implementation provenance. They are not required by the Native
Codex role and must not be interpreted as a second lifecycle owner.
