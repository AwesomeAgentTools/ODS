#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ODS_CLI="$ROOT_DIR/ods-cli"

FIXTURE=$(mktemp -d /tmp/test-gpu-reassign-manual.XXXXXX)
FAKE_INSTALL="$FIXTURE/install"
STUB_BIN="$FIXTURE/stubs"
mkdir -p "$FAKE_INSTALL" "$STUB_BIN"
trap 'rm -rf "$FIXTURE"' EXIT

: > "$FAKE_INSTALL/docker-compose.base.yml"
cat > "$FAKE_INSTALL/.env" <<'EOF'
GPU_BACKEND=nvidia
GPU_COUNT=3
GPU_ASSIGNMENT_JSON_B64=c3RhbGU=
LLAMA_SERVER_GPU_UUIDS=GPU-old-0,GPU-old-1
LLAMA_SERVER_GPU_INDICES=0,1
LLAMA_ARG_SPLIT_MODE=row
LLAMA_ARG_TENSOR_SPLIT=1,1
WHISPER_GPU_UUID=GPU-old-2
COMFYUI_GPU_UUID=GPU-old-2
EMBEDDINGS_GPU_UUID=GPU-old-2
LLM_MODEL_SIZE_MB=16000
ENABLED_SERVICES=llama_server,whisper,comfyui,embeddings
EOF

cat > "$STUB_BIN/nvidia-smi" <<'STUB'
#!/usr/bin/env bash
case "$*" in
    *"--query-gpu=index,name,memory.total,memory.free,pcie.link.gen.current,pcie.link.width.current,uuid"*)
        printf '%s\n' \
            "0, NVIDIA GeForce GTX 1080 Ti, 11264, 10240, 3, 16, GPU-ti-0" \
            "1, NVIDIA GeForce GTX 1080, 8192, 7168, 3, 16, GPU-1080" \
            "2, NVIDIA GeForce GTX 1080 Ti, 11264, 9216, 3, 16, GPU-ti-2"
        ;;
    *"--query-gpu=index,name,memory.total"*)
        printf '%s\n' \
            "0, NVIDIA GeForce GTX 1080 Ti, 11264" \
            "1, NVIDIA GeForce GTX 1080, 8192" \
            "2, NVIDIA GeForce GTX 1080 Ti, 11264"
        ;;
    *"--query-gpu=index,uuid"*)
        printf '%s\n' "0, GPU-ti-0" "1, GPU-1080" "2, GPU-ti-2"
        ;;
    *"--query-gpu=uuid"*)
        printf '%s\n' "GPU-ti-0" "GPU-1080" "GPU-ti-2"
        ;;
    *"--query-gpu=driver_version"*) echo "580.0" ;;
    "--list-gpus")
        printf '%s\n' \
            "GPU 0: NVIDIA GeForce GTX 1080 Ti (UUID: GPU-ti-0)" \
            "GPU 1: NVIDIA GeForce GTX 1080 (UUID: GPU-1080)" \
            "GPU 2: NVIDIA GeForce GTX 1080 Ti (UUID: GPU-ti-2)"
        ;;
    "topo -m")
        cat <<'EOF'
        GPU0    GPU1    GPU2
GPU0     X      PHB     PHB
GPU1    PHB      X      PHB
GPU2    PHB     PHB      X
EOF
        ;;
    "-q") echo "MIG Mode : Disabled" ;;
    *) exit 1 ;;
esac
STUB

cat > "$STUB_BIN/docker" <<'STUB'
#!/usr/bin/env bash
exit 99
STUB

