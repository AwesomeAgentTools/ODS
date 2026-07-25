#!/usr/bin/env python3
"""
Pre-flight model validation for ODS offline mode.
Ensures required models are downloaded before starting services.
"""

import os
import sys
from pathlib import Path

# Fallbacks when .env does not pin a model. These mirror the installer's
# defaults (installers/phases/06-directories.sh); NVIDIA installs pin a larger
# STT model, which is why the ids are read from .env rather than hardcoded.
DEFAULT_STT_MODEL = "Systran/faster-whisper-base"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"

# Model requirements for offline mode.
#
# Two shapes:
#   "path"      — a fixed file/directory under the install root.
#   "cache_dir" — a HuggingFace cache root; the repo id comes from .env and the
#                 on-disk directory name is derived from it.
REQUIRED_MODELS = {
    "llm": {
        "path": "data/models",
        "description": "Primary LLM (GGUF model)",
        "size_gb": 4,
    },
    "whisper": {
        "cache_dir": "data/whisper",
        "model_env": "AUDIO_STT_MODEL",
        "default_model": DEFAULT_STT_MODEL,
        "description": "Whisper STT model",
        "size_gb": 0.15,
    },
    "kokoro": {
        "path": "data/kokoro/voices/af_heart.pt",
        "description": "Kokoro TTS voice (af_heart)",
        "size_gb": 0.3,
    },
    "embeddings": {
        "cache_dir": "data/embeddings",
        "model_env": "EMBEDDING_MODEL",
        "default_model": DEFAULT_EMBEDDING_MODEL,
        "description": "Embedding model",
        "size_gb": 0.4,
    },
}


def ods_root():
    """Install root. ODS_ROOT overrides for tests and out-of-tree checkouts."""
    override = os.environ.get("ODS_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent


def env_value(root, key, default):
    """Read one KEY=value out of the install's .env, or return default."""
    env_path = root / ".env"
    if not env_path.is_file():
        return default

    prefix = f"{key}="
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        # Strip only a matched surrounding quote pair, so a value that merely
        # starts or ends with a quote keeps it.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value or default
    return default


def model_candidates(cache_root, repo_id):
    """Where a HuggingFace repo id can legitimately live under cache_root.

    Downloads run through scripts/download-hf-snapshot.py, which calls
    snapshot_download(cache_dir=...); that lays the repo out as
    models--<org>--<name>. data/whisper is mounted straight into the container
    as ~/.cache/huggingface/hub, so that is the layout on a real install. The
    bare forms are kept for manually populated caches.
    """
    org_name = repo_id.replace("/", "--")
    return [
        cache_root / f"models--{org_name}",
        cache_root / repo_id,
        cache_root / repo_id.split("/")[-1],
    ]


def dir_size_gb(path):
    """Size of a file, or the sum of every regular file beneath a directory."""
    if path.is_file():
        return path.stat().st_size / (1024**3)
    return sum(
        f.stat().st_size for f in path.rglob("*") if f.is_file()
    ) / (1024**3)


def check_model(config, root):
    """Check that a model exists on disk and is not obviously truncated."""
    if "cache_dir" in config:
        cache_root = root / config["cache_dir"]
        repo_id = env_value(root, config["model_env"], config["default_model"])
        candidates = model_candidates(cache_root, repo_id)
        label = f"{config['cache_dir']}/ ({repo_id})"
    else:
        candidates = [root / config["path"]]
        label = config["path"]

    model_path = next((c for c in candidates if c.exists()), None)
    if model_path is None:
        return False, f"Not found: {label}"

    size_gb = dir_size_gb(model_path)

    min_size = config["size_gb"] * 0.5  # At least 50% of expected size
    if size_gb < min_size:
        return False, f"Too small: {size_gb:.2f}GB (expected ~{config['size_gb']}GB)"

    return True, f"OK: {size_gb:.2f}GB"


def main():
    """Validate all required models are present."""
    root = ods_root()

    print("=" * 60)
    print("ODS Offline Mode - Model Validation")
    print("=" * 60)

    all_ok = True
    missing = []

    for service, config in REQUIRED_MODELS.items():
        ok, msg = check_model(config, root)
        status = "✓" if ok else "✗"
        print(f"{status} {config['description']:40s} {msg}")

        if not ok:
            all_ok = False
            missing.append(service)

    print("=" * 60)

    if all_ok:
        print("All models present. Ready for offline mode!")
        return 0

    print(f"\nMISSING MODELS: {', '.join(missing)}")
    print("\nDownload models before starting offline mode:")
    print("  ./scripts/pre-download.sh                # LLM for the detected tier")
    print("  ./scripts/pre-download.sh --with-voice   # also cache STT and TTS")
    print("  ./scripts/pre-download.sh --verify       # re-check the cache")
    return 1


if __name__ == "__main__":
    sys.exit(main())
