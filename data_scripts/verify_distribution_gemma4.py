#!/usr/bin/env python3
"""Run multi-core distribution comparison and verification on gemma4."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
from datasets import load_dataset
from transformers import AutoTokenizer

PARQUET_PATH = Path("/root/.cache/huggingface/hub/datasets--ai-and--termgrade-trajectories/snapshots/e0297725c7dc63ac4efa228c47f228f94b64db3e/data/messages/gemma_think.parquet")
TRAIN_TASKS_PATH = Path("/root/final_term/train_tasks.txt")
TEMPLATE_PATH = Path("/root/final_term/chat_template.jinja")

_TOKENIZER = None


def init_worker():
    global _TOKENIZER
    _TOKENIZER = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        _TOKENIZER.chat_template = f.read()


def process_row(args):
    # args: (prompt, completion)
    prompt, completion = args
    rendered = _TOKENIZER.apply_chat_template(prompt + completion, tokenize=False)
    tok_len = len(_TOKENIZER.encode(rendered, add_special_tokens=False))
    thought_count = rendered.count("<|channel>thought")
    return tok_len, thought_count, rendered


def main() -> None:
    print("Initializing tokenizer...")
    tok = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        tok.chat_template = f.read()

    with open(TRAIN_TASKS_PATH, "r", encoding="utf-8") as f:
        train_tasks = set(line.strip() for line in f if line.strip())

    print(f"Reading parquet from {PARQUET_PATH}...")
    df = pd.read_parquet(PARQUET_PATH)
    df_filtered = df[
        (df["model"] == "gemma_think")
        & (df["reward"] == 1.0)
        & (df["task"].isin(train_tasks))
    ].copy()
    print(f"Filtered: {len(df_filtered)} trials across {df_filtered['task'].nunique()} tasks.")

    # 1. Trajectory lengths to determine p95
    print("Calculating trajectory lengths for p95 threshold...")
    valid_trials = []
    traj_lengths = []
    for _, row in df_filtered.iterrows():
        raw_msgs = row["messages"]
        if raw_msgs is None:
            continue
        msgs = [dict(m) for m in raw_msgs]
        while msgs and msgs[-1].get("role") != "assistant":
            msgs.pop()
        if not any(m.get("role") == "assistant" for m in msgs):
            continue
        rendered = tok.apply_chat_template(msgs, tokenize=False)
        tlen = len(tok.encode(rendered, add_special_tokens=False))
        traj_lengths.append(tlen)
        valid_trials.append((row, msgs, tlen))

    p95_threshold = float(np.percentile(traj_lengths, 95))
    print(f"p95 Threshold: {p95_threshold:.1f} tokens")
    p95_trials = [t for t in valid_trials if t[2] <= p95_threshold]
    print(f"Trials under p95: {len(p95_trials)} / {len(valid_trials)}")

    # 2. Build two sets of split records:
    # A: WITH reasoning preserved in prompt
    # B: WITHOUT reasoning in prompt (sanitized)
    print("Building split records for both configurations...")
    records_with_reasoning = []
    records_without_reasoning = []

    for row, msgs, _ in p95_trials:
        assistant_indices = [i for i, m in enumerate(msgs) if m.get("role") == "assistant"]
        for turn_idx, a_idx in enumerate(assistant_indices, start=1):
            raw_prompt_msgs = msgs[:a_idx]

            # With reasoning
            prompt_with = []
            for m in raw_prompt_msgs:
                role = m.get("role", "user")
                content = m.get("content") or ""
                entry = {"role": role, "content": content}
                if role == "assistant" and m.get("reasoning_content"):
                    entry["reasoning_content"] = m["reasoning_content"]
                prompt_with.append(entry)

            # Without reasoning
            prompt_without = []
            for m in raw_prompt_msgs:
                role = m.get("role", "user")
                content = m.get("content") or ""
                prompt_without.append({"role": role, "content": content})

            target_assistant = msgs[a_idx]
            target_content = target_assistant.get("content") or ""
            target_reasoning = target_assistant.get("reasoning_content") or ""
            completion = [{"role": "assistant", "content": target_content}]
            if target_reasoning:
                completion[0]["reasoning_content"] = target_reasoning

            records_with_reasoning.append((prompt_with, completion))
            records_without_reasoning.append((prompt_without, completion))

    total_records = len(records_with_reasoning)
    print(f"Total split records: {total_records}")

    # 3. Parallel evaluation using 12 CPU workers
    print("\nRunning multi-core evaluation across 12 CPUs...")
    with ProcessPoolExecutor(max_workers=12, initializer=init_worker) as executor:
        print("  Evaluating configuration A (prompt WITH reasoning_content)...")
        results_with = list(executor.map(process_row, records_with_reasoning, chunksize=100))
        print("  Evaluating configuration B (prompt WITHOUT reasoning_content)...")
        results_without = list(executor.map(process_row, records_without_reasoning, chunksize=100))

    lens_with = [r[0] for r in results_with]
    thoughts_with = [r[1] for r in results_with]
    texts_with = [r[2] for r in results_with]

    lens_without = [r[0] for r in results_without]
    thoughts_without = [r[1] for r in results_without]
    texts_without = [r[2] for r in results_without]

    # 4. Compare text identity
    identical_count = sum(1 for tw, two in zip(texts_with, texts_without) if tw == two)
    diff_count = total_records - identical_count

    # 5. Thought count distribution
    # How many have 0 thoughts (when completion has no reasoning) vs 1 thought vs >1
    from collections import Counter
    thought_counts_hist = Counter(thoughts_with)

    # 6. Distribution percentiles
    pcts = [0, 25, 50, 75, 90, 95, 99, 100]
    vals_with = np.percentile(lens_with, pcts)
    vals_without = np.percentile(lens_without, pcts)

    print("\n" + "=" * 75)
    print("VERIFICATION 1: EXACT TEXT IDENTITY")
    print("=" * 75)
    print(f"Total Split Records Evaluated: {total_records:,}")
    print(f"Character-for-character Identical: {identical_count:,} ({identical_count/total_records*100:.2f}%)")
    print(f"Differences:                      {diff_count}")

    print("\n" + "=" * 75)
    print("VERIFICATION 2: THOUGHT COUNT IN RENDERED OUTPUT")
    print("=" * 75)
    for cnt in sorted(thought_counts_hist.keys()):
        num = thought_counts_hist[cnt]
        desc = "No thought (completion had no reasoning_content)" if cnt == 0 else ("Exactly 1 thought (target completion only)" if cnt == 1 else "More than 1 thought (MULTIPLE THOUGHTS)")
        print(f"  {cnt} thought blocks: {num:,} records ({num/total_records*100:.2f}%) -> {desc}")

    print("\n" + "=" * 75)
    print("VERIFICATION 3: TOKEN LENGTH DISTRIBUTION COMPARISON")
    print("=" * 75)
    print(f"{'Percentile':<15} | {'With Reasoning on Prompt':<25} | {'Without Reasoning on Prompt':<25}")
    print("-" * 75)
    print(f"{'Min (p0)':<15} | {vals_with[0]:>18,.0f} tokens | {vals_without[0]:>18,.0f} tokens")
    print(f"{'p25':<15} | {vals_with[1]:>18,.0f} tokens | {vals_without[1]:>18,.0f} tokens")
    print(f"{'Median (p50)':<15} | {vals_with[2]:>18,.0f} tokens | {vals_without[2]:>18,.0f} tokens")
    print(f"{'Mean':<15} | {np.mean(lens_with):>18,.1f} tokens | {np.mean(lens_without):>18,.1f} tokens")
    print(f"{'p75':<15} | {vals_with[3]:>18,.0f} tokens | {vals_without[3]:>18,.0f} tokens")
    print(f"{'p90':<15} | {vals_with[4]:>18,.0f} tokens | {vals_without[4]:>18,.0f} tokens")
    print(f"{'p95':<15} | {vals_with[5]:>18,.0f} tokens | {vals_without[5]:>18,.0f} tokens")
    print(f"{'p99':<15} | {vals_with[6]:>18,.0f} tokens | {vals_without[6]:>18,.0f} tokens")
    print(f"{'Max (p100)':<15} | {vals_with[7]:>18,.0f} tokens | {vals_without[7]:>18,.0f} tokens")
    print("=" * 75)


if __name__ == "__main__":
    main()
