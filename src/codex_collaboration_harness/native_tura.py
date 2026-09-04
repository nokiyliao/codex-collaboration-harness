# SPDX-License-Identifier: MIT
"""Content-addressed task bootstrap for the Native Codex Tura role.

The capsule carries immutable task input only. Native Codex remains responsible
for sessions, child lifecycle, tools, effects, terminal state, and callbacks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .core import Destination, TaskPacket, canonical_sha256, verify_identity


NATIVE_TURA_CAPSULE_VERSION = "native-tura-task-capsule/v1"
MAX_CAPSULE_BYTES = 512 * 1024
_CANONICAL_TASK_NAME = re.compile(r"^/root(?:/[a-z0-9_]+)+$")
_PACKET_KEYS = {
    "abandon_if",
    "destination",
    "executor_id",
    "expected_delta",
    "mission_id",
    "mission_mode",
    "mission_revision",
    "packet_id",
    "predicate_key",
    "recovery_budget",
    "route_id",
    "scope",
    "scope_versions",
}
_CAPSULE_KEYS = {
    "callback_id",
    "canonical_task_name",
    "capsule_sha256",
    "mission",
    "schema_version",
    "shortest_valid_route",
    "task_packet",
}


class NativeTuraPacketError(ValueError):
    """Stable typed rejection for malformed or conflicting task input."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class NativeTuraTaskCapsule:
    """One verified task-name binding around an existing TaskPacket."""

    canonical_task_name: str
    mission: str
    shortest_valid_route: str
    task_packet: TaskPacket
    callback_id: str
    capsule_sha256: str

    @property
    def parent_thread_id(self) -> str:
        return self.task_packet.destination.thread_id

    def to_wire(self) -> dict[str, Any]:
        return {
            **_capsule_payload(
                canonical_task_name=self.canonical_task_name,
                mission=self.mission,
                shortest_valid_route=self.shortest_valid_route,
                task_packet=self.task_packet,
                callback_id=self.callback_id,
            ),
            "capsule_sha256": self.capsule_sha256,
        }

    def render_task(self) -> str:
        packet = self.task_packet
        return "\n".join(
            (
                "MISSION",
                self.mission,
                "",
                "FIRST_FALSE_PREDICATE",
                packet.predicate_key,
                "",
                "SHORTEST_VALID_ROUTE",
                self.shortest_valid_route,
                "",
                "EXPECTED_PREDICATE_DELTA",
                packet.expected_delta,
                "",
                "ABANDON_IF",
                packet.abandon_if,
                "",
                "NATIVE_TASK_BINDING",
                f"canonical_task_name={self.canonical_task_name}",
                f"packet_id={packet.packet_id}",
                f"capsule_sha256={self.capsule_sha256}",
                f"parent_thread_id={self.parent_thread_id}",
                f"callback_id={self.callback_id}",
                f"mission_revision={packet.mission_revision}",
                f"mission_mode={packet.mission_mode}",
                f"route_id={packet.route_id}",
                f"executor_id={packet.executor_id}",
                f"scope={json.dumps(packet.scope, ensure_ascii=True)}",
                f"scope_versions={json.dumps(packet.scope_versions, ensure_ascii=True)}",
                f"recovery_budget={packet.recovery_budget}",
            )
        ) + "\n"


def default_native_tura_packet_root() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return codex_home / "tura-kernel" / "packets"


