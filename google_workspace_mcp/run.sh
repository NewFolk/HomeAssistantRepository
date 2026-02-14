#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[ERROR] Missing $CONFIG_PATH"
  exit 1
fi

cfg_str() {
  jq -r "$1 // \"\"" "$CONFIG_PATH"
}

cfg_bool() {
  jq -r "if $1 == true then \"true\" else \"false\" end" "$CONFIG_PATH"
}

OAUTH_CLIENT_ID="$(cfg_str '.oauth_client_id')"
OAUTH_CLIENT_SECRET="$(cfg_str '.oauth_client_secret')"
OAUTH_REDIRECT_URI="$(cfg_str '.oauth_redirect_uri')"
EXTERNAL_URL="$(cfg_str '.external_url')"
USER_GOOGLE_EMAIL="$(cfg_str '.user_google_email')"
TOOL_TIER="$(cfg_str '.tool_tier')"
TOOLS_RAW="$(cfg_str '.tools')"
TRANSPORT="$(cfg_str '.transport')"
CLIENT_COMPAT_SCOPES="$(cfg_str '.client_compat_scopes')"
ENABLE_OAUTH21="$(cfg_bool '.enable_oauth21')"
STATELESS_MODE="$(cfg_bool '.stateless_mode')"
SINGLE_USER_MODE="$(cfg_bool '.single_user_mode')"
READ_ONLY_MODE="$(cfg_bool '.read_only_mode')"
ALLOW_INSECURE="$(cfg_bool '.allow_insecure_transport')"

if [[ -z "$TOOL_TIER" ]]; then
  TOOL_TIER="core"
fi

if [[ -z "$TRANSPORT" ]]; then
  TRANSPORT="streamable-http"
fi

if [[ -z "$CLIENT_COMPAT_SCOPES" ]]; then
  CLIENT_COMPAT_SCOPES="mcp:tools"
fi

if [[ -z "$OAUTH_CLIENT_ID" || -z "$OAUTH_CLIENT_SECRET" ]]; then
  echo "[ERROR] oauth_client_id and oauth_client_secret must be set in add-on options"
  exit 1
fi

if [[ "$ENABLE_OAUTH21" == "true" && "$SINGLE_USER_MODE" == "true" ]]; then
  echo "[ERROR] single_user_mode=true is incompatible with enable_oauth21=true"
  exit 1
fi

mkdir -p /data/credentials
chmod 700 /data/credentials || true

export GOOGLE_OAUTH_CLIENT_ID="$OAUTH_CLIENT_ID"
export GOOGLE_OAUTH_CLIENT_SECRET="$OAUTH_CLIENT_SECRET"
export WORKSPACE_MCP_CREDENTIALS_DIR="/data/credentials"
export GOOGLE_MCP_CREDENTIALS_DIR="/data/credentials"
export WORKSPACE_MCP_HOST="0.0.0.0"
export WORKSPACE_MCP_PORT="8000"
export MCP_ENABLE_OAUTH21="$ENABLE_OAUTH21"
export WORKSPACE_MCP_STATELESS_MODE="$STATELESS_MODE"
export MCP_CLIENT_COMPAT_SCOPES="$CLIENT_COMPAT_SCOPES"

if [[ -n "$OAUTH_REDIRECT_URI" ]]; then
  export GOOGLE_OAUTH_REDIRECT_URI="$OAUTH_REDIRECT_URI"
fi

if [[ -n "$EXTERNAL_URL" ]]; then
  export WORKSPACE_EXTERNAL_URL="$EXTERNAL_URL"
fi

if [[ -n "$USER_GOOGLE_EMAIL" ]]; then
  export USER_GOOGLE_EMAIL="$USER_GOOGLE_EMAIL"
fi

if [[ "$ALLOW_INSECURE" == "true" ]]; then
  export OAUTHLIB_INSECURE_TRANSPORT=1
fi

cmd=(workspace-mcp --transport "$TRANSPORT" --tool-tier "$TOOL_TIER")

if [[ -n "$TOOLS_RAW" ]]; then
  # Space-separated service names, e.g. "gmail calendar drive"
  read -r -a tools_array <<< "$TOOLS_RAW"
  cmd+=(--tools "${tools_array[@]}")
fi

if [[ "$READ_ONLY_MODE" == "true" ]]; then
  cmd+=(--read-only)
fi

if [[ "$SINGLE_USER_MODE" == "true" ]]; then
  cmd+=(--single-user)
fi

echo "[INFO] Starting Google Workspace MCP"
echo "[INFO] Transport: $TRANSPORT"
echo "[INFO] Tool tier: $TOOL_TIER"
echo "[INFO] Client compat scopes: $MCP_CLIENT_COMPAT_SCOPES"

exec "${cmd[@]}"
