#!/usr/bin/env bash
# run-lab-dispatch-local.sh — Execute a Lab dispatch packet locally via Claude Code.
#
# Fallback execution path when nix/OpenClaw is offline. Runs on gentoo
# using the native claude CLI instead of OpenClaw's ACP harness.
#
# Usage:
#   ./cli/run-lab-dispatch-local.sh --packet-file /path/to/packet.json
#   echo '{"run_id":...}' | ./cli/run-lab-dispatch-local.sh
#
# Requires:
#   - claude CLI on PATH
#   - Python 3.11+ with cli/.venv
#   - NOTION_TOKEN (for handle_final_return via MCP)
#   - Project repos under ~/projects/

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PROJECTS_ROOT="${LAB_PROJECTS_ROOT:-$HOME/projects}"
SANDBOX_ROOT="${LAB_SANDBOX_ROOT:-$PROJECTS_ROOT/.lab-sandboxes}"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"
PACKET_FILE=""
TIMEOUT="${LAB_DISPATCH_TIMEOUT:-900}"

usage() {
  cat <<'EOF'
Usage:
  run-lab-dispatch-local.sh [--packet-file /path/to/packet.json] [--timeout <seconds>]

Reads a Lab dispatch packet from --packet-file or stdin. Prepares a per-run
sandbox (git worktree), invokes claude CLI, captures output, and calls
handle_final_return via the local MCP server.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --packet-file)
      [ $# -ge 2 ] || { echo "ERROR: --packet-file requires a value" >&2; exit 2; }
      PACKET_FILE="$2"
      shift 2
      ;;
    --timeout)
      [ $# -ge 2 ] || { echo "ERROR: --timeout requires a value" >&2; exit 2; }
      TIMEOUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# ── Read packet ──────────────────────────────────────────────────────────────

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE" "$MESSAGE_FILE" "$OUTPUT_FILE"' EXIT

if [ -n "$PACKET_FILE" ]; then
  cp "$PACKET_FILE" "$TMPFILE"
else
  cat >"$TMPFILE"
fi

# ── Parse packet fields ─────────────────────────────────────────────────────

packet_field() {
  "$VENV_PYTHON" -c "import json,sys; p=json.load(open(sys.argv[1])); print(p.get(sys.argv[2],''))" "$TMPFILE" "$1"
}

packet_bool() {
  "$VENV_PYTHON" -c "import json,sys; p=json.load(open(sys.argv[1])); print('1' if p.get('constraints',{}).get(sys.argv[2]) else '0')" "$TMPFILE" "$1"
}

WORK_ITEM_NAME=$(packet_field work_item_name)
WORK_ITEM_ID=$(packet_field work_item_id)
RUN_ID=$(packet_field run_id)
LANE=$(packet_field execution_lane)
REPO_URL=$(packet_field repo_url)
BRANCH=$(packet_field branch)
CAN_CODE=$(packet_bool can_code)

echo "Local dispatch: ${WORK_ITEM_NAME} (lane=${LANE})" >&2

# ── Prepare sandbox ──────────────────────────────────────────────────────────

SANDBOX_PATH=""
if [ "$CAN_CODE" = "1" ] && [ -n "$REPO_URL" ]; then
  SANDBOX_JSON=$("$VENV_PYTHON" -c "
import json, sys
sys.path.insert(0, '${SCRIPT_DIR}/../openclaw/lib' if __import__('os').path.exists('${SCRIPT_DIR}/../openclaw/lib') else '${SCRIPT_DIR}')
# Inline sandbox prep (no dependency on nix-docker-configs)
from pathlib import Path
from urllib.parse import urlparse
import subprocess

packet = json.load(open(sys.argv[1]))
repo_url = packet.get('repo_url', '')
run_id = packet.get('run_id', '')
branch = packet.get('branch', 'main')

# Derive repo name
parts = [p for p in urlparse(repo_url).path.split('/') if p]
repo_name = parts[-1].removesuffix('.git') if len(parts) >= 2 else ''

projects_root = Path('${PROJECTS_ROOT}')
sandbox_root = Path('${SANDBOX_ROOT}')
source_repo = projects_root / repo_name

if not source_repo.exists():
    print(json.dumps({'error': f'Source repo not found: {source_repo}'}))
    sys.exit(0)

# Resolve checkout ref
def has_ref(repo, ref):
    return subprocess.run(['git','-C',str(repo),'show-ref','--verify','--quiet',ref],capture_output=True).returncode==0

if has_ref(source_repo, f'refs/heads/{branch}'):
    ref = branch
elif has_ref(source_repo, f'refs/remotes/origin/{branch}'):
    ref = f'origin/{branch}'
else:
    ref = subprocess.run(['git','-C',str(source_repo),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()

sandbox_path = sandbox_root / repo_name / run_id
if not sandbox_path.exists():
    sandbox_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git','-C',str(source_repo),'worktree','add','--detach',str(sandbox_path),ref],check=True,capture_output=True,text=True)

# Write metadata
lab_dir = sandbox_path / '.lab'
lab_dir.mkdir(parents=True, exist_ok=True)
(lab_dir / 'dispatch-packet.json').write_text(json.dumps(packet, indent=2) + '\n')
(lab_dir / 'README.md').write_text('\n'.join([
    '# Lab Sandbox',
    '',
    f'- Work item: \`{packet.get(\"work_item_name\",\"\")}\`',
    f'- Run ID: \`{run_id}\`',
    f'- Source repo: \`{source_repo}\`',
    f'- Branch request: \`{branch}\`',
    f'- Repo URL: \`{repo_url}\`',
    '',
    'Rules:',
    '- Work only inside this sandbox unless explicitly instructed otherwise.',
    '- Read \`.lab/dispatch-packet.json\` before editing code.',
    '- Commit your work to the sandbox repo before finishing (\`git add\` + \`git commit\`).',
    '- The execution wrapper handles return signaling — just print a concise summary to stdout.',
    '',
]) + '\n')

# Ensure .lab/ is git-excluded
try:
    exclude_path = subprocess.run(['git','-C',str(sandbox_path),'rev-parse','--git-path','info/exclude'],capture_output=True,text=True,check=True).stdout.strip()
    ep = Path(exclude_path) if Path(exclude_path).is_absolute() else sandbox_path / exclude_path
    ep.parent.mkdir(parents=True, exist_ok=True)
    existing = ep.read_text() if ep.exists() else ''
    if '/.lab/' not in existing:
        ep.open('a').write('/.lab/\n')
except Exception:
    pass

print(json.dumps({'sandbox_path': str(sandbox_path), 'source_repo': str(source_repo), 'branch': branch}))
" "$TMPFILE")

  SANDBOX_PATH=$(echo "$SANDBOX_JSON" | "$VENV_PYTHON" -c "import json,sys; print(json.load(sys.stdin).get('sandbox_path',''))")
  if [ -z "$SANDBOX_PATH" ]; then
    echo "WARNING: Sandbox preparation failed: $SANDBOX_JSON" >&2
  else
    echo "Sandbox: ${SANDBOX_PATH}" >&2
  fi
fi

# ── Build dispatch message ───────────────────────────────────────────────────

PACKET_PRETTY=$("$VENV_PYTHON" -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1])),indent=2))" "$TMPFILE")
MESSAGE_FILE=$(mktemp)