def publish_native_tura_task_capsule(
    *,
    canonical_task_name: str,
    mission: str,
    shortest_valid_route: str,
    task_packet: TaskPacket,
    root: str | os.PathLike[str] | None = None,
) -> Path:
    """Atomically publish one immutable capsule for a unique Native task name."""

    task_name = _require_task_name(canonical_task_name)
    mission_text = _require_text("mission", mission)
    route_text = _require_text("shortest_valid_route", shortest_valid_route)
    task_packet = _decode_task_packet(_encode_task_packet(task_packet))

    callback_id = _callback_id(task_name, mission_text, route_text, task_packet)
    payload = _capsule_payload(
        canonical_task_name=task_name,
        mission=mission_text,
        shortest_valid_route=route_text,
        task_packet=task_packet,
        callback_id=callback_id,
    )
    capsule_sha256 = canonical_sha256(payload)
    wire = {**payload, "capsule_sha256": capsule_sha256}
    encoded = _canonical_json_bytes(wire)
    if len(encoded) > MAX_CAPSULE_BYTES:
        raise NativeTuraPacketError(
            "TASK_CAPSULE_TOO_LARGE",
            f"capsule is {len(encoded)} bytes; maximum is {MAX_CAPSULE_BYTES}",
        )

    packet_root = Path(root) if root is not None else default_native_tura_packet_root()
    packet_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _require_plain_root(packet_root)
    task_dir = packet_root / _task_directory_name(task_name)
    task_dir.mkdir(mode=0o700, exist_ok=True)
    _require_plain_directory(task_dir, packet_root)
    target = task_dir / f"{capsule_sha256}.json"

    existing = _capsule_files(task_dir)
    if existing:
        if len(existing) == 1 and existing[0] == target:
            loaded = load_native_tura_task_capsule(task_name, root=packet_root)
            if loaded.to_wire() == wire:
                return target
        raise NativeTuraPacketError(
            "TASK_PACKET_PREIMAGE_DRIFT",
            f"canonical task {task_name!r} already has different input",
        )

    descriptor, temporary_name = tempfile.mkstemp(
        dir=task_dir, prefix=".capsule.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, target, follow_symlinks=False)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            loaded = load_native_tura_task_capsule(task_name, root=packet_root)
            if loaded.to_wire() != wire:
                raise NativeTuraPacketError(
                    "TASK_PACKET_PREIMAGE_DRIFT",
                    f"canonical task {task_name!r} raced with different input",
                ) from None
        _fsync_directory(task_dir)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def load_native_tura_task_capsule(
    canonical_task_name: str,
    *,
    root: str | os.PathLike[str] | None = None,
) -> NativeTuraTaskCapsule:
    """Load and independently verify the sole capsule for a Native task name."""

    task_name = _require_task_name(canonical_task_name)
    packet_root = Path(root) if root is not None else default_native_tura_packet_root()
    if not packet_root.exists():
        raise NativeTuraPacketError(
            "TASK_PACKET_NOT_FOUND", f"no capsule exists for {task_name!r}"
        )
    _require_plain_root(packet_root)
    task_dir = packet_root / _task_directory_name(task_name)
    if not task_dir.exists():
        raise NativeTuraPacketError(
            "TASK_PACKET_NOT_FOUND", f"no capsule exists for {task_name!r}"
        )
    _require_plain_directory(task_dir, packet_root)
    files = _capsule_files(task_dir)
    if len(files) != 1:
        raise NativeTuraPacketError(
            "TASK_PACKET_CARDINALITY_INVALID",
            f"expected exactly one capsule for {task_name!r}, found {len(files)}",
        )
    path = files[0]
    if path.is_symlink() or not path.is_file():
        raise NativeTuraPacketError(
            "TASK_PACKET_MEMBER_INVALID", "capsule must be a regular non-symlink file"
        )
    metadata = path.stat()
    if stat.S_IMODE(metadata.st_mode) != 0o444 or metadata.st_nlink != 1:
        raise NativeTuraPacketError(
            "TASK_PACKET_MEMBER_MUTABLE",
            "capsule must have mode 0444 and exactly one filesystem link",
        )
    size = metadata.st_size
    if size > MAX_CAPSULE_BYTES:
        raise NativeTuraPacketError(
            "TASK_CAPSULE_TOO_LARGE",
            f"capsule is {size} bytes; maximum is {MAX_CAPSULE_BYTES}",
        )
    try:
        wire = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise NativeTuraPacketError("TASK_PACKET_JSON_INVALID", str(error)) from error
    if not isinstance(wire, dict):
        raise NativeTuraPacketError("TASK_PACKET_JSON_INVALID", "capsule must be an object")
    _require_exact_keys("capsule", wire, _CAPSULE_KEYS)
    if wire["schema_version"] != NATIVE_TURA_CAPSULE_VERSION:
        raise NativeTuraPacketError(
            "TASK_CAPSULE_VERSION_UNSUPPORTED", str(wire["schema_version"])
        )
    if wire["canonical_task_name"] != task_name:
        raise NativeTuraPacketError(
            "TASK_NAME_BINDING_MISMATCH", "capsule is bound to a different task name"
        )

    packet = _decode_task_packet(wire["task_packet"])
    mission = _require_text("mission", wire["mission"])
    route = _require_text("shortest_valid_route", wire["shortest_valid_route"])
    expected_callback = _callback_id(task_name, mission, route, packet)
    if wire["callback_id"] != expected_callback:
        raise NativeTuraPacketError(
            "CALLBACK_IDENTITY_MISMATCH", "callback does not bind the exact task input"
        )
    payload = {key: wire[key] for key in wire if key != "capsule_sha256"}
    expected_capsule_sha256 = canonical_sha256(payload)
    if wire["capsule_sha256"] != expected_capsule_sha256:
        raise NativeTuraPacketError(
            "TASK_CAPSULE_IDENTITY_MISMATCH", "capsule digest cannot be recomputed"
        )
    if path.stem != expected_capsule_sha256:
        raise NativeTuraPacketError(
            "TASK_CAPSULE_PATH_MISMATCH", "capsule filename differs from its digest"
        )
    return NativeTuraTaskCapsule(
        canonical_task_name=task_name,
        mission=mission,
        shortest_valid_route=route,
        task_packet=packet,
        callback_id=expected_callback,
        capsule_sha256=expected_capsule_sha256,
    )


def _capsule_payload(
    *,
    canonical_task_name: str,
    mission: str,
    shortest_valid_route: str,
    task_packet: TaskPacket,
    callback_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": NATIVE_TURA_CAPSULE_VERSION,
        "canonical_task_name": canonical_task_name,
        "mission": mission,
        "shortest_valid_route": shortest_valid_route,
        "task_packet": _encode_task_packet(task_packet),
        "callback_id": callback_id,
    }


def _encode_task_packet(packet: TaskPacket) -> dict[str, Any]:
    return {
        "mission_id": packet.mission_id,
        "mission_revision": packet.mission_revision,
        "mission_mode": packet.mission_mode,
        "predicate_key": packet.predicate_key,
        "route_id": packet.route_id,
        "executor_id": packet.executor_id,
        "scope": list(packet.scope),
        "scope_versions": [list(item) for item in packet.scope_versions],
        "expected_delta": packet.expected_delta,
        "abandon_if": packet.abandon_if,
        "recovery_budget": packet.recovery_budget,
        "destination": {
            "coordinator_id": packet.destination.coordinator_id,
            "thread_id": packet.destination.thread_id,
        },
        "packet_id": packet.packet_id,
    }


def _decode_task_packet(value: object) -> TaskPacket:
    if not isinstance(value, dict):
        raise NativeTuraPacketError("TASK_PACKET_SHAPE_INVALID", "task_packet must be an object")
    _require_exact_keys("task_packet", value, _PACKET_KEYS)
    destination = value["destination"]
    if not isinstance(destination, dict):
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID", "destination must be an object"
        )
    _require_exact_keys(
        "destination", destination, {"coordinator_id", "thread_id"}
    )
    scope = _text_sequence("scope", value["scope"])
    raw_scope_versions = value["scope_versions"]
    if not isinstance(raw_scope_versions, list):
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID", "scope_versions must be an array"
        )
    scope_versions: list[tuple[str, int]] = []
    for index, item in enumerate(raw_scope_versions):
        if not isinstance(item, list) or len(item) != 2:
            raise NativeTuraPacketError(
                "TASK_PACKET_SHAPE_INVALID",
                f"scope_versions[{index}] must contain scope and integer revision",
            )
        scope_versions.append(
            (
                _require_text(f"scope_versions[{index}][0]", item[0]),
                _require_int(f"scope_versions[{index}][1]", item[1]),
            )
        )
    packet = TaskPacket(
        mission_id=_require_text("mission_id", value["mission_id"]),
        mission_revision=_require_int("mission_revision", value["mission_revision"]),
        mission_mode=_require_text("mission_mode", value["mission_mode"]),
        predicate_key=_require_text("predicate_key", value["predicate_key"]),
        route_id=_require_text("route_id", value["route_id"]),
        executor_id=_require_text("executor_id", value["executor_id"]),
        scope=scope,
        scope_versions=tuple(scope_versions),
        expected_delta=_require_text("expected_delta", value["expected_delta"]),
        abandon_if=_require_text("abandon_if", value["abandon_if"]),
        recovery_budget=_require_int("recovery_budget", value["recovery_budget"]),
        destination=Destination(
            coordinator_id=_require_text(
                "destination.coordinator_id", destination["coordinator_id"]
            ),
            thread_id=_require_text("destination.thread_id", destination["thread_id"]),
        ),
    )
    if value["packet_id"] != packet.packet_id or not verify_identity(packet):
        raise NativeTuraPacketError(
            "TASK_PACKET_IDENTITY_MISMATCH", "packet_id cannot be recomputed"
        )
    return packet


