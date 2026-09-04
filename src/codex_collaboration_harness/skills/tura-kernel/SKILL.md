---
name: tura-kernel
description: Run callback-critical or long-lived work as a first-class Native Codex task with Tura objective-first execution policy. Use only for an explicit operator or Commander dispatch.
---

# Tura Kernel

This task is Native Codex. Codex owns its thread, persistence, provider, tools,
receipts, interruption recovery, and process lifecycle. Tura adds execution
policy and one direct terminal callback; it is not a second runtime.

`thinking="max"` is the highest admitted Tura effort. Reject a higher declared
effort as `TURA_REASONING_EFFORT_UNSUPPORTED`; never silently relabel it.

Read [references/native-topology.md](references/native-topology.md) only when
the task diagnoses ownership, callback delivery, or legacy retirement.

## Admission

The persisted initial user message must contain:

- `MISSION`
- `FIRST_FALSE_PREDICATE`
- `SHORTEST_VALID_ROUTE`
- `EXPECTED_PREDICATE_DELTA`
- `ABANDON_IF`
- `parent_thread_id`
- `callback_id`

Do not infer missing input from chat history, names, sibling tasks, or stale
Tura state. If `NATIVE_EXECUTION_PROFILE` is present, its digest, model,
thinking, and target must match the Native task metadata or reject with
`TURA_NATIVE_EXECUTION_PROFILE_MISMATCH`.

`NATIVE_TURA_INLINE_CAPSULE_V1` is already Commander-verified. Do not reload or
rehash it. Start from `task_projection` and its task-local evidence. Only a
dispatch without an inline capsule may run `tura-taskpacket load` once.

Treat one dispatch as one first-class task. It owns one fresh Native task and
one callback identity. Never reuse a terminal task or a task that attempted
callback for another mission, retry, or shard.

## Execute

Keep the five decision fields above in working state. Advance only the first
false predicate by the shortest valid route. One bounded route may continue as
long as it changes predicate state; do not impose a fixed wall timeout.

Use Native Codex tools. Batch independent reads and serialize dependent
mutations. Effects must remain top-level Native tool calls so Codex owns their
receipts and recovery. Do not add a Tura Gateway, Router, Session DB, scheduler,
lease store, callback queue, second App Server, raw App-tools pipe, GUI proxy,
or private Codex DB/rollout write. DCF and J-Space are optional read-only task
inputs, not lifecycle owners.

Parallel work uses separate Commander-created first-class tasks. Do not spawn
Tura-internal children or copy full history to simulate packet transport.

### Read-only fast path

When `NATIVE_TURA_READ_ONLY_FAST_PATH_V1` and
`NATIVE_TURA_FAST_PATH_EXECUTION_V3` are present, the inline fast-path contract
is complete. Do not read this Skill file again from the task; execute the inline
contract directly:

1. After this Skill read, emit no commentary before or between task reads.
2. The first task-read stage must be one Native batched-read stage containing
   both `CODEX_THREAD_ID` and every independent task read. A later task-ID-only
   call is forbidden.
3. Use exact known hidden paths or `rg --files --hidden --no-ignore`. In zsh,
   never assign `path`, `status`, `commands`, or `pipestatus`.
4. Do not inspect harness source/tests, re-render or self-parse the terminal, or
   create an intermediate receipt/review stage.
5. From that one result, fill the embedded
   `NATIVE_TURA_CANONICAL_TERMINAL_TEMPLATE_V1` and immediately call
   `send_message_to_thread` once.

This is one Native batched-read stage, not relaxed scope or identity checking.
The parent performs exact callback intake.

## Terminal Callback

Tura is a trusted executor and thread writer. At terminal, call the official
`send_message_to_thread` exactly once for the bound parent. Send only this
marker, one newline, and canonical JSON with exactly these keys:

```text
[TURA_NATIVE_TERMINAL_V1]
{"schema_version":"tura_native_terminal_v1","callback_id":"...","parent_thread_id":"...","task_thread_id":"...","status":"PREDICATE_ADVANCED|MISSION_COMPLETE|BLOCKED","mission":"...","predicate":"...","predicate_delta":"...","evidence":[],"first_typed_blocker":null,"authority_effect":"none","protected_effect_count":0}
```

Resolve `task_thread_id` only from `CODEX_THREAD_ID`. Populate actual effect
values. Successful tool return with no `isError:true` means delivered. On
success, do not wait for a reverse Commander ACK. Delivery does not prove parent
mission acceptance. If the tool throws or returns `isError:true`, record
`CALLBACK_DELIVERY_UNSETTLED` and do not retry.

After successful callback, the final response must be exactly:

```text
DELIVERED <callback_id>
```

The marker plus JSON must not exceed 65,536 UTF-8 bytes or 32 evidence items.
Return large logs, diffs, and artifacts by immutable reference and digest.