if [ -n "$SANDBOX_PATH" ]; then
  cat > "$MESSAGE_FILE" <<EOF
You are executing a Lab dispatch packet.

Execution lane: ${LANE}
Per-run sandbox: ${SANDBOX_PATH}

Mandatory rules:
- Work only inside ${SANDBOX_PATH}.
- Read ${SANDBOX_PATH}/.lab/README.md and ${SANDBOX_PATH}/.lab/dispatch-packet.json before editing code.
- Do not modify files outside the sandbox unless the packet explicitly requires it.
- Commit your work before finishing (git add + git commit). Do not push.
- Print a concise execution summary to stdout before exiting.

Dispatch packet:
${PACKET_PRETTY}
EOF
else
  cat > "$MESSAGE_FILE" <<EOF
You are executing a Lab dispatch packet.

Execution lane: ${LANE}

Mandatory rules:
- Follow the dispatch packet exactly.
- Print a concise execution summary to stdout before exiting.

Dispatch packet:
${PACKET_PRETTY}
EOF
fi

# ── Execute via claude CLI ───────────────────────────────────────────────────

OUTPUT_FILE=$(mktemp)
START_MS=$("$VENV_PYTHON" -c "import time; print(int(time.time()*1000))")

echo "Executing via claude CLI (timeout=${TIMEOUT}s)..." >&2

DISPATCH_EXIT_CODE=0
if [ -n "$SANDBOX_PATH" ]; then
  timeout "$TIMEOUT" claude --dangerously-skip-permissions \
    -p "$(cat "$MESSAGE_FILE")" \
    --output-format text \
    --cwd "$SANDBOX_PATH" \
    > "$OUTPUT_FILE" 2>&1 || DISPATCH_EXIT_CODE=$?
else
  timeout "$TIMEOUT" claude --dangerously-skip-permissions \
    -p "$(cat "$MESSAGE_FILE")" \
    --output-format text \
    > "$OUTPUT_FILE" 2>&1 || DISPATCH_EXIT_CODE=$?
fi

cat "$OUTPUT_FILE"

# ── Post-execution return ────────────────────────────────────────────────────

END_MS=$("$VENV_PYTHON" -c "import time; print(int(time.time()*1000))")
DURATION_MS=$(( END_MS - START_MS ))

if [ -z "$WORK_ITEM_ID" ] || [ -z "$RUN_ID" ]; then
  echo "WARNING: Missing work_item_id or run_id — skipping final return" >&2
  exit "$DISPATCH_EXIT_CODE"
fi

STATUS="ok"
VERDICT="PASS"
ERROR_MSG=""
RAW_OUTPUT=$(head -c 50000 "$OUTPUT_FILE")

if [ "$DISPATCH_EXIT_CODE" -ne 0 ]; then
  STATUS="error"
  VERDICT=""
  ERROR_MSG="Claude CLI exited with code ${DISPATCH_EXIT_CODE}"
  SUMMARY="Execution failed (exit code ${DISPATCH_EXIT_CODE})"
else
  SUMMARY=$(printf '%s' "$RAW_OUTPUT" | tail -c 2000 | head -c 500)
fi

echo "Calling handle_final_return for ${WORK_ITEM_NAME} (${STATUS})" >&2

"$VENV_PYTHON" -c "
import sys, json
sys.path.insert(0, '${SCRIPT_DIR}')
import dispatch, notion_api
from config import get_config

client = notion_api.NotionAPIClient(get_config().notion_token)
result = dispatch.handle_final_return(
    work_item_id='${WORK_ITEM_ID}',
    run_id='${RUN_ID}',
    status='${STATUS}',
    summary=sys.stdin.read(),
    raw_output=open('${OUTPUT_FILE}').read()[:50000],
    duration_ms=${DURATION_MS},
    model='claude-local',
    lane='${LANE}',
    verdict='${VERDICT}' or None,
    error='${ERROR_MSG}' or None,
    client=client,
)
print(json.dumps(result, indent=2))
" <<< "$SUMMARY" 2>&1 || echo "WARNING: handle_final_return failed" >&2

exit "$DISPATCH_EXIT_CODE"
