# Native Tura Role

## End-State Contract

The preferred Tura integration is an explicitly invoked `$tura-kernel` Skill in
a first-class Native Codex task created by the parent Commander. Native Codex is
the sole owner of session and task persistence, tools, effects, provider turns,
interruption, and terminal state. Tura adds only the execution policy needed to
keep one mission on its first false predicate and returns one official
`send_message_to_thread` callback.

The Commander creates these tasks with `thinking="max"`. This is the Skill's
default and highest admitted reasoning effort. `ultra` is not a Tura Kernel
tier and must be rejected rather than silently relabeled or downgraded.

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
After independently reviewing a new package, an operator can atomically adopt
its exact Skill bytes with:

```bash
tura-taskpacket install-skill --replace
```

The replacement receipt records the previous member digests. Verification
failure restores the prior directory; this does not modify Codex application
bytes or introduce an updater service.

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

For new mechanically prepared dispatches, the parent binds a
`NativeTuraExecutionProfile` into capsule v3. The profile's digest covers the
exact model, supported reasoning effort, and official project/projectless
target. `ultra` is rejected rather than silently mapped to `max`.

Compile the verified capsule into exact official task-creation arguments with:

```bash
tura-taskpacket prepare-dispatch --task-name /root/example_task
```

This command is a pure compiler: it emits one deterministic dispatch identity,
one exact Skill-contract digest, deterministic payload-size metrics, and a
`create_thread` argument object, but it does not call `create_thread`.
Changing the execution profile changes the callback identity, preventing a task
started with different model or target settings from reusing the old callback.

When every declared scope starts with `read:`, the compiler also emits
`NATIVE_TURA_READ_ONLY_FAST_PATH_V1`. The worker then performs one batched
Native read stage, resolves its task ID directly from `CODEX_THREAD_ID`, and
sends the canonical terminal without inspecting harness source/tests or doing a
child-side render/parse loop. Callback identity and no-retry semantics remain
unchanged; the parent still performs exact terminal intake. Static execution
policy lives only in the versioned Skill; the prompt carries its version/digest,
task-local fields, fast-path marker, and exact terminal template. This removes
redundant provider turns from small verification tasks without weakening the
general effecting-task contract. The compiler also embeds the exact two-line
`NATIVE_TURA_CANONICAL_TERMINAL_TEMPLATE_V1`, including the bound callback,
parent, mission, predicate, and canonical marker; the worker fills only observed
terminal fields. Its single read batch uses zsh-safe variable names and exact or
hidden-aware installed paths so a successful read is not converted into a
synthetic blocker by shell parameter collisions.

For a context-bound task, the parent should render the already-published,
verified capsule into the initial Native task with:

```bash
tura-taskpacket load --task-name /root/example_task --format dispatch
```

The resulting prompt starts with `$tura-kernel`, carries the exact task and
callback identities, and includes only the task projection plus the
execution-relevant J-Space policy. The complete context and J-Space source bytes
remain in the immutable capsule instead of being repeated in every provider
tool turn. The Skill consumes this inline dispatch without an extra loader,
context read, or digest pass.

Only when Native Codex cannot expose that rendered initial message and supplies
the capsule task name alone does the Skill run exactly one fallback load:

```bash
tura-taskpacket load --task-name /root/example_task --format task
```

The task name is only a lookup key. On an unreadable Native turn, the child
loads the unique highest immutable revision and must use the verified capsule
contents, including the exact parent thread and callback identity, and must not
infer instructions from the name itself.

Use `tura-taskpacket inspect-packets` for a read-only root inventory. Its
deterministic classifications are `CURRENT_PROFILED`, `LEGACY_READABLE`, and
`REJECTED`. Digest-only filenames are accepted only for immutable capsule v1;
the loader never migrates those bytes, and their absent execution profile keeps
them ineligible for `prepare-dispatch`.

The task uses Native Codex persistence and tools. At terminal it performs one
official `send_message_to_thread` call to the bound parent. No external Tura
request, Session DB, Gateway, Router, or terminal-envelope transport
participates in this profile.

The callback body has one canonical machine-readable shape: the exact marker
`[TURA_NATIVE_TERMINAL_V1]`, a newline, and one JSON object conforming to
`native_tura_terminal_v1.schema.json`. The public
`parse_native_tura_terminal_callback()` API verifies the callback, parent, and
task identities. Historical prose, key/value, or alternate-marker callbacks
are not silently accepted as equivalent terminal state.
The complete marker plus JSON callback is limited to 65,536 UTF-8 bytes and 32
evidence items. Larger output must be represented by concise immutable refs,
digests, media type, and size rather than inline payload bytes.

Native delivery confirmation is schema-light: a normally returned
`CallToolResult` whose `isError` is absent or `false` confirms delivery. The
tool can return only the destination `threadId` in a content block, so workers
must not require `structuredContent.status` or manufacture a second callback
after a false-negative local check.

Deployment acceptance should prove the Skill is readable from the installed
package, the installed target digests match the reviewed resources, a fresh
first-class task can explicitly load `$tura-kernel`, and its callback works
while optional external Tura services are unavailable.

## External Compatibility Profile

`TuraAdapter`, its wire schemas, and `components/tura-runtime.json` remain in
this repository for third-party external runtimes, protocol conformance, and
historical implementation provenance. They are not required by the Native
Codex role and must not be interpreted as a second lifecycle owner.
