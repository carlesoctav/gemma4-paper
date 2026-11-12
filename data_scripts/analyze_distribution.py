#!/usr/bin/env python3
"""Compute token and message length distribution for SFT dataset."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from transformers import AutoTokenizer

DEFAULT_TOKENIZER_PATH = (
    "/home/carlesoctav/.cache/huggingface/hub/models--google--gemma-4-31b-it-qat-w4a16-ct"
    "/snapshots/52f3f65bc7a02d555763bc923bd1d9094898219d"
)


def compute_stats(data: list[int]) -> dict[str, float]:
    if not data:
        return {}
    arr = np.array(data)
    return {
        "count": len(arr),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": int(np.min(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": int(np.max(arr)),
    }


def ascii_histogram(data: list[int], bins: int = 10, max_bar_width: int = 40) -> str:
    if not data:
        return ""
    counts, bin_edges = np.histogram(data, bins=bins)
    max_count = max(counts) if max(counts) > 0 else 1
    lines = []
    for count, edge_start, edge_end in zip(counts, bin_edges[:-1], bin_edges[1:]):
        bar_len = int(round((count / max_count) * max_bar_width))
        bar = "█" * bar_len
        pct = (count / len(data)) * 100
        lines.append(f"  [{int(edge_start):6d} - {int(edge_end):6d}] : {count:4d} ({pct:5.1f}%) | {bar}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze token length distribution.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("sft_dataset_inkling_f2p.jsonl"),
        help="Path to JSONL dataset.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_TOKENIZER_PATH,
        help="Path to tokenizer.",
    )
    args = parser.parse_args()

    print(f"Loading dataset from {args.dataset} ...")
    with open(args.dataset, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(samples)} samples.")
    print(f"Loading tokenizer from {args.model} ...")
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    print("Tokenizing samples to compute lengths...")
    total_token_lengths = []
    trained_token_lengths = []
    ignored_token_lengths = []
    num_messages_list = []

    by_type_total: dict[str, list[int]] = defaultdict(list)
    by_type_trained: dict[str, list[int]] = defaultdict(list)
    by_type_messages: dict[str, list[int]] = defaultdict(list)

    for i, s in enumerate(samples):
        msgs = s["messages"]
        tools = s.get("tools")
        stype = s.get("type", "unknown")

        if tools:
            formatted = tokenizer.apply_chat_template(msgs, tools=tools, tokenize=False)
        else:
            formatted = tokenizer.apply_chat_template(msgs, tokenize=False)

        ids = tokenizer.encode(formatted, add_special_tokens=False)
        tok_len = len(ids)

        # Estimate assistant trained tokens: content of assistant messages + tool calls
        # Let's count assistant turn tokens
        asst_text = ""
        for m in msgs:
            if m["role"] == "assistant":
                if m.get("content"):
                    asst_text += m["content"] + "\n"
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        asst_text += json.dumps(tc.get("function", {})) + "\n"

        asst_ids = tokenizer.encode(asst_text, add_special_tokens=False)
        trained_len = min(len(asst_ids), tok_len)
        ignored_len = max(0, tok_len - trained_len)

        total_token_lengths.append(tok_len)
        trained_token_lengths.append(trained_len)
        ignored_token_lengths.append(ignored_len)
        num_messages_list.append(len(msgs))

        by_type_total[stype].append(tok_len)
        by_type_trained[stype].append(trained_len)
        by_type_messages[stype].append(len(msgs))

        if (i + 1) % 25 == 0 or (i + 1) == len(samples):
            print(f"  Processed {i + 1}/{len(samples)} samples...")

    # Overall Summary
    stats = compute_stats(total_token_lengths)
    trained_stats = compute_stats(trained_token_lengths)
    msg_stats = compute_stats(num_messages_list)

    print("\n" + "=" * 80)
    print("OVERALL TOKEN LENGTH DISTRIBUTION (Total Tokens per SFT Sample)")
    print("=" * 80)
    print(
        f"Count: {stats['count']} | Mean: {stats['mean']:.1f} ± {stats['std']:.1f} | "
        f"Min: {stats['min']} | P50 (Median): {stats['p50']:.0f} | "
        f"P90: {stats['p90']:.0f} | P95: {stats['p95']:.0f} | P99: {stats['p99']:.0f} | Max: {stats['max']}"
    )
    print("\nPercentiles:")
    print(f"  Min:   {stats['min']:6d}")
    print(f"  P25:   {int(stats['p25']):6d}")
    print(f"  P50:   {int(stats['p50']):6d}  (Median)")
    print(f"  P75:   {int(stats['p75']):6d}")
    print(f"  P90:   {int(stats['p90']):6d}")
    print(f"  P95:   {int(stats['p95']):6d}")
    print(f"  P99:   {int(stats['p99']):6d}")
    print(f"  Max:   {stats['max']:6d}")

    print("\nHistogram (Token Count Ranges):")
    print(ascii_histogram(total_token_lengths, bins=12))

    print("\n" + "=" * 80)
    print("TRAINED (ASSISTANT) TOKEN LENGTH DISTRIBUTION")
    print("=" * 80)
    print(
        f"Mean: {trained_stats['mean']:.1f} | Min: {trained_stats['min']} | "
        f"P50: {trained_stats['p50']:.0f} | P90: {trained_stats['p90']:.0f} | Max: {trained_stats['max']}"
    )

    print("\n" + "=" * 80)
    print("DISTRIBUTION BY SAMPLE TYPE")
    print("=" * 80)
    header = f"{'Type':<15} | {'Count':<5} | {'Mean Toks':<10} | {'Median':<8} | {'P90':<8} | {'Max Toks':<8} | {'Mean Msgs':<9}"
    print(header)
    print("-" * len(header))

    type_order = ["main", "compaction", "main_2", "compaction_2", "main_3", "compaction_3", "main_4"]
    for t in type_order:
        if t in by_type_total:
            t_toks = by_type_total[t]
            t_msgs = by_type_messages[t]
            t_stats = compute_stats(t_toks)
            m_stats = compute_stats(t_msgs)
            print(
                f"{t:<15} | {len(t_toks):<5d} | {t_stats['mean']:<10.1f} | {int(t_stats['p50']):<8d} | "
                f"{int(t_stats['p90']):<8d} | {t_stats['max']:<8d} | {m_stats['mean']:<9.1f}"
            )

    # Save summary as json
    out_json = args.dataset.with_name(args.dataset.stem + "_length_dist.json")
    summary = {
        "overall_total_tokens": stats,
        "overall_trained_tokens": trained_stats,
        "overall_messages": msg_stats,
        "by_type": {
            t: {
                "count": len(by_type_total[t]),
                "total_tokens": compute_stats(by_type_total[t]),
                "trained_tokens": compute_stats(by_type_trained[t]),
                "messages": compute_stats(by_type_messages[t]),
            }
            for t in by_type_total
        },
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved detailed distribution metrics to {out_json}")


if __name__ == "__main__":
    main()
