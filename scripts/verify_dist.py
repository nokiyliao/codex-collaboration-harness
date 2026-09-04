# SPDX-License-Identifier: MIT
"""Verify one built wheel/sdist pair and write deterministic checksums."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
REQUIRED_PACKAGE_MEMBERS = (
    "codex_collaboration_harness/native_tura.py",
    "codex_collaboration_harness/agents/tura.toml",
    "codex_collaboration_harness/skills/tura-kernel/SKILL.md",
    "codex_collaboration_harness/skills/tura-kernel/agents/openai.yaml",
    "codex_collaboration_harness/skills/tura-kernel/references/native-topology.md",
    "codex_collaboration_harness/py.typed",
    "codex_collaboration_harness/protocol/tura_dispatch_request_v1.schema.json",
    "codex_collaboration_harness/protocol/tura_terminal_envelope_v1.schema.json",
    "codex_collaboration_harness/protocol/golden/tura_dispatch_request_v1.json",
    "codex_collaboration_harness/protocol/golden/tura_result_v1.json",
    "codex_collaboration_harness/protocol/golden/tura_failure_v1.json",
)
NATIVE_TURA_ROLE_SHA256 = (
    "2383fb6d65b3d9c71f6e5b972ae6718e723a3f684c9b55c9139a7c9fccba8983"
)
NATIVE_TURA_SKILL_SHA256 = {
    "codex_collaboration_harness/skills/tura-kernel/SKILL.md": (
        "d0cd6914ad6c76a271d06db6a6c1578149f3251bc4df25ee1aeb76a6a383702d"
    ),
    "codex_collaboration_harness/skills/tura-kernel/agents/openai.yaml": (
        "afd2cefb13e0c8c54ba7f0ed2c54c6dcbfac9fba514415d8e6a518bf396bc0c8"
    ),
    "codex_collaboration_harness/skills/tura-kernel/references/native-topology.md": (
        "df83e8637a7434e50fd1eee86c8c80626cd2d79ab002667e8301571ae93855e5"
    ),
}


def _single(pattern: str) -> Path:
    matches = sorted(DIST.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {pattern}, found {matches}")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_role_bytes(role_bytes: bytes, source: str) -> None:
    if hashlib.sha256(role_bytes).hexdigest() != NATIVE_TURA_ROLE_SHA256:
        raise RuntimeError(f"{source} Native Tura role digest differs")
    try:
        role = tomllib.loads(role_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError(f"{source} Native Tura role is invalid: {error}") from error
    if role.get("name") != "tura":
        raise RuntimeError(f"{source} Native Tura role name differs")


def _verify_members(wheel: Path, sdist: Path) -> None:
    role_member = "codex_collaboration_harness/agents/tura.toml"
    with zipfile.ZipFile(wheel) as archive:
        wheel_members = set(archive.namelist())
        _verify_role_bytes(archive.read(role_member), "wheel")
        for member, expected in NATIVE_TURA_SKILL_SHA256.items():
            if hashlib.sha256(archive.read(member)).hexdigest() != expected:
                raise RuntimeError(f"wheel {member} digest differs")
    for member in REQUIRED_PACKAGE_MEMBERS:
        if member not in wheel_members:
            raise RuntimeError(f"wheel is missing {member}")

    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        if any(item.issym() or item.islnk() for item in members):
            raise RuntimeError("sdist must not contain symlink or hardlink members")
        names = {item.name for item in members}
        role_matches = [
            item
            for item in members
            if item.name.endswith(f"/src/{role_member}") and item.isfile()
        ]
        if len(role_matches) != 1:
            raise RuntimeError(
                f"sdist must contain one Native Tura role, found {role_matches}"
            )
        role_stream = archive.extractfile(role_matches[0])
        if role_stream is None:
            raise RuntimeError("sdist Native Tura role cannot be read")
        _verify_role_bytes(role_stream.read(), "sdist")
        for member, expected in NATIVE_TURA_SKILL_SHA256.items():
            matches = [
                item
                for item in members
                if item.name.endswith(f"/src/{member}") and item.isfile()
            ]
            if len(matches) != 1:
                raise RuntimeError(f"sdist must contain one {member}")
            stream = archive.extractfile(matches[0])
            if stream is None or hashlib.sha256(stream.read()).hexdigest() != expected:
                raise RuntimeError(f"sdist {member} digest differs")
    for member in REQUIRED_PACKAGE_MEMBERS:
        suffix = f"/src/{member}"
        if not any(name.endswith(suffix) for name in names):
            raise RuntimeError(f"sdist is missing {member}")


def _verify_clean_install(wheel: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-dist-") as temporary:
        root = Path(temporary)
        venv = root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        python = venv / "bin" / "python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel.resolve()),
            ],
            check=True,
        )
        check = (
            "import hashlib, json, tomllib; "
            "from importlib.metadata import version; "
            "from importlib.resources import files; "
            "import codex_collaboration_harness as harness; "
            f"assert version('codex-collaboration-harness') == {version!r}; "
            "schema = files('codex_collaboration_harness').joinpath("
            "'protocol', 'tura_terminal_envelope_v1.schema.json'); "
            "assert json.loads(schema.read_text(encoding='utf-8'))"
            "['properties']['protocol_version']['const'] == "
            "'tura-collaboration/v1'; "
            "role = files('codex_collaboration_harness').joinpath("
            "'agents', 'tura.toml'); "
            "role_bytes = role.read_bytes(); "
            f"assert hashlib.sha256(role_bytes).hexdigest() == "
            f"{NATIVE_TURA_ROLE_SHA256!r}; "
            "assert tomllib.loads(role_bytes.decode('utf-8'))['name'] == 'tura'; "
            "skill = files('codex_collaboration_harness').joinpath("
            "'skills', 'tura-kernel', 'SKILL.md'); "
            "assert hashlib.sha256(skill.read_bytes()).hexdigest() == "
            f"{NATIVE_TURA_SKILL_SHA256['codex_collaboration_harness/skills/tura-kernel/SKILL.md']!r}; "
            "print(harness.__file__)"
        )
        subprocess.run([str(python), "-I", "-c", check], cwd=root, check=True)
        subprocess.run(
            [str(venv / "bin" / "tura-taskpacket"), "--help"],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        codex_home = root / "codex-home"
        install = subprocess.run(
            [
                str(venv / "bin" / "tura-taskpacket"),
                "install-skill",
                "--codex-home",
                str(codex_home),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        receipt = json.loads(install.stdout)
        if receipt["members"] != {
            member.removeprefix("codex_collaboration_harness/skills/tura-kernel/"): digest
            for member, digest in NATIVE_TURA_SKILL_SHA256.items()
        }:
            raise RuntimeError("installed Native Tura Skill receipt differs")
        subprocess.run([str(python), "-m", "pip", "check"], cwd=root, check=True)


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    wheel = _single("*.whl")
    sdist = _single("*.tar.gz")
    _verify_members(wheel, sdist)
    _verify_clean_install(wheel, version)

    artifacts = sorted((wheel, sdist), key=lambda path: path.name)
    checksum_path = DIST / "SHA256SUMS"
    lines = [f"{_sha256(path)}  {path.name}" for path in artifacts]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    for line, path in zip(lines, artifacts, strict=True):
        expected = line.split()[0]
        if _sha256(path) != expected:
            raise RuntimeError(f"checksum changed after publication for {path.name}")
    print(
        json.dumps(
            {
                "version": version,
                "wheel": wheel.name,
                "sdist": sdist.name,
                "checksums": checksum_path.name,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
