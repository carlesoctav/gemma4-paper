#!/usr/bin/env python3
"""Build TermGrade train/test split and training SFT dataset.

Pipeline:
  1. 1,004 tasks from termgrade
  2. Identify failed tasks from Harbor evaluation (e.g. google/gemma-4-E4B-it)
  3. Select 100 heldout tasks from failed tasks as the test set
  4. Designate remaining tasks as train tasks
  5. Filter Gemma 4 rollouts: reward == 1, task in remaining train tasks, length <= 32k tokens
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


def load_termgrade_tasks(termgrade_dir: Path | None, job_dir: Path) -> list[str]:
    """Load all 1,004 TermGrade task identifiers."""
    if termgrade_dir and termgrade_dir.exists():
        tasks = [d.name for d in termgrade_dir.iterdir() if d.is_dir() and d.name.startswith("task_")]
        if tasks:
            return sorted(tasks)

    # Fallback to job directories if benchmark repo not provided
    tasks = sorted(list(set(d.name.split("__")[0] for d in job_dir.iterdir() if d.is_dir() and d.name.startswith("task_"))))
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Partition TermGrade tasks and build training SFT dataset.")
    parser.add_argument(
        "--termgrade-dir",
        type=Path,
        default=Path("/home/carlesoctav/personal/hill-climb-gemma4-compe/termgrade"),
        help="Path to TermGrade benchmark directory with task folders.",
    )
    parser.add_argument(
        "--job-dir",
        type=Path,
        default=Path("/home/carlesoctav/personal/make_data_from_trace/jobs/termgrade-e4b-think-2"),
        help="Path to Harbor evaluation job directory containing result.json.",
    )
    parser.add_argument(
        "--sft-input",
        type=Path,
        default=Path("/home/carlesoctav/personal/final_term/data/termgrade_gemma_think_sft_32k.jsonl"),
        help="Path to pre-filtered Gemma 4 Think SFT 32k dataset.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/home/carlesoctav/personal/final_term/data"),
        help="Directory to save train/test task lists and training SFT dataset.",
    )
    parser.add_argument(
        "--n-heldout",
        type=int,
        default=100,
        help="Number of heldout tasks for test set (default: 100).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic heldout task selection (default: 42).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=32768,
        help="Maximum token sequence length (default: 32768).",
    )
    parser.add_argument(
        "--solvable-only",
        action="store_true",
        help="Sample heldout tasks only from failed tasks that have at least one successful SFT rollout.",
    )
    parser.add_argument(
        "--train-failed-only",
        action="store_true",
        help="Restrict training pool to remaining failed tasks only (excludes tasks base model succeeded on).",
    )

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load all TermGrade tasks
    all_tasks = load_termgrade_tasks(args.termgrade_dir, args.job_dir)
    print(f"Loaded {len(all_tasks)} total tasks from TermGrade.")

    # 2. Load evaluation outcomes from Harbor job
    result_json_path = args.job_dir / "result.json"
    with open(result_json_path, "r", encoding="utf-8") as f:
        job_result = json.load(f)

    eval_stats_dict = job_result["stats"]["evals"]
    eval_name, eval_data = next(iter(eval_stats_dict.items()))
    print(f"Loaded evaluation: {eval_name}")

    rewards_dict = eval_data["reward_stats"]["reward"]
    succeeded_trials = rewards_dict.get("1.0", [])
    failed_trials = rewards_dict.get("0.0", [])

    succeeded_tasks = sorted(list(set(t.split("__")[0] for t in succeeded_trials)))
    failed_tasks_eval = sorted(list(set(t.split("__")[0] for t in failed_trials)))
    all_non_succeeded_tasks = sorted(list(set(all_tasks) - set(succeeded_tasks)))

    print(f"Evaluation outcomes:")
    print(f"  Succeeded tasks (reward == 1.0): {len(succeeded_tasks)}")
    print(f"  Failed tasks (reward == 0.0): {len(failed_tasks_eval)}")
    print(f"  Total non-succeeded tasks (1,004 - {len(succeeded_tasks)}): {len(all_non_succeeded_tasks)}")

    # 3. Load SFT rollouts
    print(f"\nLoading Gemma 4 rollouts from {args.sft_input} ...")
    sft_rows: list[dict[str, Any]] = []
    with open(args.sft_input, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                sft_rows.append(json.loads(line_str))

    print(f"Loaded {len(sft_rows)} rollouts across {len(set(r['task'] for r in sft_rows))} unique tasks.")

    # Filter rollouts by reward == 1 and max_tokens
    valid_sft_rows = [
        r for r in sft_rows
        if r.get("reward") == 1.0 and r.get("num_tokens", 0) <= args.max_tokens
    ]
    print(f"Rollouts with reward == 1.0 and length <= {args.max_tokens}: {len(valid_sft_rows)}")

    sft_task_set = set(r["task"] for r in valid_sft_rows)

    # 4. Determine candidate pool for heldout test set
    if args.solvable_only:
        candidate_pool = sorted(list(set(failed_tasks_eval) & sft_task_set))
        print(f"Heldout candidate pool (failed & solvable): {len(candidate_pool)} tasks")
    else:
        candidate_pool = failed_tasks_eval
        print(f"Heldout candidate pool (all verified failed tasks): {len(candidate_pool)} tasks")

    # Sample 100 heldout tasks deterministically
    rng = random.Random(args.seed)
    heldout_tasks = sorted(rng.sample(candidate_pool, args.n_heldout))
    heldout_task_set = set(heldout_tasks)
    print(f"Selected {len(heldout_tasks)} heldout test tasks (seed={args.seed}).")

    # 5. Determine remaining train tasks
    train_tasks_all = sorted(list(set(all_tasks) - heldout_task_set))
    train_tasks_failed = sorted(list(set(failed_tasks_eval) - heldout_task_set))

    print(f"Train task pools:")
    print(f"  All remaining tasks: {len(train_tasks_all)} tasks (1004 total - 100 heldout)")
    print(f"  Remaining failed tasks: {len(train_tasks_failed)} tasks (665 failed - 100 heldout)")

    # 6. Filter rollouts based on remaining train tasks
    train_all_sft_rows = [r for r in valid_sft_rows if r["task"] in set(train_tasks_all)]
    train_failed_sft_rows = [r for r in valid_sft_rows if r["task"] in set(train_tasks_failed)]

    train_all_unique_tasks = set(r["task"] for r in train_all_sft_rows)
    train_failed_unique_tasks = set(r["task"] for r in train_failed_sft_rows)

    print("\n" + "=" * 70)
    print("SPLIT SUMMARY")
    print("=" * 70)
    print(f"Total TermGrade tasks: {len(all_tasks)}")
    print(f"Heldout test tasks: {len(heldout_tasks)}")
    print(f"Train tasks (all remaining): {len(train_tasks_all)} -> SFT rollouts: {len(train_all_sft_rows)} across {len(train_all_unique_tasks)} tasks")
    print(f"Train tasks (failed remaining): {len(train_tasks_failed)} -> SFT rollouts: {len(train_failed_sft_rows)} across {len(train_failed_unique_tasks)} tasks")
    print(f"Heldout tasks with zero train data leakage: {len(heldout_task_set & train_all_unique_tasks)} overlap (must be 0)")
    assert len(heldout_task_set & train_all_unique_tasks) == 0, "FATAL: Data leakage detected between test and train!"

    # Token length statistics for training set (all remaining)
    token_counts = [r["num_tokens"] for r in train_all_sft_rows]
    token_counts.sort()
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0
    p50_tokens = token_counts[len(token_counts) // 2] if token_counts else 0
    p90_tokens = token_counts[int(len(token_counts) * 0.9)] if token_counts else 0
    max_tokens_val = max(token_counts) if token_counts else 0
    min_tokens_val = min(token_counts) if token_counts else 0

    print(f"\nToken statistics for training set (all remaining):")
    print(f"  Min: {min_tokens_val:,} | P50: {p50_tokens:,} | Mean: {avg_tokens:,.0f} | P90: {p90_tokens:,} | Max: {max_tokens_val:,}")

    # 7. Save outputs
    heldout_json_path = args.output_dir / "heldout_test_tasks_100.json"
    heldout_txt_path = args.output_dir / "heldout_test_tasks_100.txt"
    train_tasks_json_path = args.output_dir / "train_tasks.json"
    train_tasks_txt_path = args.output_dir / "train_tasks.txt"
    train_failed_tasks_txt_path = args.output_dir / "train_failed_tasks.txt"
    train_sft_path = args.output_dir / "termgrade_train_sft_32k.jsonl"
    train_failed_sft_path = args.output_dir / "termgrade_train_failed_sft_32k.jsonl"
    summary_path = args.output_dir / "termgrade_split_summary.json"

    # Heldout tasks files
    heldout_metadata = {
        "n_heldout": len(heldout_tasks),
        "seed": args.seed,
        "solvable_only": args.solvable_only,
        "eval_source": eval_name,
        "tasks": heldout_tasks,
    }
    with open(heldout_json_path, "w", encoding="utf-8") as f:
        json.dump(heldout_metadata, f, indent=2)

    with open(heldout_txt_path, "w", encoding="utf-8") as f:
        for t in heldout_tasks:
            f.write(f"{t}\n")

    # Train tasks files
    with open(train_tasks_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "n_train_tasks_all": len(train_tasks_all),
            "train_tasks_all": train_tasks_all,
            "n_train_tasks_failed": len(train_tasks_failed),
            "train_tasks_failed": train_tasks_failed,
        }, f, indent=2)

    with open(train_tasks_txt_path, "w", encoding="utf-8") as f:
        for t in train_tasks_all:
            f.write(f"{t}\n")

    with open(train_failed_tasks_txt_path, "w", encoding="utf-8") as f:
        for t in train_tasks_failed:
            f.write(f"{t}\n")

    # Training SFT datasets
    print(f"\nWriting training SFT dataset (all remaining) to {train_sft_path} ...")
    with open(train_sft_path, "w", encoding="utf-8") as f:
        for r in train_all_sft_rows:
            f.write(json.dumps(r) + "\n")

    print(f"Writing training SFT dataset (failed remaining) to {train_failed_sft_path} ...")
    with open(train_failed_sft_path, "w", encoding="utf-8") as f:
        for r in train_failed_sft_rows:
            f.write(json.dumps(r) + "\n")

    # Split summary report
    summary = {
        "total_termgrade_tasks": len(all_tasks),
        "eval_job": str(args.job_dir.name),
        "eval_name": eval_name,
        "eval_succeeded_count": len(succeeded_tasks),
        "eval_failed_count": len(failed_tasks_eval),
        "all_non_succeeded_count": len(all_non_succeeded_tasks),
        "heldout_test_tasks_count": len(heldout_tasks),
        "train_tasks_all_count": len(train_tasks_all),
        "train_tasks_failed_count": len(train_tasks_failed),
        "train_all_sft_rows_count": len(train_all_sft_rows),
        "train_all_sft_unique_tasks_count": len(train_all_unique_tasks),
        "train_failed_sft_rows_count": len(train_failed_sft_rows),
        "train_failed_sft_unique_tasks_count": len(train_failed_unique_tasks),
        "token_stats_all": {
            "min": min_tokens_val,
            "p50": p50_tokens,
            "mean": round(avg_tokens, 1),
            "p90": p90_tokens,
            "max": max_tokens_val,
        },
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSaved files:")
    print(f"  1. {heldout_json_path}")
    print(f"  2. {heldout_txt_path}")
    print(f"  3. {train_tasks_json_path}")
    print(f"  4. {train_tasks_txt_path}")
    print(f"  5. {train_failed_tasks_txt_path}")
    print(f"  6. {train_sft_path} ({train_sft_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"  7. {train_failed_sft_path} ({train_failed_sft_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"  8. {summary_path}")


if __name__ == "__main__":
    main()