def _callback_id(
    task_name: str, mission: str, shortest_valid_route: str, packet: TaskPacket
) -> str:
    return "tura_callback_" + canonical_sha256(
        {
            "canonical_task_name": task_name,
            "mission": mission,
            "shortest_valid_route": shortest_valid_route,
            "packet_id": packet.packet_id,
            "parent_thread_id": packet.destination.thread_id,
        }
    )


def _task_directory_name(task_name: str) -> str:
    return "task-" + canonical_sha256({"canonical_task_name": task_name})


def _capsule_files(task_dir: Path) -> list[Path]:
    members = sorted(task_dir.iterdir())
    invalid = [path.name for path in members if path.suffix != ".json"]
    if invalid:
        raise NativeTuraPacketError(
            "TASK_PACKET_DIRECTORY_MEMBERS_INVALID",
            f"unexpected task packet members: {invalid}",
        )
    return members


def _require_plain_root(packet_root: Path) -> None:
    if packet_root.is_symlink() or not packet_root.is_dir():
        raise NativeTuraPacketError(
            "TASK_PACKET_ROOT_INVALID", "task packet root must be a plain directory"
        )


def _require_plain_directory(task_dir: Path, packet_root: Path) -> None:
    if task_dir.is_symlink() or not task_dir.is_dir():
        raise NativeTuraPacketError(
            "TASK_PACKET_DIRECTORY_INVALID", "task packet directory must be plain"
        )
    if task_dir.resolve().parent != packet_root.resolve():
        raise NativeTuraPacketError(
            "TASK_PACKET_DIRECTORY_ESCAPE", "task packet directory escaped its root"
        )


