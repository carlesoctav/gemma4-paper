#!/usr/bin/env python3
"""Convert Harbor agent traces / Pi sessions into a TRL-compatible multi-turn SFT dataset.

Handles compaction-aware multi-phase segmentation:
- main: initial conversation up to the first compaction cut point
- compaction: summarization task (system + conversation history + instructions -> summary)
- main_2: compacted context (system + <summary>...</summary> + kept messages -> continued conversation)
- compaction_2, main_3, etc.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
from typing import Any

from datasets import Dataset

# Pi Compaction prompts matching packages/coding-agent/src/core/compaction
SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. Your task is to read a conversation "
    "between a user and an AI assistant, then produce a structured summary following "
    "the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the "
    "conversation. ONLY output the structured summary."
)

INITIAL_SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- KEEP the same section format: Goal, Constraints & Preferences, Progress (Done / In Progress / Blocked), Key Decisions, Next Steps, Critical Context
- Keep each section concise. Preserve exact file paths, function names, and error messages."""

COMPACTION_SUMMARY_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"
TOOL_RESULT_MAX_CHARS = 2000


def truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    truncated = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[... {truncated} more characters truncated]"


def get_system_message_text(message: dict[str, Any]) -> str:
    parts = []
    content = message.get("content", "")
    if isinstance(content, str) and content:
        parts.append(content)
    sections = message.get("sections")
    if isinstance(sections, dict):
        for text in sections.values():
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def serialize_messages_for_summary(messages: list[dict[str, Any]]) -> str:
    """Serialize messages into readable text for the summarization prompt (matching Pi)."""
    parts = []
    for msg in messages:
        role = msg.get("role")
        if role == "user":
            content = msg.get("content", "")
            if content:
                parts.append(f"[User]: {content}")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            tc_strs = []
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                args_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in args.items()) if isinstance(args, dict) else str(args)
                tc_strs.append(f"{name}({args_str})")

            content = msg.get("content", "")
            # Strip thought tags if present for summary serialization
            if "<thought>" in content and "</thought>" in content:
                content = content.split("</thought>")[-1].strip()
            if content:
                parts.append(f"[Assistant]: {content}")
            if tc_strs:
                parts.append(f"[Assistant tool calls]: {'; '.join(tc_strs)}")
        elif role == "tool":
            content = msg.get("content", "")
            if content:
                parts.append(f"[Tool result]: {truncate_text(content, TOOL_RESULT_MAX_CHARS)}")
    return "\n\n".join(parts)


def convert_pi_message_to_chat_dict(event: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a single Pi session message event into a standardized chat dictionary."""
    ev_type = event.get("type")
    if ev_type != "message":
        return None

    msg = event.get("message", {})
    role = msg.get("role")

    if role == "system":
        return {"role": "system", "content": get_system_message_text(msg)}

    if role == "user":
        content = msg.get("content")
        if isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        return {"role": "user", "content": text}

    if role == "assistant":
        content = msg.get("content", [])
        text_blocks = []
        thinking_blocks = []
        tool_calls = []

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                b_type = block.get("type")
                if b_type == "text" and isinstance(block.get("text"), str):
                    text_blocks.append(block["text"])
                elif b_type == "thinking" and isinstance(block.get("thinking"), str):
                    thinking_blocks.append(block["thinking"])
                elif b_type == "toolCall":
                    tc_id = block.get("id", f"call_{len(tool_calls)}")
                    name = block.get("name", "")
                    arguments = block.get("arguments", {})
                    tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arguments,
                        },
                    })
        elif isinstance(content, str):
            text_blocks.append(content)

        text_content = "\n".join(text_blocks).strip()
        if thinking_blocks:
            thought_text = "\n".join(thinking_blocks).strip()
            combined_content = f"<thought>\n{thought_text}\n</thought>\n{text_content}".strip()
        else:
            combined_content = text_content

        res = {"role": "assistant", "content": combined_content}
        if tool_calls:
            res["tool_calls"] = tool_calls
        return res

    if role == "toolResult":
        content = msg.get("content", [])
        if isinstance(content, list):
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        elif isinstance(content, str):
            text = content
        else:
            text = ""
        return {
            "role": "tool",
            "tool_call_id": msg.get("toolCallId", ""),
            "name": msg.get("toolName", ""),
            "content": text,
        }

    return None


def format_tools_list(tools_added: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format toolsAdded into standard OpenAI / Hugging Face tool definitions."""
    formatted = []
    for t in tools_added:
        formatted.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            },
        })
    return formatted