chmod +x "$STUB_BIN"/*
STUB_PATH="$STUB_BIN:$PATH"

run_manual() {
    local input="$1"
    set +e
    OUTPUT=$(printf '%s' "$input" |
        ODS_HOME="$FAKE_INSTALL" PATH="$STUB_PATH" "$ODS_CLI" gpu reassign --manual 2>&1)
    RC=$?
    set -e
}

run_cli() {
    set +e
    OUTPUT=$(ODS_HOME="$FAKE_INSTALL" PATH="$STUB_PATH" "$ODS_CLI" "$@" 2>&1)
    RC=$?
    set -e
}

env_value() {
    local key="$1"
    awk -F= -v key="$key" 'index($0, key "=") == 1 { print substr($0, length(key) + 2) }' \
        "$FAKE_INSTALL/.env"
}

run_manual $'0,1,2\n2\n\n1\npipeline\nn\n'
[[ $RC -eq 0 ]] || { echo "[FAIL] manual reassignment failed: $OUTPUT"; exit 1; }

assignment=$(env_value GPU_ASSIGNMENT_JSON_B64 | base64 -d)
echo "$assignment" | jq -e '
    .gpu_assignment.version == "1.0"
    and .gpu_assignment.strategy == "manual"
    and .gpu_assignment.services.llama_server.gpus
        == ["GPU-ti-0", "GPU-1080", "GPU-ti-2"]
    and .gpu_assignment.services.llama_server.gpu_indices == [0, 1, 2]
    and .gpu_assignment.services.llama_server.parallelism.mode == "pipeline"
    and .gpu_assignment.services.llama_server.parallelism.tensor_parallel_size == 1
    and .gpu_assignment.services.llama_server.parallelism.pipeline_parallel_size == 3
    and .gpu_assignment.services.whisper.gpus == ["GPU-ti-2"]
    and (.gpu_assignment.services | has("comfyui") | not)
    and .gpu_assignment.services.embeddings.gpus == ["GPU-1080"]
' >/dev/null

[[ "$(env_value LLAMA_SERVER_GPU_UUIDS)" == "GPU-ti-0,GPU-1080,GPU-ti-2" ]]
[[ "$(env_value LLAMA_SERVER_GPU_INDICES)" == "0,1,2" ]]
[[ "$(env_value LLAMA_ARG_SPLIT_MODE)" == "layer" ]]
[[ -z "$(env_value LLAMA_ARG_TENSOR_SPLIT)" ]]
[[ "$(env_value WHISPER_GPU_UUID)" == "GPU-ti-2" ]]
[[ -z "$(env_value COMFYUI_GPU_UUID)" ]]
[[ "$(env_value EMBEDDINGS_GPU_UUID)" == "GPU-1080" ]]

run_manual $'0,2\n1\n2\n\n\nn\n'
[[ $RC -eq 0 ]] || { echo "[FAIL] tensor reassignment failed: $OUTPUT"; exit 1; }

assignment=$(env_value GPU_ASSIGNMENT_JSON_B64 | base64 -d)
echo "$assignment" | jq -e '
    .gpu_assignment.services.llama_server.gpus == ["GPU-ti-0", "GPU-ti-2"]
    and .gpu_assignment.services.llama_server.parallelism == {
        mode: "tensor",
        tensor_parallel_size: 2,
        pipeline_parallel_size: 1,
        gpu_memory_utilization: 0.93,
        tensor_split: [1, 1]
    }
    and .gpu_assignment.services.whisper.gpus == ["GPU-1080"]
    and .gpu_assignment.services.comfyui.gpus == ["GPU-ti-2"]
    and (.gpu_assignment.services | has("embeddings") | not)
' >/dev/null
[[ "$(env_value LLAMA_ARG_SPLIT_MODE)" == "row" ]]
[[ "$(env_value LLAMA_ARG_TENSOR_SPLIT)" == "1,1" ]]
[[ -z "$(env_value EMBEDDINGS_GPU_UUID)" ]]

run_cli gpu assignment
[[ $RC -eq 0 ]]
echo "$OUTPUT" | grep -q "Strategy: manual"
echo "$OUTPUT" | grep -q "llama_server.*GPU0, GPU2.*tensor"

run_cli gpu validate
[[ $RC -eq 0 ]]
echo "$OUTPUT" | grep -q "Result: 3 check(s) passed, 0 failed"

before_hash=$(sha256sum "$FAKE_INSTALL/.env" | awk '{print $1}')
run_manual $'0,3\n\n\n\n'
[[ $RC -ne 0 ]] || { echo "[FAIL] nonexistent GPU index was accepted"; exit 1; }
echo "$OUTPUT" | grep -q "Invalid llama-server GPU list"
after_hash=$(sha256sum "$FAKE_INSTALL/.env" | awk '{print $1}')
[[ "$before_hash" == "$after_hash" ]] || {
    echo "[FAIL] invalid manual input mutated .env"
    exit 1
}

before_hash=$(sha256sum "$FAKE_INSTALL/.env" | awk '{print $1}')
run_manual $'0,1\n0,2\n\n\n'
[[ $RC -ne 0 ]] || { echo "[FAIL] multiple auxiliary GPU indices were accepted"; exit 1; }
echo "$OUTPUT" | grep -q "Invalid Whisper GPU index"
after_hash=$(sha256sum "$FAKE_INSTALL/.env" | awk '{print $1}')
[[ "$before_hash" == "$after_hash" ]] || {
    echo "[FAIL] invalid auxiliary input mutated .env"
    exit 1
}

echo "[PASS] manual GPU reassignment persists one validated assignment contract"
