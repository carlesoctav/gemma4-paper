#!/usr/bin/env python3
"""Build termgrade-p95-split_sft.jsonl in conversational prompt-completion format with turn prefix expansion."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
from transformers import AutoTokenizer

PARQUET_PATH = Path("/home/carlesoctav/.cache/huggingface/hub/datasets--ai-and--termgrade-trajectories/snapshots/e0297725c7dc63ac4efa228c47f228f94b64db3e/data/messages/gemma_think.parquet")
TRAIN_TASKS_PATH = Path("data/train_tasks.txt")
TEMPLATE_PATH = Path("chat_template.jinja")
OUTPUT_PATH = Path("data/termgrade-p95-split_sft.jsonl")


def main() -> None:
    print(f"Loading tokenizer google/gemma-4-E4B-it ...")
    tokenizer = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        chat_template = f.read()

    print(f"Loading train tasks from {TRAIN_TASKS_PATH} ...")
    with open(TRAIN_TASKS_PATH, "r", encoding="utf-8") as f:
        train_tasks = set(line.strip() for line in f if line.strip())
    print(f"Train tasks pool size: {len(train_tasks)}")

    print(f"Loading parquet from {PARQUET_PATH} ...")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"Total rows in parquet: {len(df)}")

    # Filter by model == gemma_think, reward == 1.0, and task in train_tasks
    df_filtered = df[
        (df["model"] == "gemma_think")
        & (df["reward"] == 1.0)
        & (df["task"].isin(train_tasks))
    ].copy()
    print(f"Filtered (model=gemma_think, reward=1.0, in train pool): {len(df_filtered)} trials across {df_filtered['task'].nunique()} tasks")

    # Step 1: Pre-calculate trajectory token lengths under default template (without preserve thinking)
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

        rendered = tokenizer.apply_chat_template(msgs, chat_template=chat_template, tokenize=False)
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

    # Step 2: Split each trajectory into growing prompt-completion turns
    print("Splitting trajectories into growing prompt-completion rows...")
    split_records = []
    
    for row, msgs, _ in p95_trials:
        task_id = str(row["task"])
        trial_id = str(row["trial"])
        reward = float(row["reward"])

        # Find all assistant turn indices
        assistant_indices = [i for i, m in enumerate(msgs) if m.get("role") == "assistant"]
        k_total = len(assistant_indices)

        for turn_idx, a_idx in enumerate(assistant_indices, start=1):
            # Prompt is everything before this assistant turn
            raw_prompt_msgs = msgs[:a_idx]
            
            # Sanitize prompt: prior assistant messages must only contain content, NO past reasoning
            sanitized_prompt = []
            for m in raw_prompt_msgs:
                role = m.get("role", "user")
                content = m.get("content") or ""
                if role == "assistant":
                    sanitized_prompt.append({"role": "assistant", "content": content})
                else:
                    sanitized_prompt.append({"role": role, "content": content})

            # Target assistant turn
            target_assistant = msgs[a_idx]
            target_content = target_assistant.get("content") or ""
            target_reasoning = target_assistant.get("reasoning_content") or ""

            target_completion_entry = {"role": "assistant", "content": target_content}
            if target_reasoning:
                target_completion_entry["reasoning_content"] = target_reasoning

            completion_msgs = [target_completion_entry]

            split_records.append({
                "prompt": sanitized_prompt,
                "completion": completion_msgs,
                "task": task_id,
                "trial": trial_id,
                "turn": turn_idx,
                "turns_total": k_total,
                "reward": reward,
            })

    print(f"Total split rows created: {len(split_records)}")

    # Write out JSONL
    print(f"Writing dataset to {OUTPUT_PATH} ...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for rec in split_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Successfully created {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / (1024 * 1024):.2f} MB)")


if __name__ == "__main__":
    main()
