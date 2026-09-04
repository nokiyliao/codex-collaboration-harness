---
name: tura-kernel
description: Run callback-critical or long-lived work as a first-class Native Codex task with Tura's objective-first execution policy. Use only when an operator or Commander explicitly dispatches work to Tura; do not use legacy Tura services or treat this as a general-purpose planning skill.
---

# Tura Kernel

Run inside the current first-class Codex task. Codex remains the sole owner of
the task/thread, session persistence, rollout, tools, provider turn, process
lifecycle, and restart recovery. Tura supplies execution policy only.

The Commander must create Native Tura tasks with `thinking="max"`. `max` is
the default and highest admitted reasoning effort for this Skill; do not request
or report `ultra` as a Tura Kernel tier. An operator may explicitly choose a
lower supported effort for a particular task, but the Skill must never silently
raise, lower, or relabel the task's actual Native Codex reasoning metadata.

Read [references/native-topology.md](references/native-topology.md) when
diagnosing ownership, callback delivery, or legacy-surface retirement.

## Admit The Task

Use the current task's persisted initial user message as the authoritative
dispatch input. Require these fields before performing effects:

- `MISSION`
- `FIRST_FALSE_PREDICATE`
- `SHORTEST_VALID_ROUTE`
- `EXPECTED_PREDICATE_DELTA`
- `ABANDON_IF`
- `parent_thread_id`
- `callback_id`

Accept task-local scope, authority, evidence references, acceptance criteria,
model, reasoning effort, and service tier when supplied. Reject a declared
reasoning effort above `max` as `TURA_REASONING_EFFORT_UNSUPPORTED`; do not
silently downgrade it. Do not invent missing authority or infer
task input from chat history, filenames, task titles, sibling tasks, or stale
Tura state.

New Commander-prepared tasks also carry `NATIVE_EXECUTION_PROFILE`. Require its
profile digest, model, reasoning effort, and target to match the initial Native
task metadata. A mismatch is `TURA_NATIVE_EXECUTION_PROFILE_MISMATCH`; do not
repair it by changing model, effort, target, callback identity, or task.

Treat one dispatch as one first-class task. After that task has terminalized or
attempted its callback, do not reuse it for a new mission, shard, retry, or
follow-up dispatch. The parent Commander creates a fresh Native task with a new
callback identity instead. This keeps Tura task identity independent from a
completed provider response chain.

When the initial dispatch contains `NATIVE_TURA_INLINE_CAPSULE_V1`,
`NATIVE_TASK_BINDING`, and `TASK_LOCAL_EVIDENCE`, treat that inline capsule as
already loaded and verified by the Commander. Do not call `tura-taskpacket`,
re-read the bound context files, or recompute their hashes merely to validate
the dispatch. Start from `task_projection`; use Native Codex reads only when a
required result field is absent from that projection. Continue only when the
inline parent and callback identities match the initial dispatch.

When the dispatch supplies only a Native Tura capsule task name and no inline
capsule, load it exactly once with
`tura-taskpacket load --task-name <name> --format task` and verify that its
parent and callback identities match the initial message. This loader is
optional immutable-input validation, not a session store or runtime.

### Read-only fast path

When the dispatch contains `NATIVE_TURA_READ_ONLY_FAST_PATH_V1`, every admitted
execution scope is explicitly read-only. Keep the five decision fields in
working state, but do not spend provider turns narrating them between reads.

- Do not run a command to re-read this Skill after it has been activated.
- Execute all independent evidence checks in one Native batched-read stage.
- Native command shells are zsh. Never assign its special parameters `path`,
  `status`, `commands`, or `pipestatus`; use descriptive names such as
  `candidate_path` and `worktree_state` instead.
- For hidden installed roots, use exact known paths or
  `rg --files --hidden --no-ignore`; a default hidden-file search is not absence
  evidence.
- Resolve the exact current task identity once from `CODEX_THREAD_ID`. If it is
  absent, return `TURA_NATIVE_TASK_ID_UNAVAILABLE`; do not search or guess.
- Do not inspect harness source or tests to rediscover the terminal format
  already embedded in the dispatch.
