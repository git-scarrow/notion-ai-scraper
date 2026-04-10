#!/usr/bin/env bash
# Launcher for notion-mcp-server (node) — injects NOTION_TOKEN via op run.
set -euo pipefail

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

if op account get &>/dev/null 2>&1; then
    ENV_FILE="$(select_env_file "$ENV_LOCAL" "$ENV_REMOTE")" || {
        echo "No env file found. Expected $ENV_LOCAL or $ENV_REMOTE." >&2
        exit 1
    }
    exec op run --env-file "$ENV_FILE" --no-masking -- node /mnt/fast/npm-global/bin/notion-mcp-server "$@"
else
    export OP_SERVICE_ACCOUNT_TOKEN="$SA_TOKEN"
    ENV_FILE="$(select_env_file "$ENV_REMOTE" "$ENV_LOCAL")" || {
        echo "No env file found. Expected $ENV_REMOTE or $ENV_LOCAL." >&2
        exit 1
    }
    exec op run --env-file "$ENV_FILE" --no-masking -- node /mnt/fast/npm-global/bin/notion-mcp-server "$@"
fi
