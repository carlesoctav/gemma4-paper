#!/usr/bin/env python3
"""Filter SFT dataset against Harbor evaluation results (e.g. termgrade-e4b-think-2)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from datasets import Dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter SFT dataset based on model evaluation outcomes.")
    parser.add_argument(
        "--job-dir",
        type=Path,
        default=Path("jobs/termgrade-e4b-think-2"),
        help="Path to downloaded Harbor job directory containing result.json.",
    )
    parser.add_argument(
        "--sft-dataset",
        type=Path,
        default=Path("termgrade_gemma_think_sft_32k.jsonl"),
        help="Path to SFT dataset JSONL file.",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default="termgrade_gemma_think_sft_32k",
        help="Prefix for generated output files.",
    )
    args = parser.parse_args()

    result_json = args.job_dir / "result.json"
    if not result_json.exists():
        raise FileNotFoundError(f"Missing {result_json}")

    print(f"Reading evaluation results from {result_json} ...")
    with open(result_json, "r", encoding="utf-8") as f:
        job_result = json.load(f)

    eval_stats_dict = job_result.get("stats", {}).get("evals", {})
    if not eval_stats_dict:
        raise ValueError("No evaluation stats found in result.json")

    eval_name, eval_data = next(iter(eval_stats_dict.items()))
    print(f"Loaded evaluation: {eval_name}")

    rewards_dict = eval_data.get("reward_stats", {}).get("reward", {})
    succeeded_trials = rewards_dict.get("1.0", [])
    failed_trials = rewards_dict.get("0.0", [])

    succeeded_tasks = sorted(list(set(t.split("__")[0] for t in succeeded_trials)))
    failed_tasks = sorted(list(set(t.split("__")[0] for t in failed_trials)))
    succeeded_set = set(succeeded_tasks)

    print(f"Job evaluation summary:")
    print(f"  Total trials with reward == 1.0: {len(succeeded_trials)} (unique tasks: {len(succeeded_tasks)})")
    print(f"  Total trials with reward == 0.0: {len(failed_trials)} (unique tasks: {len(failed_tasks)})")

    # Save task lists
    tasks_meta = {
        "job_name": args.job_dir.name,
        "eval_name": eval_name,
        "succeeded_task_count": len(succeeded_tasks),
        "failed_task_count": len(failed_tasks),
        "succeeded_tasks": succeeded_tasks,
        "failed_tasks": failed_tasks,
    }
    tasks_meta_path = Path(f"{args.output_prefix}_eval_tasks.json")
    with open(tasks_meta_path, "w", encoding="utf-8") as f:
        json.dump(tasks_meta, f, indent=2)
    print(f"Saved evaluation task lists to {tasks_meta_path}")

    # Load SFT dataset
    print(f"\nLoading SFT dataset from {args.sft_dataset} ...")
    with open(args.sft_dataset, "r", encoding="utf-8") as f:
        sft_rows = [json.loads(line) for line in f if line.strip()]

    total_sft = len(sft_rows)
    all_sft_tasks = set(r["task"] for r in sft_rows)
    print(f"Loaded {total_sft} SFT samples across {len(all_sft_tasks)} unique tasks.")

    # Partition dataset into:
    # 1. Samples where the evaluated model succeeded (tasks in succeeded_set)
    # 2. Samples where the evaluated model failed / did not succeed (tasks not in succeeded_set)
    succeeded_samples = [r for r in sft_rows if r.get("task") in succeeded_set]
    unsolved_samples = [r for r in sft_rows if r.get("task") not in succeeded_set]

    succeeded_tasks_in_sft = set(r["task"] for r in succeeded_samples)
    unsolved_tasks_in_sft = set(r["task"] for r in unsolved_samples)

    print("\n" + "=" * 70)
    print("SFT PARTITION BREAKDOWN")
    print("=" * 70)
    print(
        f"Tasks E4B succeeded on in SFT dataset: {len(succeeded_tasks_in_sft)} / {len(succeeded_tasks)} "
        f"({len(succeeded_samples)} samples, {len(succeeded_samples)/total_sft*100:.1f}%)"
    )
    print(
        f"Tasks E4B unsolved/failed on in SFT dataset: {len(unsolved_tasks_in_sft)} "
        f"({len(unsolved_samples)} samples, {len(unsolved_samples)/total_sft*100:.1f}%)"
    )

    # Save succeeded subset (both JSONL and Arrow)
    succeeded_jsonl = Path(f"{args.output_prefix}_succeeded.jsonl")
    with open(succeeded_jsonl, "w", encoding="utf-8") as f:
        for r in succeeded_samples:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote succeeded subset to {succeeded_jsonl.resolve()} ({len(succeeded_samples)} samples)")

    succeeded_arrow_dir = Path(f"{args.output_prefix}_succeeded")
    Dataset.from_list(succeeded_samples).save_to_disk(str(succeeded_arrow_dir))
    print(f"Saved succeeded Arrow dataset to {succeeded_arrow_dir.resolve()}")

    # Save unsolved/failed subset (both JSONL and Arrow)
    unsolved_jsonl = Path(f"{args.output_prefix}_unsolved.jsonl")
    with open(unsolved_jsonl, "w", encoding="utf-8") as f:
        for r in unsolved_samples:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote unsolved subset to {unsolved_jsonl.resolve()} ({len(unsolved_samples)} samples)")

    unsolved_arrow_dir = Path(f"{args.output_prefix}_unsolved")
    Dataset.from_list(unsolved_samples).save_to_disk(str(unsolved_arrow_dir))
    print(f"Saved unsolved Arrow dataset to {unsolved_arrow_dir.resolve()}")


if __name__ == "__main__":
    main()
