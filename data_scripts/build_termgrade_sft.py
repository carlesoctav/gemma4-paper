#!/usr/bin/env python3
"""Build TRL-compatible SFT dataset from ai-and/termgrade-trajectories (gemma_think, reward == 1, max_tokens <= 32768)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from datasets import Dataset
from transformers import AutoTokenizer

DEFAULT_MODEL = "google/gemma-4-31B-it-qat-w4a16-ct"
DEFAULT_PARQUET = "hf://datasets/ai-and/termgrade-trajectories/data/messages/gemma_think.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TermGrade Gemma Think SFT dataset.")
    parser.add_argument(
        "--parquet-url",
        type=str,
        default=DEFAULT_PARQUET,
        help="Path or HuggingFace URL to gemma_think.parquet.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help="Model tokenizer to compute exact sequence length.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=32768,
        help="Maximum total token count per SFT sample (default: 32768).",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("termgrade_gemma_think_sft_32k.jsonl"),
        help="Output JSONL dataset path.",
    )
    parser.add_argument(
        "--output-arrow-dir",
        type=Path,
        default=Path("termgrade_gemma_think_sft_32k"),
        help="Output directory for HuggingFace Dataset (Arrow).",
    )
    args = parser.parse_args()

    print(f"Loading tokenizer from {args.model} ...")
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    print(f"Loading parquet from {args.parquet_url} ...")
    df = pd.read_parquet(args.parquet_url)
    print(f"Total rows in dataset: {len(df)}")

    # Filter by model == gemma_think and reward == 1.0
    df_filtered = df[(df["model"] == "gemma_think") & (df["reward"] == 1.0)].copy()
    print(f"Filtered (model=gemma_think, reward=1.0): {len(df_filtered)} trials across {df_filtered['task'].nunique()} tasks")

    sft_records: list[dict[str, Any]] = []
    skipped_no_assistant = 0
    skipped_over_token_limit = 0

    print("Processing trajectories and tokenizing sequence lengths...")
    for idx, (_, row) in enumerate(df_filtered.iterrows()):
        raw_msgs = row["messages"]
        if raw_msgs is None:
            continue

        # Clean trailing non-assistant turns so trajectory terminates on successful model solution
        msgs = [dict(m) for m in raw_msgs]
        while msgs and msgs[-1].get("role") != "assistant":
            msgs.pop()

        if not any(m.get("role") == "assistant" for m in msgs):
            skipped_no_assistant += 1
            continue

        # Format sequence for token counting
        full_text = ""
        formatted_messages = []
        for m in msgs:
            role = m.get("role", "user")
            content = m.get("content") or ""
            reasoning = m.get("reasoning_content") or ""

            msg_entry: dict[str, Any] = {"role": role, "content": content}
            if role == "assistant":
                if reasoning:
                    msg_entry["reasoning_content"] = reasoning
                    full_text += f"<|turn>{role}\n<|channel>thought\n{reasoning}\n<channel|>\n{content}<turn|>\n"
                else:
                    full_text += f"<|turn>{role}\n{content}<turn|>\n"
            else:
                full_text += f"<|turn>{role}\n{content}<turn|>\n"

            formatted_messages.append(msg_entry)

        seq_tokens = len(tokenizer.encode(full_text, add_special_tokens=False))
        if seq_tokens > args.max_tokens:
            skipped_over_token_limit += 1
            continue

        sft_records.append({
            "messages": formatted_messages,
            "task": str(row["task"]),
            "trial": str(row["trial"]),
            "reward": float(row["reward"]),
            "num_tokens": seq_tokens,
            "num_messages": len(formatted_messages),
            "turns_total": float(row.get("turns_total", len(formatted_messages))),
            "duration_s": float(row.get("duration_s", 0.0)),
        })

        if (idx + 1) % 500 == 0 or (idx + 1) == len(df_filtered):
            print(f"  Processed {idx + 1}/{len(df_filtered)} trials (kept {len(sft_records)} under {args.max_tokens} tokens)...")

    print("\n" + "=" * 70)
    print("SFT DATASET SUMMARY")
    print("=" * 70)
    print(f"Total passing trials examined:    {len(df_filtered)}")
    print(f"Kept (actual tokens <= {args.max_tokens}): {len(sft_records)} ({len(sft_records)/len(df_filtered)*100:.1f}%)")
    print(f"Excluded (tokens > {args.max_tokens}):     {skipped_over_token_limit}")
    print(f"Unique tasks represented:         {len(set(r['task'] for r in sft_records))}")

    # Write JSONL
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_jsonl, "w", encoding="utf-8") as f:
        for r in sft_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nWrote JSONL dataset to {args.output_jsonl.resolve()}")

    # Save Arrow Dataset
    hf_dataset = Dataset.from_list(sft_records)
    hf_dataset.save_to_disk(str(args.output_arrow_dir))
    print(f"Saved HuggingFace Arrow Dataset to {args.output_arrow_dir.resolve()}")


if __name__ == "__main__":
    main()
