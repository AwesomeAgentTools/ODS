#!/bin/bash
# Static regression checks for the Windows ods.ps1 uninstall command.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
ODS_PS1="$ROOT_DIR/installers/windows/ods.ps1"

fail() { echo "[FAIL] $1"; exit 1; }
pass() { echo "[PASS] $1"; }

[[ -f "$ODS_PS1" ]] || fail "Windows ods.ps1 missing"

grep -q 'uninstall.*Remove ODS containers' "$ODS_PS1" \
    || fail "Header/help must document uninstall"
grep -q 'function Invoke-Uninstall' "$ODS_PS1" \
    || fail "Invoke-Uninstall function missing"
grep -q '"uninstall" { Invoke-Uninstall' "$ODS_PS1" \
    || fail "Command dispatcher must route uninstall"

grep -q 'com.docker.compose.project=ods' "$ODS_PS1" \
    || fail "Uninstall must have Docker label fallback for broken compose receipts"
grep -q 'docker rm -f @containers' "$ODS_PS1" \
    || fail "Uninstall fallback must remove labelled containers"
grep -q 'docker network rm @networks' "$ODS_PS1" \
    || fail "Uninstall fallback must remove labelled networks"
grep -q 'docker volume rm @volumes' "$ODS_PS1" \
    || fail "Uninstall fallback must remove labelled volumes"
grep -q 'function Test-ODSComposeFlagsFilesAvailable' "$ODS_PS1" \
    || fail "Uninstall must validate compose receipt files before compose down"
grep -q 'Assert-ODSInstallDirSafeForRemoval' "$ODS_PS1" \
    || fail "Uninstall must guard recursive removal target"

for doc in \
    "$REPO_ROOT/README.md" \
    "$ROOT_DIR/README.md" \
    "$ROOT_DIR/QUICKSTART.md" \
    "$ROOT_DIR/FAQ.md" \
    "$ROOT_DIR/docs/WINDOWS-QUICKSTART.md" \
    "$ROOT_DIR/docs/WINDOWS-INSTALL-WALKTHROUGH.md"; do
    [[ -f "$doc" ]] || fail "Expected doc missing: $doc"
    grep -q '.\\ods.ps1 uninstall --force' "$doc" \
        || fail "Doc must show Windows uninstall command: $doc"
done

pass "Windows uninstall command and docs are wired"
