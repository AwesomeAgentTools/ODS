#!/usr/bin/env python3
"""Offline-mode model validation contracts.

ODS has two offline readiness checkers — scripts/validate-models.py and
scripts/check-offline-models.sh. Both have to agree with what the installer
actually puts on disk:

  * models are fetched with scripts/download-hf-snapshot.py, i.e.
    snapshot_download(cache_dir=...), which writes ``models--<org>--<name>``
  * data/whisper is mounted into the container as the HuggingFace hub cache
    (extensions/services/whisper/compose.yaml)
  * the model ids are pinned per backend in .env (NVIDIA gets a larger STT
    model than AMD/CPU)

Run: python3 tests/test-offline-model-validation.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALIDATE_PY = ROOT / "scripts" / "validate-models.py"
CHECK_SH = ROOT / "scripts" / "check-offline-models.sh"

# Failure output echoes the checkers' ✓/✗ marks. Keep a non-UTF-8 console from
# turning a reported failure into an encoding traceback.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS = 0
FAIL = 0


def ok(label: str) -> None:
    global PASS
    print(f"[PASS] {label}")
    PASS += 1


def bad(label: str, detail: str) -> None:
    global FAIL
    print(f"[FAIL] {label}")
    print(f"       {detail}")
    FAIL += 1


def check(label: str, condition: bool, detail: str = "") -> None:
    ok(label) if condition else bad(label, detail)


@contextlib.contextmanager
def temp_root():
    """Scratch install root.

    Not TemporaryDirectory: a subprocess uses this tree as its working
    directory, and on Windows the handle can outlive the process just long
    enough to make cleanup raise. Cleanup noise must not fail the suite.
    """
    path = Path(tempfile.mkdtemp())
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_models", VALIDATE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_root(tmp: Path, *, layout: str, stt_model: str, embedding_model: str) -> Path:
    """Create an install root populated in the given on-disk layout."""
    (tmp / "data" / "models").mkdir(parents=True)
    (tmp / "data" / "models" / "model.gguf").write_bytes(b"gguf")
    (tmp / "data" / "kokoro" / "voices").mkdir(parents=True)
    (tmp / "data" / "kokoro" / "voices" / "af_heart.pt").write_bytes(b"voice")

    def place(cache: str, repo_id: str) -> None:
        root = tmp / "data" / cache
        if layout == "hf-cache":
            target = root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "abc"
        else:
            target = root / repo_id
        target.mkdir(parents=True)
        (target / "weights.bin").write_bytes(b"w")

    place("whisper", stt_model)
    place("embeddings", embedding_model)

    (tmp / ".env").write_text(
        f"ODS_MODE=local\nAUDIO_STT_MODEL={stt_model}\nEMBEDDING_MODEL={embedding_model}\n",
        encoding="utf-8",
    )
    return tmp


def run_validator(root: Path) -> str:
    # The checkers print ✓/✗; force UTF-8 so a non-UTF-8 console encoding on the
    # test host cannot turn a passing check into an encoding traceback.
    env = dict(os.environ, ODS_ROOT=str(root), PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(VALIDATE_PY)],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace",
    )
    return (proc.stdout or "") + (proc.stderr or "")


def run_shell_checker(root: Path) -> str:
    """check-offline-models.sh resolves its root from its own location."""
    scripts_dir = root / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    copy = scripts_dir / CHECK_SH.name
    copy.write_bytes(CHECK_SH.read_bytes())
    # Hand bash a bare filename and let Python set the working directory. A
    # Windows-style absolute path is not resolvable by bash on a Windows
    # checkout, and the resulting "No such file or directory" would quietly
    # satisfy every assertion made about this output.
    proc = subprocess.run(
        ["bash", CHECK_SH.name],
        cwd=str(scripts_dir),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    validator = load_validator()

    # ── Unit: repo id → on-disk candidates ────────────────────────────────
    candidates = [
        p.name for p in validator.model_candidates(Path("/x"), "Systran/faster-whisper-base")
    ]
    check(
        "hf cache directory name is a candidate",
        "models--Systran--faster-whisper-base" in candidates,
        f"got {candidates}",
    )
    check(
        "bare repo-name directory stays a candidate",
        "faster-whisper-base" in candidates,
        f"got {candidates}",
    )

    # ── Unit: .env reading ────────────────────────────────────────────────
    with temp_root() as root:
        (root / ".env").write_text('AUDIO_STT_MODEL="org/quoted-model"\n', encoding="utf-8")
        check(
            "matched quote pair is stripped from .env values",
            validator.env_value(root, "AUDIO_STT_MODEL", "fallback") == "org/quoted-model",
            repr(validator.env_value(root, "AUDIO_STT_MODEL", "fallback")),
        )
        check(
            "absent key falls back to the default",
            validator.env_value(root, "EMBEDDING_MODEL", "fallback") == "fallback",
            repr(validator.env_value(root, "EMBEDDING_MODEL", "fallback")),
        )

    # ── Integration: layouts and pinned models ────────────────────────────
    cases = [
        ("hf-cache", "Systran/faster-whisper-base", "BAAI/bge-base-en-v1.5", "amd/cpu defaults"),
        ("hf-cache", "deepdml/faster-whisper-large-v3-turbo-ct2", "BAAI/bge-base-en-v1.5", "nvidia stt pin"),
        ("bare", "Systran/faster-whisper-base", "BAAI/bge-base-en-v1.5", "bare layout"),
    ]

    for layout, stt, emb, label in cases:
        with temp_root() as td:
            root = build_root(td, layout=layout, stt_model=stt, embedding_model=emb)
            out = run_validator(root)

            # The fixtures are deliberately tiny, so a located model reports
            # "Too small" rather than "Not found". What matters here is that the
            # checker resolves the path the installer actually produced.
            missing = re.findall(r"Not found: (\S+)", out)
            check(
                f"validate-models locates whisper + embeddings ({label})",
                not missing,
                f"reported missing: {missing}\n{out}",
            )

            shell_out = run_shell_checker(root)
            check(
                f"check-offline-models ran ({label})",
                "ODS Offline Mode - Model Check" in shell_out,
                shell_out,
            )
            check(
                f"check-offline-models agrees ({label})",
                "MISSING" not in shell_out,
                shell_out,
            )

    # ── Integration: nothing downloaded yet ───────────────────────────────
    with temp_root() as root:
        (root / ".env").write_text("ODS_MODE=local\n", encoding="utf-8")
        out = run_validator(root)
        check("empty install reports missing models", "MISSING MODELS" in out, out)

        # Whatever remediation either checker prints must actually exist.
        shell_out = run_shell_checker(root)
        referenced = set(
            re.findall(r"\./(scripts/[A-Za-z0-9._-]+)", out)
            + re.findall(r"\./(scripts/[A-Za-z0-9._-]+)", shell_out)
        )
        check("remediation commands were printed", bool(referenced), f"{out}\n{shell_out}")
        for rel in sorted(referenced):
            check(
                f"remediation target exists: {rel}",
                (ROOT / rel).is_file(),
                f"{ROOT / rel} does not exist",
            )

    print()
    print(f"Passed: {PASS}  Failed: {FAIL}")
    if FAIL:
        return 1
    print("[PASS] offline model validation contracts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
