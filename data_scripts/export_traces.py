import json
import os
import sys

def format_trial_to_markdown(trial_dir, output_file, failure_summary):
    pi_file = os.path.join(trial_dir, "agent", "pi.txt")
    res_file = os.path.join(trial_dir, "result.json")
    traj_file = os.path.join(trial_dir, "agent", "trajectory.json")
    exc_file = os.path.join(trial_dir, "exception.txt")

    with open(res_file) as f:
        res = json.load(f)

    task_name = res.get("task_name", "")
    trial_name = res.get("trial_name", "")
    exc_info = res.get("exception_info") or {}
    exc_type = exc_info.get("exception_type", "None")
    exc_msg = exc_info.get("exception_message", "")
    
    if os.path.exists(exc_file) and exc_type == "None":
        with open(exc_file) as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            if lines:
                exc_type = lines[-1]

    reward = res.get("verifier_result", {}).get("rewards", {}) if res.get("verifier_result") else None
    model_name = res.get("config", {}).get("agent", {}).get("model_name", "simple-lora-1e4")

    # Metrics
    agent_res = res.get("agent_result") or {}
    n_in = agent_res.get("n_input_tokens", 0)
    n_out = agent_res.get("n_output_tokens", 0)

    events = []
    if os.path.exists(pi_file):
        with open(pi_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        pass

    steps_count = 0
    if os.path.exists(traj_file):
        try:
            with open(traj_file) as f:
                steps_count = len(json.load(f).get("steps", []))
        except Exception:
            pass

    md = []
    md.append(f"# Trial Trace: `{trial_name}`\n")
    md.append("## Overview\n")
    md.append(f"- **Task**: `{task_name}`")
    md.append(f"- **Model**: `{model_name}`")
    md.append(f"- **Result**: `{exc_type}` {f'({exc_msg})' if exc_msg else ''}")
    md.append(f"- **Reward**: `{reward}`")
    md.append(f"- **Total Steps**: {steps_count}")
    md.append(f"- **Total Tokens**: {n_in:,} input tokens + {n_out:,} output tokens")
    md.append(f"- **Timeout Diagnosis**: {failure_summary}\n")
    md.append("---\n")
    md.append("## Full Interaction Trace\n")

    turn_idx = 0
    for ev in events:
        etype = ev.get("type")
        if etype == "turn_start":
            turn_idx += 1
            md.append(f"\n### Turn {turn_idx}\n")
        elif etype == "message_end":
            msg = ev.get("message", {})
            role = msg.get("role", "assistant")
            for c in msg.get("content", []):
                ctype = c.get("type")
                if ctype == "thinking":
                    th = c.get("thinking", "").strip()
                    if th:
                        md.append(f"<details><summary><b>Thinking Process (click to expand)</b></summary>\n\n```text\n{th}\n```\n</details>\n")
                elif ctype == "text":
                    txt = c.get("text", "").strip()
                    if txt:
                        label = "User Prompt" if role == "user" else "Agent Message"
                        md.append(f"**{label}**:\n\n{txt}\n")
                elif ctype == "toolCall":
                    tname = c.get("name")
                    targs = c.get("arguments", {})
                    if isinstance(targs, str):
                        try:
                            targs = json.loads(targs)
                        except Exception:
                            pass
                    targs_str = json.dumps(targs, indent=2) if isinstance(targs, (dict, list)) else str(targs)
                    md.append(f"**Tool Call: `{tname}`**\n```json\n{targs_str}\n```\n")
        elif etype == "tool_execution_end":
            tname = ev.get("toolName")
            is_err = ev.get("isError")
            res_content = ev.get("result", {}).get("content", [])
            out_txt = "\n".join([item.get("text", "") for item in res_content]).strip()
            status = "FAILED / ERROR" if is_err else "SUCCESS"
            if len(out_txt) > 3000:
                out_txt = out_txt[:1500] + f"\n\n... [truncated {len(out_txt)-3000} characters] ...\n\n" + out_txt[-1500:]
            md.append(f"**Tool Result (`{tname}`) [{status}]**:\n```\n{out_txt}\n```\n")
        elif etype == "compaction_end":
            res_comp = ev.get("result", {})
            summary = res_comp.get("summary", "")
            tokens_before = res_comp.get("tokensBefore", 0)
            tokens_after = res_comp.get("estimatedTokensAfter", 0)
            indent_summary = "\n> ".join(summary.split("\n"))
            md.append(f"\n> **[Pi Context Compaction Triggered]**\n> Reduced tokens from {tokens_before:,} -> ~{tokens_after:,}\n>\n> {indent_summary}\n\n")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w") as f:
        f.write("\n".join(md))
    print(f"Exported trace to {output_file} ({len(md)} lines)")


if __name__ == "__main__":
    job_dir = "harbor/jobs/fix-simple-lora-1e4-eval_tasks-gemma4_gh_pr"
    targets = [
        (
            "Textualize__rich-2725",
            "post/Textualize__rich-2725.md",
            "Introduced a Python SyntaxError (`unmatched ')'`) into `rich/table.py`. Repeatedly failed to edit the file due to exact whitespace/newline mismatch, re-read the 1,000+ line file repeatedly, hit context compaction twice, and exceeded 600s."
        ),
        (
            "Textualize__rich-3296",
            "post/Textualize__rich-3296.md",
            "Tool call schema validation failure (`Validation failed for tool 'edit': - path: missing`), followed by reading large files repeatedly, leading to 470k input tokens and agent execution timeout."
        ),
        (
            "Textualize__rich-3471",
            "post/Textualize__rich-3471.md",
            "Suffered 67 tool execution errors. Generated malformed JSON keys with escaped quotes (`'\\\"newText\\\"'`), repeatedly failed oldText searches in `rich/text.py`, and spiraled into 34 steps before timing out."
        ),
        (
            "psf__requests-6644",
            "post/psf__requests-6644.md",
            "Combination of tool schema validation errors (`path: missing`), unable to find exact text in `requests/models.py`, repetitive failing edits, context compaction, and eventual 600s timeout."
        ),
        (
            "tiangolo__fastapi-14482",
            "post/tiangolo__fastapi-14482.md",
            "Extreme 56-step loop consuming 1.32M input tokens. Generated raw Python code inside JSON keys (`'arbitrary_types_allowed=...': '...'`), emitted special tokenizer tokens (`<|\"|>`), triggered 3 compactions, and looped endlessly on failed edits."
        ),
        (
            "tiangolo__fastapi-14605",
            "post/tiangolo__fastapi-14605.md",
            "Persistent edit failures on `fastapi/routing.py`, repeated full-file re-reads, context compaction at ~40k tokens, and timeout."
        ),
    ]

    for prefix, out_path, diag in targets:
        found = False
        for d in sorted(os.listdir(job_dir)):
            if d.startswith(prefix):
                trial_path = os.path.join(job_dir, d)
                format_trial_to_markdown(trial_path, out_path, diag)
                found = True
                break
        if not found:
            print(f"Warning: prefix {prefix} not found in {job_dir}")
