#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINUX_ENV="$ROOT_DIR/installers/phases/06-directories.sh"
MACOS_ENV="$ROOT_DIR/installers/macos/lib/env-generator.sh"
WINDOWS_ENV="$ROOT_DIR/installers/windows/lib/env-generator.ps1"
WINDOWS_OPENCODE="$ROOT_DIR/installers/windows/phases/07-devtools.ps1"
LINUX_OPENCODE="$ROOT_DIR/opencode/opencode-web.service"

require() {
    local pattern="$1" file="$2" message="$3"
    if ! grep -Eq -- "$pattern" "$file"; then
        printf 'FAIL: %s\n' "$message" >&2
        exit 1
    fi
}

require '_env_get WEBUI_AUTH "false"' "$LINUX_ENV" \
    "Linux loopback installs must default Open WebUI auth off"
require '_env_get WEBUI_AUTH "true"' "$LINUX_ENV" \
    "Linux network installs must default Open WebUI auth on"
require 'ENABLE_ODS_PROXY.*false' "$LINUX_ENV" \
    "Linux LAN proxy installs must keep Open WebUI auth on"

require '127\.0\.0\.1\|::1\|localhost.*webui_auth="false"' "$MACOS_ENV" \
    "macOS loopback installs must default Open WebUI auth off"
require 'ENABLE_ODS_PROXY.*true' "$MACOS_ENV" \
    "macOS LAN proxy installs must keep Open WebUI auth on"

require 'webuiAuthDefault = if' "$WINDOWS_ENV" \
    "Windows loopback auth policy is missing"
require '127\.0\.0\.1", "::1", "localhost' "$WINDOWS_ENV" \
    "Windows loopback host allowlist is missing"
require 'EnableODSProxy' "$WINDOWS_ENV" \
    "Windows LAN proxy auth policy is missing"

require 'UnsetEnvironment=OPENCODE_SERVER_PASSWORD' "$LINUX_OPENCODE" \
    "Linux OpenCode must clear inherited browser auth"
require 'Remove-Item Env:OPENCODE_SERVER_PASSWORD' "$WINDOWS_OPENCODE" \
    "Windows OpenCode must clear inherited browser auth"
require '--hostname 127\.0\.0\.1' "$WINDOWS_OPENCODE" \
    "Passwordless Windows OpenCode must remain loopback-only"

printf 'PASS: local app authentication defaults\n'
