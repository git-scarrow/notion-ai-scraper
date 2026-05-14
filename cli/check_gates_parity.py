"""check_gates_parity.py — compare local and Worker `check_gates` output.

Local side calls `dispatch.check_gates` directly.
Worker side calls the deployed Notion Worker tool via the agent-tools endpoint.

Until the Worker is deployed, `--worker` exits non-zero with a clear message.
This script is the gate for Lane 1 of the notion-platform-migration audit.

Exit codes:
  0 — both sides returned identical JSON for every fixture
  1 — at least one fixture diverged
  2 — Worker endpoint unreachable or not yet deployed
  3 — configuration missing (NOTION_TOKEN, Work Items DB, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch
import notion_api
from config import get_config


@dataclass(frozen=True)
class Fixture:
    name: str
    work_item_id: str | None
    description: str


FIXTURES: list[Fixture] = [
    Fixture(
        name="no_work_item",
        work_item_id=None,
        description="Pre-Flight check only; expect {proceed, cascade_depth: 1}.",
    ),
]


def _normalize(result: dict) -> dict:
    """Sort keys and re-serialize so diffs are deterministic."""
    return json.loads(json.dumps(result, sort_keys=True))


def run_local(fixture: Fixture, client: notion_api.NotionAPIClient) -> dict:
    return _normalize(dispatch.check_gates(fixture.work_item_id, client))


def run_worker(fixture: Fixture, project_dir: str, *, remote: bool) -> dict:
    """Run the Worker via `ntn workers exec`. remote=False uses --local."""
    import subprocess

    payload = json.dumps({"work_item_id": fixture.work_item_id or ""})
    cmd = ["ntn", "workers", "exec", "checkGates"]
    if not remote:
        cmd.append("--local")
    cmd += ["-d", payload]
    env = os.environ.copy()
    env.setdefault("NOTION_KEYRING", "0")
    proc = subprocess.run(
        cmd, cwd=project_dir, env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ntn workers exec failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return _normalize(json.loads(proc.stdout))


def compare(local: dict, worker: dict) -> list[str]:
    """Return human-readable diffs; empty list = identical."""
    diffs: list[str] = []
    all_keys = sorted(set(local) | set(worker))
    for key in all_keys:
        if key not in local:
            diffs.append(f"  + {key}={worker[key]!r} (worker only)")
        elif key not in worker:
            diffs.append(f"  - {key}={local[key]!r} (local only)")
        elif local[key] != worker[key]:
            diffs.append(f"  ~ {key}: local={local[key]!r} worker={worker[key]!r}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--worker",
        action="store_true",
        help="Also run the Worker via `ntn workers exec --local` and diff.",
    )
    ap.add_argument(
        "--remote",
        action="store_true",
        help="With --worker, target the deployed Worker instead of --local.",
    )
    ap.add_argument(
        "--worker-dir",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "workers",
            "check_gates",
        ),
        help="Path to the check_gates Worker project (for --local exec).",
    )
    ap.add_argument(
        "--work-item-id",
        help="Add an extra fixture against a real Work Item (read-only).",
    )
    args = ap.parse_args()

    cfg = get_config()
    if not cfg.notion_token:
        print("ERROR: NOTION_TOKEN not configured.", file=sys.stderr)
        return 3

    client = notion_api.NotionAPIClient(cfg.notion_token)

    fixtures = list(FIXTURES)
    if args.work_item_id:
        fixtures.append(
            Fixture(
                name="user_work_item",
                work_item_id=args.work_item_id,
                description=f"Live Work Item {args.work_item_id}.",
            )
        )

    failures = 0
    for fix in fixtures:
        print(f"[{fix.name}] {fix.description}")
        local = run_local(fix, client)
        print(f"  local : {json.dumps(local, sort_keys=True)}")
        if not args.worker:
            continue
        if not os.path.isdir(args.worker_dir):
            print(f"ERROR: worker dir not found: {args.worker_dir}", file=sys.stderr)
            return 2
        worker = run_worker(fix, args.worker_dir, remote=args.remote)
        print(f"  worker: {json.dumps(worker, sort_keys=True)}")
        diffs = compare(local, worker)
        if diffs:
            failures += 1
            print("  DIVERGED:")
            for d in diffs:
                print(d)
        else:
            print("  OK")

    if failures:
        print(f"\n{failures} fixture(s) diverged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
