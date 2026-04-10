#!/usr/bin/env bash
# MCP server launcher — auto-selects local (biometric) or remote (service account) auth.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
SERVER="$SCRIPT_DIR/mcp_server.py"
ENV_LOCAL="$HOME/.env"
ENV_REMOTE="$HOME/.env.remote"
SA_TOKEN_FILE="$HOME/.config/op/notion-forge-sa-token"
SA_TOKEN="${OP_SERVICE_ACCOUNT_TOKEN:-$(cat "$SA_TOKEN_FILE" 2>/dev/null || true)}"

select_env_file() {
    if [[ -f "$1" ]]; then
        printf '%s\n' "$1"
    elif [[ -f "$2" ]]; then
        printf '%s\n' "$2"
    else
        return 1
    fi
}

# Try local (biometric) auth first; fall back to service account
if op account get &>/dev/null 2>&1; then
    ENV_FILE="$(select_env_file "$ENV_LOCAL" "$ENV_REMOTE")" || {
        echo "No env file found. Expected $ENV_LOCAL or $ENV_REMOTE." >&2
        exit 1
    }
    exec op run --env-file "$ENV_FILE" --no-masking -- "$PYTHON" "$SERVER"
else
    export OP_SERVICE_ACCOUNT_TOKEN="$SA_TOKEN"
    ENV_FILE="$(select_env_file "$ENV_REMOTE" "$ENV_LOCAL")" || {
        echo "No env file found. Expected $ENV_REMOTE or $ENV_LOCAL." >&2
        exit 1
    }
    exec op run --env-file "$ENV_FILE" --no-masking -- "$PYTHON" "$SERVER"
fi
