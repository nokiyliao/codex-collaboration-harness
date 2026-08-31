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
    "codex_collaboration_harness/py.typed",
    "codex_collaboration_harness/protocol/tura_dispatch_request_v1.schema.json",
    "codex_collaboration_harness/protocol/tura_terminal_envelope_v1.schema.json",
    "codex_collaboration_harness/protocol/golden/tura_dispatch_request_v1.json",
    "codex_collaboration_harness/protocol/golden/tura_result_v1.json",
    "codex_collaboration_harness/protocol/golden/tura_failure_v1.json",
)


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


def _verify_members(wheel: Path, sdist: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        wheel_members = set(archive.namelist())
    for member in REQUIRED_PACKAGE_MEMBERS:
        if member not in wheel_members:
            raise RuntimeError(f"wheel is missing {member}")

    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        if any(item.issym() or item.islnk() for item in members):
            raise RuntimeError("sdist must not contain symlink or hardlink members")
        names = {item.name for item in members}
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
            "import json; "
            "from importlib.metadata import version; "
            "from importlib.resources import files; "
            "import codex_collaboration_harness as harness; "
            f"assert version('codex-collaboration-harness') == {version!r}; "
            "schema = files('codex_collaboration_harness').joinpath("
            "'protocol', 'tura_terminal_envelope_v1.schema.json'); "
            "assert json.loads(schema.read_text(encoding='utf-8'))"
            "['properties']['protocol_version']['const'] == "
            "'tura-collaboration/v1'; "
            "print(harness.__file__)"
        )
        subprocess.run([str(python), "-I", "-c", check], cwd=root, check=True)
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
