#!/usr/bin/env python3
"""Blind scoring, reveal, and ranking for the evaluation matrix.

Usage:
    python cli/eval/scoring.py export-blind results/pass1
    python cli/eval/scoring.py record-score run_001 structural '{"contribution_accuracy":4,"macro_form_classification":3,...}'
    python cli/eval/scoring.py reveal results/pass1
    python cli/eval/scoring.py select-pass2 results/pass1 --top 2
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path


def export_blind(pass_dir: str) -> None:
    """Print blinded outputs in shuffled order for manual scoring."""
    manifest_path = os.path.join(pass_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"No manifest found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Group by role for sequential scoring
    by_role: dict[str, list[str]] = {}
    for run_id, meta in manifest.items():
        role = meta["role"]
        by_role.setdefault(role, []).append(run_id)

    for role in sorted(by_role):
        run_ids = by_role[role]
        random.shuffle(run_ids)
        print(f"\n{'='*72}")
        print(f"ROLE: {role} — {len(run_ids)} responses (shuffled)")
        print(f"{'='*72}\n")

        for run_id in run_ids:
            output_path = os.path.join(pass_dir, f"{run_id}.md")
            if not os.path.exists(output_path):
                print(f"[{run_id}] OUTPUT MISSING\n")
                continue

            with open(output_path) as f:
                content = f.read()

            print(f"--- {run_id} ---")
            print(content)
            print(f"--- end {run_id} ---\n")


def record_score(run_id: str, role: str, scores_json: str, scores_dir: str) -> None:
    """Record dimension scores for a blinded run."""
    os.makedirs(scores_dir, exist_ok=True)
    scores_file = os.path.join(scores_dir, f"{role}_scores.json")

    existing = {}
    if os.path.exists(scores_file):
        with open(scores_file) as f:
            existing = json.load(f)

    scores = json.loads(scores_json)
    existing[run_id] = scores

    with open(scores_file, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"Recorded scores for {run_id} in {scores_file}", file=sys.stderr)


def reveal(pass_dir: str) -> dict:
    """Unseal manifest, compute per-model averages, rank by role."""
    manifest_path = os.path.join(pass_dir, "manifest.json")
    scores_dir = os.path.join(pass_dir, "..", "scores")

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Collect all scores by role
    rankings: dict[str, list[dict]] = {}

    for role in set(m["role"] for m in manifest.values()):
        scores_file = os.path.join(scores_dir, f"{role}_scores.json")
        if not os.path.exists(scores_file):
            print(f"No scores found for role '{role}' at {scores_file}", file=sys.stderr)
            continue

        with open(scores_file) as f:
            scores = json.load(f)

        # Aggregate by model
        model_totals: dict[str, dict] = {}  # model_label -> {sum, count, dims}
        for run_id, dim_scores in scores.items():
            meta = manifest.get(run_id)
            if not meta:
                print(f"Warning: {run_id} in scores but not in manifest", file=sys.stderr)
                continue
            model_label = meta["model_label"]
            if model_label not in model_totals:
                model_totals[model_label] = {"sum": 0, "count": 0, "dims": {}}
            for dim, score in dim_scores.items():
                model_totals[model_label]["sum"] += score
                model_totals[model_label]["count"] += 1
                model_totals[model_label]["dims"].setdefault(dim, []).append(score)

        # Compute averages and rank
        ranked = []
        for model_label, data in model_totals.items():
            avg = data["sum"] / data["count"] if data["count"] else 0
            dim_avgs = {dim: sum(vals)/len(vals) for dim, vals in data["dims"].items()}
            ranked.append({
                "model": model_label,
                "average": round(avg, 2),
                "dimensions": {k: round(v, 2) for k, v in dim_avgs.items()},
            })
        ranked.sort(key=lambda x: x["average"], reverse=True)
        rankings[role] = ranked

    # Print results
    for role, models in rankings.items():
        print(f"\n{'='*50}")
        print(f"ROLE: {role}")
        print(f"{'='*50}")
        for i, entry in enumerate(models, 1):
            print(f"  {i}. {entry['model']} — avg {entry['average']}")
            for dim, avg in entry["dimensions"].items():
                print(f"     {dim}: {avg}")

    # Save rankings
    rankings_path = os.path.join(pass_dir, "rankings.json")
    with open(rankings_path, "w") as f:
        json.dump(rankings, f, indent=2)
    print(f"\nRankings saved to {rankings_path}", file=sys.stderr)

    return rankings


def select_pass2(pass_dir: str, top_n: int = 2) -> dict[str, list[str]]:
    """Pick top N models per role for Pass 2."""
    rankings_path = os.path.join(pass_dir, "rankings.json")
    if not os.path.exists(rankings_path):
        print("Run 'reveal' first to generate rankings.", file=sys.stderr)
        sys.exit(1)

    with open(rankings_path) as f:
        rankings = json.load(f)

    selection: dict[str, list[str]] = {}
    for role, models in rankings.items():
        selected = [m["model"] for m in models[:top_n]]
        selection[role] = selected
        print(f"{role}: {', '.join(selected)}")

    selection_path = os.path.join(pass_dir, "pass2_selection.json")
    with open(selection_path, "w") as f:
        json.dump(selection, f, indent=2)
    print(f"\nSelection saved to {selection_path}", file=sys.stderr)

    return selection


def main():
    parser = argparse.ArgumentParser(description="Evaluation scoring tools")
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export-blind", help="Print blinded outputs for scoring")
    p_export.add_argument("pass_dir", help="Path to pass results directory")

    p_record = sub.add_parser("record-score", help="Record scores for a run")
    p_record.add_argument("run_id", help="Blinded run ID (e.g. run_001)")
    p_record.add_argument("role", help="Role name")
    p_record.add_argument("scores_json", help="JSON string of dimension scores")
    p_record.add_argument("--scores-dir", default=None, help="Scores output directory")

    p_reveal = sub.add_parser("reveal", help="Unseal manifest and rank models")
    p_reveal.add_argument("pass_dir", help="Path to pass results directory")

    p_select = sub.add_parser("select-pass2", help="Select top models for Pass 2")
    p_select.add_argument("pass_dir", help="Path to pass results directory")
    p_select.add_argument("--top", type=int, default=2, help="Number of models to select per role")

    args = parser.parse_args()

    if args.command == "export-blind":
        export_blind(args.pass_dir)
    elif args.command == "record-score":
        scores_dir = args.scores_dir or os.path.join(os.path.dirname(args.pass_dir) if args.pass_dir else ".", "scores")
        record_score(args.run_id, args.role, args.scores_json, scores_dir)
    elif args.command == "reveal":
        reveal(args.pass_dir)
    elif args.command == "select-pass2":
        select_pass2(args.pass_dir, args.top)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
