#!/usr/bin/env python3
"""Build termgrade-p95-split-spt-preserve-thinking.jsonl with reasoning_content retained on prompt turns."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
from datasets import Dataset
from transformers import AutoTokenizer

PARQUET_PATH = Path("/home/carlesoctav/.cache/huggingface/hub/datasets--ai-and--termgrade-trajectories/snapshots/e0297725c7dc63ac4efa228c47f228f94b64db3e/data/messages/gemma_think.parquet")
TRAIN_TASKS_PATH = Path("data/train_tasks.txt")
TEMPLATE_PATH = Path("chat_template.jinja")
OUTPUT_JSONL = Path("data/termgrade-p95-split-spt-preserve-thinking.jsonl")
HF_REPO_ID = "carlesoctav/termgrade-p95-split-spt-preserve-thinking"


def main() -> None:
    print("Loading tokenizer google/gemma-4-E4B-it ...")
    tokenizer = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        chat_template = f.read()
    tokenizer.chat_template = chat_template

    print(f"Loading train tasks from {TRAIN_TASKS_PATH} ...")
    with open(TRAIN_TASKS_PATH, "r", encoding="utf-8") as f:
        train_tasks = set(line.strip() for line in f if line.strip())
    print(f"Train tasks pool size: {len(train_tasks)}")

    print(f"Loading parquet from {PARQUET_PATH} ...")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"Total rows in parquet: {len(df)}")

    # Filter: model == gemma_think, reward == 1.0, and task in train_tasks
    df_filtered = df[
        (df["model"] == "gemma_think")
        & (df["reward"] == 1.0)
        & (df["task"].isin(train_tasks))
    ].copy()
    print(f"Filtered (model=gemma_think, reward=1.0, in train pool): {len(df_filtered)} trials across {df_filtered['task'].nunique()} tasks")

    # Step 1: Pre-calculate full trajectory token lengths under default template
    print("Pre-calculating full trajectory token lengths to determine exact p95 threshold...")
    traj_lengths = []
    valid_trials = []

    for _, row in df_filtered.iterrows():
        raw_msgs = row["messages"]
        if raw_msgs is None:
            continue
        msgs = [dict(m) for m in raw_msgs]
        while msgs and msgs[-1].get("role") != "assistant":
            msgs.pop()
        if not any(m.get("role") == "assistant" for m in msgs):
            continue

        rendered = tokenizer.apply_chat_template(msgs, tokenize=False)
        tok_len = len(tokenizer.encode(rendered, add_special_tokens=False))
        traj_lengths.append(tok_len)
        valid_trials.append((row, msgs, tok_len))

    traj_lengths = np.array(traj_lengths)
    p95_threshold = float(np.percentile(traj_lengths, 95))
    print(f"Total valid trials: {len(valid_trials)}")
    print(f"p95 Trajectory Token Threshold: {p95_threshold:.1f} tokens")

    # Filter trials <= p95
    p95_trials = [t for t in valid_trials if t[2] <= p95_threshold]
    print(f"Trials retained under p95: {len(p95_trials)} / {len(valid_trials)} ({len(p95_trials)/len(valid_trials)*100:.2f}%)")

    # Step 2: Split each trajectory into growing prompt-completion turns, preserving reasoning_content in prompt
    print("Splitting trajectories into growing prompt-completion rows (preserving reasoning_content on prompt)...")
    split_records = []

    for row, msgs, _ in p95_trials:
        task_id = str(row["task"])
        trial_id = str(row["trial"])
        reward = float(row["reward"])

        # Assistant turn indices
        assistant_indices = [i for i, m in enumerate(msgs) if m.get("role") == "assistant"]
        k_total = len(assistant_indices)

        for turn_idx, a_idx in enumerate(assistant_indices, start=1):
            raw_prompt_msgs = msgs[:a_idx]

            # Preserve reasoning_content on assistant messages in prompt as well
            prompt_msgs = []
            for m in raw_prompt_msgs:
                role = m.get("role", "user")
                content = m.get("content") or ""
                entry = {"role": role, "content": content}
                if role == "assistant" and m.get("reasoning_content"):
                    entry["reasoning_content"] = m["reasoning_content"]
                prompt_msgs.append(entry)

            # Target completion
            target_assistant = msgs[a_idx]
            target_content = target_assistant.get("content") or ""
            target_reasoning = target_assistant.get("reasoning_content") or ""

            target_completion_entry = {"role": "assistant", "content": target_content}
            if target_reasoning:
                target_completion_entry["reasoning_content"] = target_reasoning

            completion_msgs = [target_completion_entry]

            split_records.append({
                "prompt": prompt_msgs,
                "completion": completion_msgs,
                "task": task_id,
                "trial": trial_id,
                "turn": turn_idx,
                "turns_total": k_total,
                "reward": reward,
            })

    print(f"Total split rows created: {len(split_records)}")

    # Write JSONL
    print(f"Writing dataset to {OUTPUT_JSONL} ...")
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for rec in split_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Successfully saved {OUTPUT_JSONL} ({OUTPUT_JSONL.stat().st_size / (1024 * 1024):.2f} MB)")

    # Step 3: Distribution Verification using tokenizer.apply_chat_template(prompt + completion)
    print("\nCalculating token distribution of apply_chat_template(prompt + completion) on split records...")
    lengths = []
    # Sample or evaluate full distribution
    for rec in split_records:
        rendered = tokenizer.apply_chat_template(rec["prompt"] + rec["completion"], tokenize=False)
        tok_len = len(tokenizer.encode(rendered, add_special_tokens=False))
        lengths.append(tok_len)

    lengths = np.array(lengths)
    percentiles = [0, 25, 50, 75, 90, 95, 99, 100]
    pct_values = np.percentile(lengths, percentiles)

    print("\n" + "=" * 60)
    print("TOKEN LENGTH DISTRIBUTION (apply_chat_template prompt + completion):")
    print("=" * 60)
    print(f"Count:       {len(lengths):,}")
    print(f"Min:         {pct_values[0]:,.0f} tokens")
    print(f"p25:         {pct_values[1]:,.0f} tokens")
    print(f"Median (p50):{pct_values[2]:,.0f} tokens")
    print(f"Mean:        {np.mean(lengths):,.1f} tokens")
    print(f"p75:         {pct_values[3]:,.0f} tokens")
    print(f"p90:         {pct_values[4]:,.0f} tokens")
    print(f"p95:         {pct_values[5]:,.0f} tokens")
    print(f"p99:         {pct_values[6]:,.0f} tokens")
    print(f"Max:         {pct_values[7]:,.0f} tokens")
    print("=" * 60)

    # Step 4: Push to Hugging Face Hub
    print(f"\nPushing dataset to Hugging Face Hub: {HF_REPO_ID} ...")
    ds = Dataset.from_list(split_records)
    ds.push_to_hub(HF_REPO_ID, private=False)
    print(f"Successfully pushed to https://huggingface.co/datasets/{HF_REPO_ID}")


if __name__ == "__main__":
    main()
