# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

from codex_collaboration_harness import (
    Destination,
    TaskContextBinding,
    TaskPacket,
    canonical_sha256,
)
from codex_collaboration_harness.native_tura import (
    LEGACY_NATIVE_TURA_CAPSULE_VERSION,
    NATIVE_TURA_CAPSULE_VERSION,
    NativeTuraPacketError,
    load_native_tura_task_capsule,
    main,
    publish_native_tura_task_capsule,
)


TASK_NAME = "/root/native_tura_p1"


def make_packet(
    *,
    revision: int = 1,
    task_context_binding: TaskContextBinding | None = None,
) -> TaskPacket:
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
        task_context_binding=task_context_binding,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _write_context_pair(
    root: Path,
    *,
    task_id: str = "v2-release-pointer",
    generation_id: str = "generation-current",
    input_fingerprint: str = "1" * 64,
    data: dict[str, object] | None = None,
    oracle_key: str | None = None,
    context_oracle_key: str | None = None,
    jspace_oracle_key: str | None = None,
    mission_overrides: dict[str, object] | None = None,
    projection_schema_version: str = "task-context-projection/v1",
    jspace_version: int = 1,
) -> TaskContextBinding:
    generation = {
        "generated_at": "2026-09-04T00:00:00+00:00",
        "generation_id": generation_id,
        "input_fingerprint": input_fingerprint,
        "repo_head": "2" * 40,
        "required_capabilities": ["surface-map", "verifier-gates"],
        "worktree_fingerprint": "3" * 64,
    }
    target = f"task:{task_id}"
    provenance: dict[str, object] = {
        "surface_contract": "surface.json",
        "matched_surface_ids": ["authority_contracts_policy"],
        "authority_contract": "authority.json",
    }
    if jspace_oracle_key is not None:
        provenance[jspace_oracle_key] = "forbidden"
    jspace: dict[str, object] = {
        "schema_version": f"jspace_contract_v{jspace_version}",
        "repo_root": "/workspace/frozen",
        "dcf_generation": generation,
        "provenance": provenance,
        "matched_surface_ids": ["authority_contracts_policy"],
        "read_scopes": ["**"],
        "write_scopes": [],
        "allowed_operations": ["command", "read"],
        "denied_operations": ["install", "network", "system_mutation"],
        "focused_verifiers": [],
        "declared_targets": [target],
        "expansion": {
            "mode": "exact_target_only",
            "error_code": "JSPACE_EXPANSION_REQUIRED",
            "mutation_on_expansion": False,
        },
    }
    if jspace_version == 1:
        jspace["command_prefixes"] = []
        jspace["semantic_sha256"] = canonical_sha256(jspace)
        jspace_semantic_sha256 = jspace["semantic_sha256"]
    elif jspace_version == 2:
        jspace["command_templates"] = []
        authorization_payload = {
            "schema_version": "jspace_authorization_v1",
            "repo_root": jspace["repo_root"],
            "required_domain_bindings": generation.get("required_domain_bindings"),
            "matched_surface_ids": jspace["matched_surface_ids"],
            "read_scopes": jspace["read_scopes"],
            "write_scopes": jspace["write_scopes"],
            "allowed_operations": jspace["allowed_operations"],
            "denied_operations": jspace["denied_operations"],
            "command_templates": jspace["command_templates"],
            "declared_targets": jspace["declared_targets"],
            "expansion": jspace["expansion"],
        }
        jspace["authorization_semantic_sha256"] = canonical_sha256(
            authorization_payload
        )
        jspace["content_sha256"] = canonical_sha256(jspace)
        jspace_semantic_sha256 = jspace["authorization_semantic_sha256"]
    else:
        raise ValueError("test fixture supports only J-Space v1 and v2")
    projection = {
        "schema_version": projection_schema_version,
        "task_id": task_id,
        "projection_kind": "release_authority",
        "target": "state:active_route",
        "capability_ids": ["current-state", "model-context"],
        "task_visible_pre_task_evidence_only": True,
        "answer_key_used": False,
        "data": data if data is not None else {"visible_fact": "bound"},
    }
    if oracle_key is not None:
        projection["data"] = {oracle_key: "forbidden"}
    mission: dict[str, object] = {
        "mission_id": "mission.native-tura",
        "mode": "delivery",
        "current_predicate": "native_task_input_loaded",
        "objective": "Use the task-local evidence.",
        "task_id": task_id,
    }
    if mission_overrides is not None:
        mission.update(mission_overrides)
    if context_oracle_key is not None:
        mission[context_oracle_key] = "forbidden"
    context = {
        "schema_version": "task_context_capsule_v1",
        "mission": mission,
        "context_summary": _canonical_json(projection),
        "dcf_generation": generation,
        "surface": {
            "repo_root": jspace["repo_root"],
            "matched_surface_ids": jspace["matched_surface_ids"],
            "declared_targets": jspace["declared_targets"],
        },
        "authority": {
            "forbidden_effects": ["repository_source", "trading"],
            "denied_operations": jspace["denied_operations"],
        },
        "evidence_refs": [
            {
                "id": f"{task_id}:jspace",
                "kind": "jspace_contract",
                "sha256": jspace_semantic_sha256,
            }
        ],
        "focused_verifiers": jspace["focused_verifiers"],
        "jspace_semantic_sha256": jspace_semantic_sha256,
    }
    context["semantic_sha256"] = canonical_sha256(context)

    context_path = root / "contexts" / f"{task_id}.json"
    jspace_path = root / "jspace" / f"{task_id}.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    jspace_path.parent.mkdir(parents=True, exist_ok=True)
    context_bytes = _canonical_json(context).encode("ascii")
    jspace_bytes = _canonical_json(jspace).encode("ascii")
    context_path.write_bytes(context_bytes)
    jspace_path.write_bytes(jspace_bytes)
    return TaskContextBinding(
        task_id=task_id,
        artifact_root=str(root),
        context_path=str(context_path.relative_to(root)),
        context_sha256=hashlib.sha256(context_bytes).hexdigest(),
        jspace_path=str(jspace_path.relative_to(root)),
        jspace_sha256=hashlib.sha256(jspace_bytes).hexdigest(),
        dcf_generation_id=generation_id,
        dcf_input_fingerprint=input_fingerprint,
    )


