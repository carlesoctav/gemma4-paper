#!/usr/bin/env python3
"""Analyze gemma_think trajectories from ai-and/termgrade-trajectories (reward == 1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def compute_stats(arr: np.ndarray) -> dict[str, float]:
    if len(arr) == 0:
        return {}
    return {
        "count": len(arr),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
    }


def ascii_bar(count: int, max_count: int, width: int = 30) -> str:
    if max_count <= 0:
        return ""
    return "█" * int(round(count / max_count * width))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze ai-and/termgrade-trajectories dataset.")
    parser.add_argument(
        "--parquet-url",
        type=str,
        default="hf://datasets/ai-and/termgrade-trajectories/data/messages/gemma_think.parquet",
        help="Path or HuggingFace URL to gemma_think.parquet",
    )
    parser.add_argument(
        "--min-reward",
        type=float,
        default=1.0,
        help="Filter trials by minimum reward (default: 1.0).",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("termgrade_gemma_think_dist.json"),
        help="Output JSON summary path.",
    )
    args = parser.parse_args()

    print(f"Loading {args.parquet_url} ...")
    df = pd.read_parquet(args.parquet_url)
    total_trials = len(df)
    print(f"Total rows in dataset: {total_trials}")

    df_filtered = df[df["reward"] >= args.min_reward].copy()
    filtered_count = len(df_filtered)
    unique_tasks = df_filtered["task"].nunique()
    pass_rate = (filtered_count / total_trials * 100) if total_trials else 0.0

    print(f"\nFiltered (reward >= {args.min_reward}): {filtered_count} / {total_trials} ({pass_rate:.1f}%)")
    print(f"Unique tasks solved: {unique_tasks}")

    df_filtered["total_tokens"] = df_filtered["prompt_tokens"] + df_filtered["output_tokens"]

    stats_prompt = compute_stats(df_filtered["prompt_tokens"].dropna().to_numpy())
    stats_output = compute_stats(df_filtered["output_tokens"].dropna().to_numpy())
    stats_total = compute_stats(df_filtered["total_tokens"].dropna().to_numpy())
    stats_turns = compute_stats(df_filtered["turns_total"].dropna().to_numpy())
    stats_dur = compute_stats(df_filtered["duration_s"].dropna().to_numpy())

    # Reasoning vs content
    reasoning_chars = []
    content_chars = []
    reasoning_ratios = []
    for msgs in df_filtered["messages"]:
        r_c = sum(len(m.get("reasoning_content") or "") for m in msgs if m.get("role") == "assistant")
        c_c = sum(len(m.get("content") or "") for m in msgs if m.get("role") == "assistant")
        reasoning_chars.append(r_c)
        content_chars.append(c_c)
        if (r_c + c_c) > 0:
            reasoning_ratios.append(r_c / (r_c + c_c))

    stats_reasoning = compute_stats(np.array(reasoning_chars))
    stats_content = compute_stats(np.array(content_chars))

    summary = {
        "dataset": "ai-and/termgrade-trajectories",
        "model": "gemma_think",
        "total_trials": total_trials,
        "filtered_trials": filtered_count,
        "pass_rate_pct": pass_rate,
        "unique_tasks_solved": unique_tasks,
        "prompt_tokens": stats_prompt,
        "output_tokens": stats_output,
        "total_tokens": stats_total,
        "turns_total": stats_turns,
        "duration_s": stats_dur,
        "assistant_reasoning_chars": stats_reasoning,
        "assistant_content_chars": stats_content,
        "mean_thinking_share_pct": float(np.mean(reasoning_ratios) * 100),
    }

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved metrics summary to {args.output_json.resolve()}")


if __name__ == "__main__":
    main()
