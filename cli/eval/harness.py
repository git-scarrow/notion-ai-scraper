#!/usr/bin/env python3
"""Model evaluation harness for the Writing Editor role matrix.

Bypasses chat_with_agent to send inference with the correct model codename.

Usage:
    python cli/eval/harness.py --pass 1 [--dry-run]
    python cli/eval/harness.py --pass 2 [--dry-run]
    python cli/eval/harness.py --single structural oval-kumquat-medium tearing-of-the-page
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

# Ensure cli/ is on the path
CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CLI_DIR not in sys.path:
    sys.path.insert(0, CLI_DIR)

import cookie_extract
import notion_agent_config
import notion_threads
import block_builder
from notion_http import _post
from eval.config import (
    ROLES, MODELS_PASS1, ESSAYS, PASS1_ESSAYS, PASS2_ESSAYS,
    TIMEOUT, COOLDOWN, POLL_INTERVAL, EVAL_DIR,
)


def _get_auth():
    return cookie_extract.get_auth()


def _load_agents_yaml():
    import yaml
    agents_yaml = os.path.join(CLI_DIR, "agents.yaml")
    with open(agents_yaml) as f:
        return yaml.safe_load(f)


def _get_agent_cfg(agent_name: str) -> dict:
    registry = _load_agents_yaml()
    cfg = registry.get(agent_name)
    if not cfg:
        raise ValueError(f"Agent '{agent_name}' not in agents.yaml. Create eval agents first.")
    return cfg


def push_instructions(agent_name: str, instructions_path: str, token: str, user_id: str) -> str:
    """Push instructions from a file to an agent and publish."""
    cfg = _get_agent_cfg(agent_name)
    with open(instructions_path, encoding="utf-8") as f:
        markdown = f.read()

    new_blocks = block_builder.markdown_to_blocks(markdown)
    if not new_blocks:
        raise RuntimeError(f"Instructions at {instructions_path} produced no blocks.")

    # Import diff_replace from notion_client (internal API wrapper)
    import notion_client
    stats = notion_client.diff_replace_block_content(
        cfg["notion_public_id"], cfg["space_id"], new_blocks, token, user_id,
    )

    # Publish
    result = notion_agent_config.publish_agent(
        cfg["notion_internal_id"], cfg["space_id"], token, user_id,
        archive_existing=False,
    )
    return f"Instructions pushed ({stats}), published: {result.get('workflowArtifactId', 'ok')}"


def set_model(agent_name: str, model_codename: str, token: str, user_id: str) -> None:
    """Set the model on a workflow record."""
    cfg = _get_agent_cfg(agent_name)
    notion_agent_config.update_agent_model(
        cfg["notion_internal_id"], cfg["space_id"], model_codename, token, user_id,
    )


def run_single(
    role_key: str,
    model_codename: str,
    model_label: str,
    essay_key: str,
    run_id: str,
    output_dir: str,
    token: str,
    user_id: str,
    dry_run: bool = False,
) -> dict:
    """Execute a single evaluation cell: push message, wait for response, save output."""
    role = ROLES[role_key]
    agent_name = role["agent"]

    meta = {
        "role": role_key,
        "model_codename": model_codename,
        "model_label": model_label,
        "essay": essay_key,
        "agent": agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
    }

    if dry_run:
        print(f"  [DRY RUN] {run_id}: {role_key} x {model_label} x {essay_key}")
        meta["status"] = "dry_run"
        return meta

    cfg = _get_agent_cfg(agent_name)
    essay_path = ESSAYS[essay_key]

    with open(essay_path, encoding="utf-8") as f:
        essay_content = f.read()

    # Create fresh thread
    thread_id = notion_threads.create_workflow_thread(
        cfg["notion_internal_id"], cfg["space_id"], token, user_id,
        title=f"Eval: {role_key} / {model_label} / {essay_key}",
    )
    meta["thread_id"] = thread_id
    print(f"  Thread: {thread_id}", file=sys.stderr)

    # Send message with correct model (retry once on timeout)
    for attempt in range(2):
        try:
            msg_id = notion_threads.send_agent_message(
                thread_id=thread_id,
                space_id=cfg["space_id"],
                notion_internal_id=cfg["notion_internal_id"],
                content=essay_content,
                token_v2=token,
                user_id=user_id,
                model=model_codename,
            )
            break
        except RuntimeError as e:
            if "timed out" in str(e).lower() and attempt == 0:
                print(f"  Inference trigger timed out, retrying in 10s...", file=sys.stderr)
                time.sleep(10)
            else:
                raise
    meta["msg_id"] = msg_id
    print(f"  Message sent: {msg_id}", file=sys.stderr)

    # Wait for response
    response = notion_threads.wait_for_agent_response(
        thread_id, msg_id, token, user_id,
        timeout=TIMEOUT, poll_interval=POLL_INTERVAL,
    )

    if response:
        meta["status"] = "success"
        meta["response_length"] = len(response)
        # Save blinded output
        output_path = os.path.join(output_dir, f"{run_id}.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response)
        print(f"  Saved: {output_path} ({len(response)} chars)", file=sys.stderr)
    else:
        meta["status"] = "timeout"
        print(f"  TIMEOUT after {TIMEOUT}s", file=sys.stderr)

    return meta


def run_matrix(
    pass_num: int,
    models: list[tuple[str, str]],
    essay_keys: list[str],
    dry_run: bool = False,
) -> None:
    """Run the full evaluation matrix for a given pass."""
    output_dir = os.path.join(EVAL_DIR, "results", f"pass{pass_num}")
    os.makedirs(output_dir, exist_ok=True)

    manifest: dict[str, dict] = {}
    manifest_path = os.path.join(output_dir, "manifest.json")

    # Resume from existing manifest if present
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        print(f"Resuming from {len(manifest)} existing runs", file=sys.stderr)

    token, user_id = (None, None) if dry_run else _get_auth()
    run_counter = len(manifest)

    total_runs = len(ROLES) * len(models) * len(essay_keys)
    completed = 0

    # Outer loop: roles (fewer instruction pushes)
    for role_key, role_cfg in ROLES.items():
        agent_name = role_cfg["agent"]
        instructions_path = role_cfg["instructions"]

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"ROLE: {role_key} ({agent_name})", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        # Push role instructions once per role
        if not dry_run:
            print(f"Pushing instructions from {instructions_path}...", file=sys.stderr)
            result = push_instructions(agent_name, instructions_path, token, user_id)
            print(f"  {result}", file=sys.stderr)

        # Inner loop: models
        for model_codename, model_label in models:
            # Set model on workflow
            if not dry_run:
                print(f"\nSetting model: {model_label} ({model_codename})", file=sys.stderr)
                set_model(agent_name, model_codename, token, user_id)

            for essay_key in essay_keys:
                # Check if already completed
                existing = [
                    rid for rid, m in manifest.items()
                    if m["role"] == role_key
                    and m["model_codename"] == model_codename
                    and m["essay"] == essay_key
                    and m.get("status") == "success"
                ]
                if existing:
                    print(f"  Skipping {role_key} x {model_label} x {essay_key} (already done: {existing[0]})", file=sys.stderr)
                    completed += 1
                    continue

                run_counter += 1
                run_id = f"run_{run_counter:03d}"

                print(f"\n[{completed + 1}/{total_runs}] {run_id}: {role_key} x {model_label} x {essay_key}", file=sys.stderr)

                meta = run_single(
                    role_key, model_codename, model_label, essay_key,
                    run_id, output_dir, token, user_id, dry_run,
                )
                manifest[run_id] = meta
                completed += 1

                # Save manifest after each run (crash-safe)
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=2)

                # Cooldown between runs
                if not dry_run and completed < total_runs:
                    print(f"  Cooling down {COOLDOWN}s...", file=sys.stderr)
                    time.sleep(COOLDOWN)

    print(f"\nMatrix complete: {completed}/{total_runs} runs", file=sys.stderr)
    print(f"Manifest: {manifest_path}", file=sys.stderr)

    # Summary
    statuses = {}
    for m in manifest.values():
        s = m.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"Results: {statuses}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Writing Editor model evaluation harness")
    parser.add_argument("--pass", dest="pass_num", type=int, choices=[1, 2, 3], help="Pass number (1=screening, 2=finals, 3=anthropic flagships)")
    parser.add_argument("--dry-run", action="store_true", help="Print matrix plan without sending messages")
    parser.add_argument(
        "--single", nargs=3, metavar=("ROLE", "MODEL_CODENAME", "ESSAY"),
        help="Run a single cell: ROLE MODEL_CODENAME ESSAY",
    )
    args = parser.parse_args()

    if args.single:
        role_key, model_codename, essay_key = args.single
        # Resolve model label
        from notion_agent_config import MODEL_NAMES
        model_label = MODEL_NAMES.get(model_codename, model_codename)
        token, user_id = _get_auth()
        output_dir = os.path.join(EVAL_DIR, "results", "single")
        os.makedirs(output_dir, exist_ok=True)
        run_id = f"single_{role_key}_{model_codename.split('-')[0]}"
        meta = run_single(
            role_key, model_codename, model_label, essay_key,
            run_id, output_dir, token, user_id, args.dry_run,
        )
        print(json.dumps(meta, indent=2))
        return

    if args.pass_num == 1:
        run_matrix(1, MODELS_PASS1, PASS1_ESSAYS, args.dry_run)
    elif args.pass_num == 2:
        # Load pass2 selection if available
        selection_path = os.path.join(EVAL_DIR, "results", "pass1", "pass2_selection.json")
        if os.path.exists(selection_path):
            with open(selection_path) as f:
                selection = json.load(f)
            # Build model list from selection (union of all roles' top picks)
            selected_labels = set()
            for labels in selection.values():
                selected_labels.update(labels)
            # Reverse-map labels to codenames
            from notion_agent_config import MODEL_NAMES
            label_to_code = {v: k for k, v in MODEL_NAMES.items()}
            models = [(label_to_code[lbl], lbl) for lbl in selected_labels if lbl in label_to_code]
            if not models:
                print("No models resolved from pass2_selection.json. Run pass 1 first.", file=sys.stderr)
                sys.exit(1)
        else:
            print("No pass2_selection.json found. Run pass 1 + scoring first.", file=sys.stderr)
            sys.exit(1)
        run_matrix(2, models, PASS2_ESSAYS, args.dry_run)
    elif args.pass_num == 3:
        # Supplemental: Anthropic flagships (Opus + Sonnet) across all roles and essays
        from eval.config import MODELS_ANTHROPIC
        run_matrix(3, MODELS_ANTHROPIC, PASS2_ESSAYS, args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