def _require_task_name(value: object) -> str:
    task_name = _require_text("canonical_task_name", value)
    if len(task_name) > 512 or not _CANONICAL_TASK_NAME.fullmatch(task_name):
        raise NativeTuraPacketError(
            "CANONICAL_TASK_NAME_INVALID",
            "expected /root followed by lowercase task-name path segments",
        )
    return task_name


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID", f"{name} must be a non-empty string"
        )
    return value


def _require_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID", f"{name} must be an integer"
        )
    return value


def _text_sequence(name: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID", f"{name} must be an array"
        )
    return tuple(_require_text(f"{name}[{index}]", item) for index, item in enumerate(value))


def _require_exact_keys(name: str, value: dict[str, Any], expected: set[str]) -> None:
    actual = set(value)
    if actual != expected:
        raise NativeTuraPacketError(
            "TASK_PACKET_SHAPE_INVALID",
            f"{name} keys differ; missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}",
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise NativeTuraPacketError(
                "TASK_PACKET_JSON_DUPLICATE_KEY", f"duplicate key {key!r}"
            )
        value[key] = item
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    load = subparsers.add_parser("load", help="load one task-bound capsule")
    load.add_argument("--task-name", required=True)
    load.add_argument("--format", choices=("json", "task"), default="task")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
        if args.command == "load":
            capsule = load_native_tura_task_capsule(args.task_name, root=args.root)
            if args.format == "json":
                print(json.dumps(capsule.to_wire(), sort_keys=True))
            else:
                print(capsule.render_task(), end="")
            return 0
        raise AssertionError(f"unhandled command: {args.command}")
    except NativeTuraPacketError as error:
        print(
            json.dumps(
                {"status": "rejected", "code": error.code, "detail": error.detail},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