- Do not render and parse the terminal again inside the child merely to prove
  its own output. The parent performs exact callback intake.
- After the read batch, use the dispatch's exact
  `NATIVE_TURA_CANONICAL_TERMINAL_TEMPLATE_V1` two-line callback and call
  `send_message_to_thread` immediately. Keep its marker, key set, bound
  identities, mission, and predicate unchanged. Do not add an intermediate
  review, receipt publication, progress report, or callback acknowledgement
  phase.

This fast path removes redundant model boundaries; it does not relax scope,
identity, effect, callback, or no-retry rules.

## Execute

Before each non-trivial action keep the five required decision fields current.
Work on the first false predicate and give the selected route one bounded
attempt. A long route may run for as long as it keeps producing predicate
progress; do not impose an arbitrary wall-clock timeout.

Reuse authoritative current state and Native Codex tools. Batch independent
reads and deterministic command sets. Serialize dependent mutations. Keep
effecting commands as top-level Native tool calls so Codex owns their durable
receipts and interruption recovery.

For independent semantic shards, ask the parent Commander to dispatch separate
first-class Tura tasks. Do not use Native multi-agent children as an operational
baseline: child packet visibility is a platform capability and must not be
simulated with copied history, a bridge, or another runtime. Parallel Tura tasks
remain independently persistent and each owns exactly one callback identity.
Do not use another task merely to run several deterministic commands.

Do not create or use a Tura Gateway, Router, Session DB, scheduler, lease store,
callback queue, standalone App Server, raw App-tools pipe, or GUI proxy. Never
write Codex private SQLite or rollout files. DCF and J-Space are optional
read-only context/authority tools when the task requires them, not alternate
lifecycle owners.

## Deliver The Terminal

Tura is an operator-trusted executor and thread writer. At terminal, call the
official Native Codex `send_message_to_thread` tool exactly once for the bound
`parent_thread_id`. Send a concise packet prefixed
`[TURA_NATIVE_TERMINAL_V1]` with exactly these fields:

```json
{
  "schema_version": "tura_native_terminal_v1",
  "callback_id": "<bound callback identity>",
  "parent_thread_id": "<bound parent>",
  "task_thread_id": "<current Codex task id>",
  "status": "PREDICATE_ADVANCED | MISSION_COMPLETE | BLOCKED",
  "mission": "<mission>",
  "predicate": "<first false predicate worked>",
  "predicate_delta": "<actual state change or none>",
  "evidence": [],
  "first_typed_blocker": null,
  "authority_effect": "none",
  "protected_effect_count": 0
}
```

Populate effect fields with actual values rather than the example defaults.
Send only the exact marker, one newline, and the JSON object. Do not prepend or
append prose, rename fields, emit a key/value summary, or substitute a historical
terminal marker. When the public package is available, its
`NativeTuraTerminal.render()` method is the canonical renderer.
The successful tool response is delivery confirmation and completes the Tura
task; do not wait for a reverse Commander ACK. It proves that the callback
message was accepted by the Native task tool, not that the parent provider turn
or parent mission acceptance completed. If the parent later encounters a Native
continuation failure, preserve the delivered callback and intake it on a later
Commander turn; never resend the callback. If delivery is uncertain, do not
retry. Finish locally with `CALLBACK_DELIVERY_UNSETTLED`, the payload digest,
and the exact uncertain attempt so Commander can reconcile it from Native task
history.

Treat a `send_message_to_thread` invocation that returns normally with
`CallToolResult.isError` absent or `false` as successful delivery. The Native
tool may return only a content block containing the target `threadId`; do not
require `structuredContent`, `status`, or an acknowledgement field. A thrown
tool/transport error or `isError: true` remains delivery-uncertain and must not
be retried blindly.

The child task's final response is fallback evidence only. Mission convergence
belongs to the parent Commander after callback intake.

The complete marker plus JSON callback must not exceed 65,536 UTF-8 bytes and
`evidence` must contain at most 32 items. Keep each item concise and use
immutable references, digests, media types, and byte sizes for large artifacts;
do not inline large logs, source files, reports, or binary content.