class NativeTuraTaskCapsuleTests(unittest.TestCase):
    def test_absent_context_preserves_legacy_packet_identity(self) -> None:
        self.assertEqual(
            make_packet().packet_id,
            "packet_46f5dd3a4dfb099017933ac22cc979b8f67c4bbfc0c226d2e868267d43dd7f54",
        )

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
            self.assertEqual(
                json.loads(path.read_text(encoding="ascii"))["schema_version"],
                LEGACY_NATIVE_TURA_CAPSULE_VERSION,
            )
            self.assertTrue(path.name.endswith(f"-{loaded.capsule_sha256}.json"))
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

    def test_context_round_trip_is_packet_bound_and_visible_to_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence")
            packet = make_packet(task_context_binding=binding)
            path = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one context-bound Native Tura task.",
                shortest_valid_route="Use only the bound task-local evidence.",
                task_packet=packet,
                root=root / "packets",
            )

            loaded = load_native_tura_task_capsule(TASK_NAME, root=root / "packets")

            self.assertEqual(loaded.task_packet, packet)
            self.assertEqual(
                json.loads(path.read_text(encoding="ascii"))["schema_version"],
                NATIVE_TURA_CAPSULE_VERSION,
            )
            self.assertIsNotNone(loaded.verified_task_context)
            rendered = loaded.render_task()
            self.assertIn("TASK_LOCAL_EVIDENCE", rendered)
            self.assertIn(f"task_id={binding.task_id}", rendered)
            self.assertIn(binding.dcf_generation_id, rendered)
            self.assertIn('"task_visible_pre_task_evidence_only":true', rendered)
            self.assertIn('"answer_key_used":false', rendered)
            self.assertIn('"schema_version":"jspace_contract_v1"', rendered)
            self.assertNotEqual(packet.packet_id, make_packet().packet_id)

    def test_current_jspace_v2_digests_are_verified_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence", jspace_version=2)
            publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one context-bound Native Tura task.",
                shortest_valid_route="Use only the bound task-local evidence.",
                task_packet=make_packet(task_context_binding=binding),
                root=root / "packets",
            )

            loaded = load_native_tura_task_capsule(TASK_NAME, root=root / "packets")

            self.assertIn(
                '"schema_version":"jspace_contract_v2"',
                loaded.render_task(),
            )

    def test_published_context_survives_external_reference_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root = root / "evidence"
            packet_root = root / "packets"
            binding = _write_context_pair(evidence_root)
            packet = make_packet(task_context_binding=binding)
            arguments = {
                "canonical_task_name": TASK_NAME,
                "mission": "Run one context-bound Native Tura task.",
                "shortest_valid_route": "Use only the bound task-local evidence.",
                "task_packet": packet,
                "root": packet_root,
            }
            published = publish_native_tura_task_capsule(**arguments)
            (evidence_root / binding.context_path).unlink()
            (evidence_root / binding.jspace_path).unlink()

            loaded = load_native_tura_task_capsule(TASK_NAME, root=packet_root)
            republished = publish_native_tura_task_capsule(**arguments)

            self.assertEqual(republished, published)
            self.assertIn("TASK_LOCAL_EVIDENCE", loaded.render_task())

    def test_context_reference_missing_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence")
            binding = replace(binding, context_path="contexts/missing.json")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_REFERENCE_MISSING"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=binding),
                    root=root / "packets",
                )
            self.assertEqual(list((root / "packets").rglob("*.json")), [])

    def test_context_file_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence")
            binding = replace(binding, context_sha256="0" * 64)
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_DIGEST_MISMATCH"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=binding),
                    root=root / "packets",
                )

    def test_context_generation_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence")
            stale = replace(binding, dcf_generation_id="generation-stale")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_GENERATION_MISMATCH"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=stale),
                    root=root / "packets",
                )

    def test_cross_task_context_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence")
            wrong_task = replace(binding, task_id="v2-first-blocker")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_TASK_MISMATCH"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=wrong_task),
                    root=root / "packets",
                )

    def test_context_mission_identity_must_match_task_packet(self) -> None:
        cases = (
            {"mission_id": "mission.other"},
            {"mode": "research"},
            {"current_predicate": "different_predicate"},
        )
        for overrides in cases:
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                binding = _write_context_pair(
                    root / "evidence", mission_overrides=overrides
                )
                with self.assertRaisesRegex(
                    NativeTuraPacketError, "TASK_CONTEXT_MISSION_MISMATCH"
                ):
                    publish_native_tura_task_capsule(
                        canonical_task_name=TASK_NAME,
                        mission="Run one context-bound Native Tura task.",
                        shortest_valid_route="Use only the bound task-local evidence.",
                        task_packet=make_packet(task_context_binding=binding),
                        root=root / "packets",
                    )

    def test_context_traversal_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root = root / "evidence"
            binding = _write_context_pair(evidence_root)
            traversal = replace(binding, context_path="../outside.json")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_REFERENCE_INVALID"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=traversal),
                    root=root / "packets-traversal",
                )

            original = evidence_root / binding.context_path
            link = evidence_root / "contexts" / "linked.json"
            link.symlink_to(original)
            symlink = replace(binding, context_path="contexts/linked.json")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_REFERENCE_INVALID"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=symlink),
                    root=root / "packets-symlink",
                )

    def test_oracle_marker_is_rejected_before_child_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(root / "evidence", oracle_key="answer_key")
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_ORACLE_MATERIAL_REJECTED"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=binding),
                    root=root / "packets",
                )

    def test_oracle_marker_outside_projection_is_rejected(self) -> None:
        cases = (
            {"context_oracle_key": "expected_answer"},
            {"jspace_oracle_key": "hidden_verifier_payload"},
        )
        for options in cases:
            with (
                self.subTest(options=options),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                binding = _write_context_pair(root / "evidence", **options)
                with self.assertRaisesRegex(
                    NativeTuraPacketError, "TASK_CONTEXT_ORACLE_MATERIAL_REJECTED"
                ):
                    publish_native_tura_task_capsule(
                        canonical_task_name=TASK_NAME,
                        mission="Run one context-bound Native Tura task.",
                        shortest_valid_route="Use only the bound task-local evidence.",
                        task_packet=make_packet(task_context_binding=binding),
                        root=root / "packets",
                    )

    def test_camel_case_oracle_marker_is_rejected(self) -> None:
        for oracle_key in (
            "answerKey",
            "expectedAnswer",
            "groundTruth",
            "hiddenVerifier",
            "scorerOutput",
        ):
            with (
                self.subTest(oracle_key=oracle_key),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                binding = _write_context_pair(root / "evidence", oracle_key=oracle_key)
                with self.assertRaisesRegex(
                    NativeTuraPacketError, "TASK_CONTEXT_ORACLE_MATERIAL_REJECTED"
                ):
                    publish_native_tura_task_capsule(
                        canonical_task_name=TASK_NAME,
                        mission="Run one context-bound Native Tura task.",
                        shortest_valid_route="Use only the bound task-local evidence.",
                        task_packet=make_packet(task_context_binding=binding),
                        root=root / "packets",
                    )

    def test_unknown_projection_structure_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = _write_context_pair(
                root / "evidence",
                projection_schema_version="task-context-projection/v2",
            )
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_PROJECTION_INVALID"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Run one context-bound Native Tura task.",
                    shortest_valid_route="Use only the bound task-local evidence.",
                    task_packet=make_packet(task_context_binding=binding),
                    root=root / "packets",
                )

    def test_explicit_null_context_binding_is_not_legacy_compatible(self) -> None:
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
            wire["task_packet"]["task_context_binding"] = None
            payload = {
                key: value for key, value in wire.items() if key != "capsule_sha256"
            }
            digest = canonical_sha256(payload)
            wire["capsule_sha256"] = digest
            replacement = path.with_name(f"{path.name[:20]}-{digest}.json")
            path.unlink()
            replacement.write_text(_canonical_json(wire), encoding="ascii")
            os.chmod(replacement, 0o444)

            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_CONTEXT_BINDING_INVALID"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

    def test_callback_identity_changes_only_when_bound_context_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_binding = _write_context_pair(
                root / "evidence-a", data={"visible_fact": "a"}
            )
            second_binding = _write_context_pair(
                root / "evidence-b", data={"visible_fact": "b"}
            )
            first_packet = make_packet(task_context_binding=first_binding)
            second_packet = make_packet(task_context_binding=second_binding)
            publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one context-bound Native Tura task.",
                shortest_valid_route="Use only the bound task-local evidence.",
                task_packet=first_packet,
                root=root / "packets-a",
            )
            publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one context-bound Native Tura task.",
                shortest_valid_route="Use only the bound task-local evidence.",
                task_packet=second_packet,
                root=root / "packets-b",
            )
            first = load_native_tura_task_capsule(TASK_NAME, root=root / "packets-a")
            second = load_native_tura_task_capsule(TASK_NAME, root=root / "packets-b")

            self.assertNotEqual(first_packet.packet_id, second_packet.packet_id)
            self.assertNotEqual(first.callback_id, second.callback_id)

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
                NativeTuraPacketError, "TASK_PACKET_REVISION_CONFLICT"
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

    def test_same_task_name_loads_latest_immutable_packet_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Run one bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(),
                root=root,
            )
            second = publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Resume the same bounded Native Tura task.",
                shortest_valid_route="Use the same Native child identity.",
                task_packet=make_packet(revision=2),
                root=root,
            )

            loaded = load_native_tura_task_capsule(TASK_NAME, root=root)

            self.assertNotEqual(first, second)
            self.assertEqual(loaded.task_packet.mission_revision, 2)
            self.assertEqual(
                loaded.mission, "Resume the same bounded Native Tura task."
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
                NativeTuraPacketError, "TASK_PACKET_DIRECTORY_MEMBERS_INVALID"
            ):
                load_native_tura_task_capsule(TASK_NAME, root=root)

    def test_older_unseen_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            publish_native_tura_task_capsule(
                canonical_task_name=TASK_NAME,
                mission="Resume the bounded Native Tura task.",
                shortest_valid_route="Use Native Codex only.",
                task_packet=make_packet(revision=2),
                root=root,
            )
            with self.assertRaisesRegex(
                NativeTuraPacketError, "TASK_PACKET_REVISION_STALE"
            ):
                publish_native_tura_task_capsule(
                    canonical_task_name=TASK_NAME,
                    mission="Stale task input.",
                    shortest_valid_route="Do not run this stale route.",
                    task_packet=make_packet(revision=1),
                    root=root,
                )

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
            path.write_text(
                text.replace('{"callback_id":', '{"callback_id":"x","callback_id":', 1),
                encoding="ascii",
            )
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
