# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from importlib.resources import files
from io import StringIO
from pathlib import Path

from codex_collaboration_harness.native_tura import (
    NATIVE_TURA_REASONING_EFFORT,
    NATIVE_TURA_SKILL_MEMBERS,
    NativeTuraPacketError,
    install_native_tura_skill,
    main,
)
import codex_collaboration_harness.native_tura as native_tura


def _expected_digests() -> dict[str, str]:
    root = files("codex_collaboration_harness").joinpath("skills", "tura-kernel")
    return {
        relative: hashlib.sha256(
            root.joinpath(*relative.split("/")).read_bytes()
        ).hexdigest()
        for relative in NATIVE_TURA_SKILL_MEMBERS
    }


class NativeTuraSkillTests(unittest.TestCase):
    def test_reasoning_effort_contract_is_max(self) -> None:
        self.assertEqual(NATIVE_TURA_REASONING_EFFORT, "max")

    def test_packaged_members_expose_the_native_contract(self) -> None:
        root = files("codex_collaboration_harness").joinpath(
            "skills", "tura-kernel"
        )
        self.assertEqual(
            set(NATIVE_TURA_SKILL_MEMBERS),
            {"SKILL.md", "agents/openai.yaml", "references/native-topology.md"},
        )
        skill = root.joinpath("SKILL.md").read_text(encoding="utf-8")
        self.assertIn("[TURA_NATIVE_TERMINAL_V1]", skill)
        self.assertIn("send_message_to_thread", skill)
        self.assertIn("thinking=\"max\"", skill)
        self.assertIn("NATIVE_TURA_READ_ONLY_FAST_PATH_V1", skill)
        self.assertIn("one Native batched-read stage", skill)
        self.assertIn("do not spend provider turns narrating", skill)
        self.assertIn("The parent performs exact callback intake", skill)

    def test_install_is_atomic_and_identical_replay_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"

            installed = install_native_tura_skill(codex_home=codex_home)
            replayed = install_native_tura_skill(codex_home=codex_home)
            expected_digests = _expected_digests()

            self.assertEqual(installed["status"], "installed")
            self.assertEqual(replayed["status"], "unchanged")
            self.assertEqual(installed["members"], expected_digests)
            self.assertEqual(
                installed["skill_contract"], replayed["skill_contract"]
            )
            self.assertEqual(
                installed["skill_contract"]["schema_version"],
                "tura-kernel-skill-contract/v1",
            )
            target = codex_home / "skills" / "tura-kernel"
            for relative, expected in expected_digests.items():
                self.assertEqual(
                    hashlib.sha256((target / relative).read_bytes()).hexdigest(),
                    expected,
                )

    def test_install_rejects_existing_drift_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"
            install_native_tura_skill(codex_home=codex_home)
            skill = codex_home / "skills" / "tura-kernel" / "SKILL.md"
            skill.write_text("operator-owned drift\n", encoding="utf-8")

            with self.assertRaises(NativeTuraPacketError) as raised:
                install_native_tura_skill(codex_home=codex_home)

            self.assertEqual(raised.exception.code, "SKILL_TARGET_PREIMAGE_DRIFT")
            self.assertEqual(skill.read_text(encoding="utf-8"), "operator-owned drift\n")

    def test_explicit_replace_updates_drift_and_returns_preimage_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"
            install_native_tura_skill(codex_home=codex_home)
            skill = codex_home / "skills" / "tura-kernel" / "SKILL.md"
            skill.write_text("old installed bytes\n", encoding="utf-8")
            old_sha256 = hashlib.sha256(skill.read_bytes()).hexdigest()

            receipt = install_native_tura_skill(
                codex_home=codex_home, replace=True
            )

            self.assertEqual(receipt["status"], "updated")
            self.assertEqual(
                receipt["previous_members"]["SKILL.md"], old_sha256
            )
            self.assertEqual(receipt["members"], _expected_digests())
            self.assertEqual(
                list((codex_home / "skills").glob(".tura-kernel.*")), []
            )

    def test_explicit_replace_restores_preimage_when_verification_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"
            install_native_tura_skill(codex_home=codex_home)
            target = codex_home / "skills" / "tura-kernel"
            skill = target / "SKILL.md"
            skill.write_text("old installed bytes\n", encoding="utf-8")
            original_verify = native_tura._verify_native_tura_skill_target

            def fail_new_target(path: Path, payloads: dict[str, bytes]) -> None:
                if (path / "SKILL.md").read_text(encoding="utf-8") != "old installed bytes\n":
                    raise NativeTuraPacketError(
                        "INJECTED_POST_REPLACE_FAILURE", "exercise rollback"
                    )
                original_verify(path, payloads)

            with mock.patch.object(
                native_tura,
                "_verify_native_tura_skill_target",
                side_effect=fail_new_target,
            ), self.assertRaisesRegex(
                NativeTuraPacketError, "INJECTED_POST_REPLACE_FAILURE"
            ):
                install_native_tura_skill(codex_home=codex_home, replace=True)

            self.assertEqual(skill.read_text(encoding="utf-8"), "old installed bytes\n")
            self.assertEqual(
                list((codex_home / "skills").glob(".tura-kernel.*")), []
            )

    def test_cli_installs_skill_and_returns_member_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    ["install-skill", "--codex-home", str(codex_home)]
                )

            self.assertEqual(exit_code, 0)
            receipt = json.loads(output.getvalue())
            self.assertEqual(receipt["status"], "installed")
            self.assertEqual(receipt["members"], _expected_digests())
            self.assertEqual(receipt["reasoning_effort"], "max")


if __name__ == "__main__":
    unittest.main()