def extract_active_path(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract root-to-leaf path following parentId pointers."""
    events_by_id = {}
    leaf_id = None
    headers = []

    for ev in events:
        if ev.get("type") == "session":
            headers.append(ev)
            continue
        eid = ev.get("id")
        if eid:
            events_by_id[eid] = ev
            leaf_id = eid

    if not leaf_id:
        return events

    branch = []
    visited = set()
    curr = leaf_id
    while curr and curr not in visited:
        visited.add(curr)
        ev = events_by_id.get(curr)
        if not ev:
            break
        branch.append(ev)
        curr = ev.get("parentId")

    branch.reverse()
    return headers + branch


def process_session_file(
    session_path: Path,
    trial_id: str,
    reward: float | None,
    f2p_rate: float | None = None,
    p2p_rate: float | None = None,
) -> list[dict[str, Any]]:
    """Parse a Pi session JSONL and split into compaction-aware SFT segments."""
    events = []
    with open(session_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    path = extract_active_path(events)

    # Find system message and tools from header
    initial_system_text = ""
    tools_list = []
    for ev in path:
        if ev.get("type") == "message" and ev.get("message", {}).get("role") == "system":
            msg = ev["message"]
            initial_system_text = get_system_message_text(msg)
            if "toolsAdded" in msg and isinstance(msg["toolsAdded"], list):
                tools_list = format_tools_list(msg["toolsAdded"])
            break

    # Locate all compactions
    compaction_indices = [i for i, ev in enumerate(path) if ev.get("type") == "compaction"]

    samples = []

    metrics_meta = {
        "trial_id": trial_id,
        "reward": reward,
        "f2p_rate": f2p_rate,
        "p2p_rate": p2p_rate,
    }

    if not compaction_indices:
        # Simple trajectory without compactions -> single "main" sample
        messages = []
        if initial_system_text:
            messages.append({"role": "system", "content": initial_system_text})

        for ev in path:
            msg_dict = convert_pi_message_to_chat_dict(ev)
            if msg_dict:
                if msg_dict["role"] == "system":
                    continue
                messages.append(msg_dict)

        # Ensure there is at least one assistant message
        if any(m["role"] == "assistant" for m in messages):
            samples.append({
                "messages": messages,
                "tools": tools_list,
                "type": "main",
                **metrics_meta,
            })
        return samples

    # We have one or more compactions!
    # Segment 0: main (from beginning up to compaction 0)
    cmp_0_idx = compaction_indices[0]
    cmp_0_ev = path[cmp_0_idx]

    main_0_messages = []
    if initial_system_text:
        main_0_messages.append({"role": "system", "content": initial_system_text})

    for ev in path[:cmp_0_idx]:
        msg_dict = convert_pi_message_to_chat_dict(ev)
        if msg_dict and msg_dict["role"] != "system":
            main_0_messages.append(msg_dict)

    if any(m["role"] == "assistant" for m in main_0_messages):
        samples.append({
            "messages": main_0_messages,
            "tools": tools_list,
            "type": "main",
            **metrics_meta,
        })

    # For each compaction k:
    # 1. Generate "compaction" (or "compaction_k") summarization task
    # 2. Generate "main_(k+1)" continuation task
    prev_summary = ""

    for k, cmp_idx in enumerate(compaction_indices):
        cmp_ev = path[cmp_idx]
        summary = cmp_ev.get("summary", "")
        first_kept_id = cmp_ev.get("firstKeptEntryId")
        comp_type_name = "compaction" if k == 0 else f"compaction_{k+1}"
        main_type_name = f"main_{k+2}"

        # Determine messages summarized by this compaction
        # For k=0: messages from start up to cut point (cmp_idx)
        # For k>0: messages from previous firstKeptEntryId up to cut point
        if k == 0:
            events_to_summarize = path[:cmp_idx]
        else:
            prev_cmp_ev = path[compaction_indices[k - 1]]
            prev_kept_id = prev_cmp_ev.get("firstKeptEntryId")
            start_i = 0
            for i, ev in enumerate(path[:cmp_idx]):
                if ev.get("id") == prev_kept_id:
                    start_i = i
                    break
            events_to_summarize = path[start_i:cmp_idx]

        summarized_chat_msgs = []
        for ev in events_to_summarize:
            m = convert_pi_message_to_chat_dict(ev)
            if m and m["role"] != "system":
                summarized_chat_msgs.append(m)

        serialized_convo = serialize_messages_for_summary(summarized_chat_msgs)

        if k == 0 or not prev_summary:
            user_prompt = f"# Conversation\n{serialized_convo}\n\n# Instructions\n{INITIAL_SUMMARIZATION_PROMPT}"
        else:
            user_prompt = (
                f"# Conversation\n{serialized_convo}\n\n"
                f"# Existing Summary\n{prev_summary}\n\n"
                f"# Instructions\n{UPDATE_SUMMARIZATION_PROMPT}"
            )

        # Compaction sample
        compaction_messages = [
            {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": summary},
        ]
        samples.append({
            "messages": compaction_messages,
            "tools": [],
            "type": comp_type_name,
            **metrics_meta,
        })

        # Next main segment (main_2, main_3, ...)
        next_cmp_idx = compaction_indices[k + 1] if k + 1 < len(compaction_indices) else len(path)

        kept_events = []
        found_kept = False
        for i in range(cmp_idx):
            ev = path[i]
            if ev.get("id") == first_kept_id:
                found_kept = True
            if found_kept:
                kept_events.append(ev)

        # Subsequent events between current compaction and next cut point
        subsequent_events = path[cmp_idx + 1:next_cmp_idx]

        main_k_messages = []
        sys_msg_obj = cmp_ev.get("systemMessage")
        sys_text = get_system_message_text(sys_msg_obj) if sys_msg_obj else initial_system_text
        if sys_text:
            main_k_messages.append({"role": "system", "content": sys_text})

        # Summary as user message
        summary_user_text = f"{COMPACTION_SUMMARY_PREFIX}{summary}{COMPACTION_SUMMARY_SUFFIX}"
        main_k_messages.append({"role": "user", "content": summary_user_text})

        # Kept messages
        for ev in kept_events + subsequent_events:
            m = convert_pi_message_to_chat_dict(ev)
            if m and m["role"] != "system":
                main_k_messages.append(m)

        # Determine tools for main_k
        if sys_msg_obj and "toolsAdded" in sys_msg_obj and isinstance(sys_msg_obj["toolsAdded"], list):
            main_k_tools = format_tools_list(sys_msg_obj["toolsAdded"])
        else:
            main_k_tools = tools_list

        if any(m["role"] == "assistant" for m in main_k_messages):
            samples.append({
                "messages": main_k_messages,
                "tools": main_k_tools,
                "type": main_type_name,
                **metrics_meta,
            })

        prev_summary = summary

    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TRL-compatible SFT dataset from Harbor job traces.")
    parser.add_argument(
        "--job-dir",
        type=Path,
        default=Path("jobs/mined-gemma31b-final-36"),
        help="Path to downloaded Harbor job directory.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("sft_dataset.jsonl"),
        help="Path to output JSONL dataset file.",
    )
    parser.add_argument(
        "--output-arrow-dir",
        type=Path,
        default=Path("sft_dataset"),
        help="Directory to save HuggingFace Dataset (Arrow format).",
    )
    parser.add_argument(
        "--min-reward",
        type=float,
        default=None,
        help="Minimum overall reward threshold (e.g. 1.0). If omitted and --min-f2p is omitted, defaults to 1.0.",
    )
    parser.add_argument(
        "--min-f2p",
        type=float,
        default=None,
        help="Minimum Fail-to-Pass (f2p_rate) threshold, e.g. 1.0. Takes precedence over --min-reward when provided.",
    )
    args = parser.parse_args()

    # Default to min_reward=1.0 if neither min_reward nor min_f2p is specified
    if args.min_reward is None and args.min_f2p is None:
        args.min_reward = 1.0

    # Load trial results and rewards from result.json if present
    results_path = args.job_dir / "result.json"
    reward_by_trial: dict[str, float] = {}
    if results_path.exists():
        with open(results_path, "r", encoding="utf-8") as f:
            job_result = json.load(f)
        eval_stats_dict = job_result.get("stats", {}).get("evals", {})
        if eval_stats_dict:
            eval_stats = next(iter(eval_stats_dict.values()))
            reward_stats = eval_stats.get("reward_stats", {}).get("reward", {})
            for r_str, trials in reward_stats.items():
                r_val = float(r_str)
                for t in trials:
                    reward_by_trial[t] = r_val

    # Find all session files
    session_paths = list(args.job_dir.glob("*/agent/pi/sessions/*.jsonl"))
    print(f"Found {len(session_paths)} session files in {args.job_dir}")

    all_samples = []
    type_counts: dict[str, int] = {}
    trial_counts = 0

    for s_path in sorted(session_paths):
        trial_id = s_path.parts[-5] if len(s_path.parts) >= 5 else s_path.parent.name
        reward = reward_by_trial.get(trial_id)
        f2p_rate = None
        p2p_rate = None

        # Look for verifier/reward-details.json
        trial_dir = s_path.parents[3]
        verifier_path = trial_dir / "verifier" / "reward-details.json"
        if verifier_path.exists():
            with open(verifier_path, "r", encoding="utf-8") as vf:
                v_data = json.load(vf)
            f2p_rate = v_data.get("f2p_rate")
            p2p_rate = v_data.get("p2p_rate")
            if "reward" in v_data:
                reward = float(v_data["reward"])

        # Filter criteria: check f2p if requested, otherwise check overall reward
        if args.min_f2p is not None:
            if f2p_rate is None or f2p_rate < args.min_f2p:
                continue
        elif args.min_reward is not None:
            if reward is None or reward < args.min_reward:
                continue

        trial_samples = process_session_file(
            s_path,
            trial_id,
            reward=reward,
            f2p_rate=f2p_rate,
            p2p_rate=p2p_rate,
        )
        if trial_samples:
            trial_counts += 1
            for s in trial_samples:
                t = s["type"]
                type_counts[t] = type_counts.get(t, 0) + 1
                all_samples.append(s)

    filter_desc = f"min_f2p={args.min_f2p}" if args.min_f2p is not None else f"min_reward={args.min_reward}"
    print(f"\nProcessed {trial_counts} eligible trials ({filter_desc})")
    print(f"Total SFT samples produced: {len(all_samples)}")
    print("Distribution of sample types:")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    # Write JSONL
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_jsonl, "w", encoding="utf-8") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    print(f"\nWrote JSONL dataset to {args.output_jsonl.resolve()}")

    # Save as HuggingFace Dataset
    hf_dataset = Dataset.from_list(all_samples)
    hf_dataset.save_to_disk(str(args.output_arrow_dir))
    print(f"Saved HuggingFace Arrow Dataset to {args.output_arrow_dir.resolve()}")


if __name__ == "__main__":
    main()
