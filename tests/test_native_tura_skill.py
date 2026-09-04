# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
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


EXPECTED_DIGESTS = {
    "SKILL.md": "d0cd6914ad6c76a271d06db6a6c1578149f3251bc4df25ee1aeb76a6a383702d",
    "agents/openai.yaml": "afd2cefb13e0c8c54ba7f0ed2c54c6dcbfac9fba514415d8e6a518bf396bc0c8",
    "references/native-topology.md": "df83e8637a7434e50fd1eee86c8c80626cd2d79ab002667e8301571ae93855e5",
}


class NativeTuraSkillTests(unittest.TestCase):
    def test_reasoning_effort_contract_is_max(self) -> None:
        self.assertEqual(NATIVE_TURA_REASONING_EFFORT, "max")

    def test_packaged_members_match_reviewed_identity(self) -> None:
        root = files("codex_collaboration_harness").joinpath(
            "skills", "tura-kernel"
        )
        self.assertEqual(set(NATIVE_TURA_SKILL_MEMBERS), set(EXPECTED_DIGESTS))
        for relative, expected in EXPECTED_DIGESTS.items():
            payload = root.joinpath(*relative.split("/")).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected)

    def test_install_is_atomic_and_identical_replay_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary) / "codex-home"

            installed = install_native_tura_skill(codex_home=codex_home)
            replayed = install_native_tura_skill(codex_home=codex_home)

            self.assertEqual(installed["status"], "installed")
            self.assertEqual(replayed["status"], "unchanged")
            self.assertEqual(installed["members"], EXPECTED_DIGESTS)
            target = codex_home / "skills" / "tura-kernel"
            for relative, expected in EXPECTED_DIGESTS.items():
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
            self.assertEqual(receipt["members"], EXPECTED_DIGESTS)
            self.assertEqual(receipt["reasoning_effort"], "max")


if __name__ == "__main__":
    unittest.main()
