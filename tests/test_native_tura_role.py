# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from codex_collaboration_harness import Destination, TaskPacket
from codex_collaboration_harness.native_tura import (
    NativeTuraPacketError,
    load_native_tura_task_capsule,
    main,
    publish_native_tura_task_capsule,
)


TASK_NAME = "/root/native_tura_p1"


def make_packet(*, revision: int = 1) -> TaskPacket:
    return TaskPacket(
        mission_id="mission.native-tura",
        mission_revision=revision,
        mission_mode="delivery",
        predicate_key="native_task_input_loaded",
        route_id="route.native-task-capsule",
        executor_id="executor.tura.native",
        scope=("artifact:native-task-input",),
        scope_versions=(("artifact:native-task-input", 1),),
        expected_delta="the Native Tura child loads the exact bounded task input",
        abandon_if="the route requires a Codex binary patch or second lifecycle store",
        recovery_budget=1,
        destination=Destination(
            coordinator_id="commander.native",
            thread_id="thread.native.parent",
        ),
    )


class NativeTuraTaskCapsuleTests(unittest.TestCase):
    def test_publish_load_and_render_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet = make_packet()
            path = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Read the capsule, then use Native Codex tools.",
                task_packet=packet,
                root=root,
            )

            loaded = load_native_tura_task_capsule(TASK_NAME, root=root)

            self.assertEqual(loaded.task_packet, packet)
            self.assertEqual(path.stem, loaded.capsule_sha256)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
            self.assertEqual(path.stat().st_nlink, 1)
            rendered = loaded.render_task()
            for field in (
                "MISSION",
                "FIRST_FALSE_PREDICATE",
                "SHORTEST_VALID_ROUTE",
                "EXPECTED_PREDICATE_DELTA",
                "ABANDON_IF",
                packet.packet_id,
                loaded.callback_id,
                packet.destination.thread_id,
            ):
                self.assertIn(field, rendered)

    def test_identical_publish_is_noop_and_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = {
                "canonical_task_name": TASK_NAME,
                "mission": "Run one bounded Native Tura task.",
                "shortest_valid_route": "Use Native Codex only.",
                "task_packet": make_packet(),
                "root": root,
            }
            first = publish_native_tura_task_capsule(**arguments)
            second = publish_native_tura_task_capsule(**arguments)
            self.assertEqual(first, second)

            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_PREIMAGE_DRIFT"
            ):
                publish_native_tura_task_capsule(
                    **{**arguments, "mission": "A different mission."}
                )

    def test_tampered_capsule_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(),
                root=root,
            )
            wire = json.loads(path.read_text(encoding="ascii"))
            wire["mission"] = "tampered"
            os.chmod(path, 0o644)
            path.write_text(json.dumps(wire), encoding="ascii")
            os.chmod(path, 0o444)

            with self.assertRaisesRegex(
                NativeTuraPacketError, "CALLBACK_IDENTITY_MISMATCH"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

    def test_task_name_cannot_escape_packet_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                NativeTuraPacketError, "CANONICAL_TASK_NAME_INVALID"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name="/root/../escape",
                    mission="Run one bounded Native Tura task.",
                    shortest_valid_route="Use Native Codex only.",
                    task_packet=make_packet(),
                    root=temporary,
                )

    def test_same_task_name_cannot_acquire_a_second_packet_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(),
                root=root,
            )
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_PREIMAGE_DRIFT"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one bounded Native Tura task.",
                    shortest_valid_route="Use Native Codex only.",
                    task_packet=make_packet(revision=2),
                    root=root,
                )

    def test_mutable_or_linked_capsule_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(),
                root=root,
            )
            os.chmod(path, 0o644)
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_MEMBER_MUTABLE"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

            os.chmod(path, 0o444)
            os.link(path, path.with_suffix(".copy.json"))
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_CARDINALITY_INVALID"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(),
                root=root,
            )
            text = path.read_text(encoding="ascii")
            os.chmod(path, 0o644)
            path.write_text(text.replace('{"callback_id":', '{"callback_id":"x","callback_id":', 1), encoding="ascii")
            os.chmod(path, 0o444)
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_JSON_DUPLICATE_KEY"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

    def test_cli_returns_typed_missing_capsule_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "--root",
                        temporary,
                        "load",
                        "--task-name",
                        TASK_NAME,
                        "--format",
                        "task",
                    ]
                )

            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout.getvalue(), "")
            error = json.loads(stderr.getvalue())
            self.assertEqual(error["status"], "rejected")
            self.assertEqual(error["code"], "TASK_PACKET_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
