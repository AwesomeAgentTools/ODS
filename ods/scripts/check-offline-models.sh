#!/bin/bash
# ODS Offline Mode - Model Pre-download Check
# Verifies required models exist before starting services

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ODS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ODS_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "ODS Offline Mode - Model Check"
echo "=========================================="
echo ""

MISSING=()

# Read one KEY=value from .env, stripping only a matched surrounding quote pair.
_env_value() {
    local key="$1" default="$2" line value
    [ -f ".env" ] || { printf '%s' "$default"; return 0; }
    line=$(grep -m1 "^${key}=" ".env" 2>/dev/null || true)
    [ -n "$line" ] || { printf '%s' "$default"; return 0; }
    value="${line#*=}"
    value="${value%$'\r'}"
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    printf '%s' "${value:-$default}"
}

# Is a HuggingFace repo id present under a cache root, in any known layout?
# Downloads go through scripts/download-hf-snapshot.py -> snapshot_download,
# which writes models--<org>--<name>; the bare forms cover manual caches.
_hf_model_present() {
    local cache_root="$1" repo_id="$2"
    [ -d "$cache_root/models--${repo_id//\//--}" ] && return 0
    [ -d "$cache_root/$repo_id" ] && return 0
    [ -d "$cache_root/${repo_id##*/}" ] && return 0
    return 1
}

# The installer pins these per backend (NVIDIA gets a larger STT model), so
# read what this install actually configured instead of assuming the default.
STT_MODEL=$(_env_value AUDIO_STT_MODEL "Systran/faster-whisper-base")
EMBEDDING_MODEL_ID=$(_env_value EMBEDDING_MODEL "BAAI/bge-base-en-v1.5")

# Check LLM model (GGUF)
if ls data/models/*.gguf &>/dev/null; then
    MODEL_FILE=$(ls -1 data/models/*.gguf | sed -n '1p')
    echo -e "${GREEN}✓${NC} LLM model: $(basename "$MODEL_FILE")"
else
    echo -e "${RED}✗${NC} LLM model (GGUF) - MISSING"
    MISSING+=("gguf-model")
fi

# Check Whisper model
if _hf_model_present "data/whisper" "$STT_MODEL"; then
    echo -e "${GREEN}✓${NC} Whisper STT ($STT_MODEL)"
else
    echo -e "${RED}✗${NC} Whisper STT ($STT_MODEL) - MISSING"
    MISSING+=("$STT_MODEL")
fi

# Check Kokoro voice
if [ -f "data/kokoro/voices/af_heart.pt" ]; then
    echo -e "${GREEN}✓${NC} Kokoro voice af_heart (TTS)"
else
    echo -e "${RED}✗${NC} Kokoro voice af_heart - MISSING"
    MISSING+=("kokoro-af_heart")
fi

# Check embeddings model
if _hf_model_present "data/embeddings" "$EMBEDDING_MODEL_ID"; then
    echo -e "${GREEN}✓${NC} Embeddings ($EMBEDDING_MODEL_ID)"
else
    echo -e "${RED}✗${NC} Embeddings ($EMBEDDING_MODEL_ID) - MISSING"
    MISSING+=("$EMBEDDING_MODEL_ID")
fi

echo ""
echo "=========================================="

if [ ${#MISSING[@]} -eq 0 ]; then
    echo -e "${GREEN}All models present. Ready for offline mode!${NC}"
    exit 0
else
    echo -e "${RED}Missing models: ${#MISSING[@]}${NC}"
    echo ""
    echo "Download models with:"
    echo "  ./scripts/pre-download.sh                # LLM for the detected tier"
    echo "  ./scripts/pre-download.sh --with-voice   # also cache STT and TTS"
    echo ""
    echo "Or manually download:"
    for model in "${MISSING[@]}"; do
        echo "  - $model"
    done
    exit 1
fi
