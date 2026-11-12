#!/usr/bin/env python3
"""Visualize SFT training examples with color-coded tokens (trained vs. ignored).

Following the Unsloth inspection pattern:
- RED / GRAY: Ignored tokens (label = -100, prompt / user / system / tool observations)
- BOLD GREEN: Trained tokens (assistant reasoning, tool calls, responses)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

COLOR_IGNORED = "\033[90m"       # Gray / dim for masked tokens
COLOR_TRAINED = "\033[1;32m"     # Bold green for active training tokens
COLOR_HEADER = "\033[1;36m"      # Cyan for headers
COLOR_RESET = "\033[0m"

DEFAULT_TOKENIZER_PATH = (
    "/home/carlesoctav/.cache/huggingface/hub/models--google--gemma-4-31b-it-qat-w4a16-ct"
    "/snapshots/52f3f65bc7a02d555763bc923bd1d9094898219d"
)


def compute_turn_labels(
    tokenizer: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[list[int], list[int]]:
    """Compute input_ids and labels for a multi-turn conversation.

    Assistant turns are trained (label = token_id).
    System, User, Tool observation, and Turn header tokens are ignored (label = -100).
    """
    if tools:
        full_text = tokenizer.apply_chat_template(messages, tools=tools, tokenize=False)
    else:
        full_text = tokenizer.apply_chat_template(messages, tokenize=False)

    input_ids = tokenizer.encode(full_text, add_special_tokens=False)
    labels = [-100] * len(input_ids)

    # In Gemma 4 chat template:
    # Model turn begins with '<|turn>model\n'
    # Model turn ends with '<turn|>\n' or '<turn|>'
    # Inside model turn:
    # Tool call: '<|tool_call>call:...<tool_call|>' (model output -> trained)
    # Tool response: '<|tool_response>response:...<tool_response|>' (environment output -> ignored)
    full_tokens = [tokenizer.decode([tid]) for tid in input_ids]

    in_model_turn = False
    in_tool_response = False

    # Token-level state machine using token string representation
    for i, token_str in enumerate(full_tokens):
        if "<|turn>model" in token_str or (token_str == "<|turn>" and i + 1 < len(full_tokens) and "model" in full_tokens[i + 1]):
            in_model_turn = True
            labels[i] = -100
            continue

        if "<|turn>user" in token_str or "<|turn>system" in token_str:
            in_model_turn = False
            labels[i] = -100
            continue

        if "<|tool_response>" in token_str:
            in_tool_response = True
            labels[i] = -100
            continue

        if "<tool_response|>" in token_str:
            in_tool_response = False
            labels[i] = -100
            continue

        if "<turn|>" in token_str:
            if in_model_turn and not in_tool_response:
                # The model generates the end-of-turn token!
                labels[i] = input_ids[i]
            else:
                labels[i] = -100
            in_model_turn = False
            continue

        if in_model_turn and not in_tool_response:
            labels[i] = input_ids[i]
        else:
            labels[i] = -100

    return input_ids, labels


def print_colored_example(
    sample: dict[str, Any],
    input_ids: list[int],
    labels: list[int],
    tokenizer: Any,
    max_tokens: int | None = None,
) -> None:
    """Print the color-coded token sequence and statistics."""
    task = sample.get("task")
    trial = sample.get("trial") or sample.get("trial_id", "unknown")
    reward = sample.get("reward")
    f2p_rate = sample.get("f2p_rate")
    p2p_rate = sample.get("p2p_rate")
    tools = sample.get("tools", [])
    tool_names = [t.get("function", {}).get("name", "") for t in tools] if tools else []

    total_tokens = len(input_ids)
    trained_count = sum(1 for lab in labels if lab != -100)
    ignored_count = total_tokens - trained_count
    trained_pct = (trained_count / total_tokens * 100) if total_tokens else 0.0

    meta_parts = []
    if task:
        meta_parts.append(f"Task: {task}")
    if trial:
        meta_parts.append(f"Trial: {trial}")
    if reward is not None:
        meta_parts.append(f"Reward: {reward}")
    if "type" in sample:
        meta_parts.append(f"Type: {sample['type']}")
    if f2p_rate is not None:
        meta_parts.append(f"F2P: {f2p_rate}")
    if p2p_rate is not None:
        meta_parts.append(f"P2P: {p2p_rate}")

    print(f"\n{COLOR_HEADER}======================================================================{COLOR_RESET}")
    print(f"{COLOR_HEADER}Example Sample | {' | '.join(meta_parts)}{COLOR_RESET}")
    print(f"Tools ({len(tool_names)}): {tool_names if tool_names else '(none - bash CLI interaction)'}")
    print(f"Total tokens: {total_tokens} | Trained tokens: {trained_count} ({trained_pct:.1f}%) | Ignored tokens: {ignored_count} ({100-trained_pct:.1f}%)")
    print(f"{COLOR_HEADER}----------------------------------------------------------------------{COLOR_RESET}")
    print(
        f"{COLOR_RESET}[LEGEND] "
        f"{COLOR_IGNORED}■ Masked / Ignored (-100: System, User, Tool Outputs, Turn Headers){COLOR_RESET} | "
        f"{COLOR_TRAINED}■ Trained (Active Gradients: Assistant Thoughts, Tool Calls, Responses){COLOR_RESET}\n"
    )

    display_ids = input_ids[:max_tokens] if max_tokens else input_ids
    display_labels = labels[:max_tokens] if max_tokens else labels

    curr_color = None
    buf = []

    for tid, lab in zip(display_ids, display_labels):
        color = COLOR_TRAINED if lab != -100 else COLOR_IGNORED
        token_str = tokenizer.decode([tid])

        if color != curr_color:
            if curr_color is not None:
                buf.append(COLOR_RESET)
            buf.append(color)
            curr_color = color

        buf.append(token_str)

    if curr_color is not None:
        buf.append(COLOR_RESET)

    print("".join(buf))

    if max_tokens and total_tokens > max_tokens:
        print(f"\n{COLOR_HEADER}[... Truncated for display: showing {max_tokens} of {total_tokens} tokens ...]{COLOR_RESET}")

    print(f"{COLOR_HEADER}======================================================================{COLOR_RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect color-coded SFT tokens (Unsloth style).")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("sft_dataset.jsonl"),
        help="Path to SFT JSONL dataset.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_TOKENIZER_PATH,
        help="Model name or local path for tokenizer.",
    )
    parser.add_argument(
        "--num-examples",
        type=int,
        default=2,
        help="Number of examples to display.",
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="Filter examples by type (e.g. main, compaction, main_2, compaction_2, main_3).",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Specific sample index to inspect.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1200,
        help="Max tokens to print per example (default: 1200). Use 0 for full sequence.",
    )
    args = parser.parse_args()

    # Load dataset
    samples = []
    with open(args.dataset, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    if not samples:
        print("Dataset is empty!")
        return

    print(f"Loaded {len(samples)} samples from {args.dataset}")

    # Load tokenizer
    print(f"Loading tokenizer from {args.model} ...")
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    max_toks = None if args.max_tokens == 0 else args.max_tokens

    # Select samples to display
    selected = []
    if args.index is not None:
        if 0 <= args.index < len(samples):
            selected.append(samples[args.index])
        else:
            print(f"Index {args.index} out of range (0-{len(samples)-1})")
            return
    elif args.type is not None:
        filtered = [s for s in samples if s.get("type") == args.type]
        selected = filtered[:args.num_examples]
    else:
        # Default: pick 1 main and 1 compaction/main_2 if 'type' exists, else first num_examples
        compaction_samples = [s for s in samples if "compaction" in s.get("type", "") or "main_2" in s.get("type", "")]
        main_samples = [s for s in samples if s.get("type") == "main"]

        if main_samples:
            selected.append(main_samples[0])
        if compaction_samples:
            selected.append(compaction_samples[0])
        elif len(main_samples) > 1:
            selected.append(main_samples[1])

        if not selected:
            selected = samples[:args.num_examples]

    for sample in selected:
        input_ids, labels = compute_turn_labels(tokenizer, sample["messages"], tools=sample.get("tools"))
        print_colored_example(sample, input_ids, labels, tokenizer, max_tokens=max_toks)


if __name__ == "__main__":
    main()
