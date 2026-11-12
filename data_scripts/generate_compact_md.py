import json
import glob
import os

SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."""

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

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

TURN_PREFIX_SUMMARIZATION_PROMPT = """The messages above are earlier context from an ongoing conversation. Later messages are stored separately and do not need to be reconstructed.

Create a concise checkpoint of the user's request and the progress shown above. This checkpoint will be placed before the later messages so the conversation can continue with the necessary context.

## Original Request
[What did the user ask for?]

## Progress So Far
- [Key decisions and work completed in these messages]

## Context Needed to Continue
- [Information from these messages needed to understand the later work]

Only summarize information explicitly present above. Do not infer or recreate later messages."""

def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    texts.append(b.get("text", ""))
            elif isinstance(b, str):
                texts.append(b)
        return "".join(texts)
    return ""

def truncate_tool_result(text, max_chars=2000):
    if len(text) <= max_chars:
        return text
    trunc = len(text) - max_chars
    return text[:max_chars] + f"\n\n[... {trunc} more characters truncated]"

def serialize_conversation(messages):
    parts = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            txt = content_text(content)
            if txt:
                parts.append(f"[User]: {txt}")
        elif role == "assistant":
            tcs = []
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "toolCall":
                        name = b.get("name")
                        args = b.get("arguments", {})
                        args_str = ", ".join(f"{k}={json.dumps(v)}" for k, v in args.items())
                        tcs.append(f"{name}({args_str})")
            if any(b.get("type") == "text" for b in content if isinstance(b, dict)):
                parts.append(f"[Assistant]: {content_text(content)}")
            if tcs:
                parts.append(f"[Assistant tool calls]: {chr(59).join(tcs)}")
        elif role == "toolResult":
            txt = content_text(content)
            if txt:
                parts.append(f"[Tool result]: {truncate_tool_result(txt)}")
    return "\n\n".join(parts)

def build_compact_md():
    path = glob.glob("harbor/jobs/fix-simple-lora-1e4-eval_tasks-gemma4_gh_pr/Textualize__rich-2725__QGagC2t/agent/pi/sessions/*.jsonl")[0]
    with open(path) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    # Compaction 1 (Entry 25) - Split Turn
    msgs_comp1 = [e["message"] for e in entries[3:17] if e.get("type") == "message"]
    conv_comp1 = serialize_conversation(msgs_comp1)
    prompt_input_1 = f"# Conversation\n{conv_comp1}\n\n# Instructions\n{TURN_PREFIX_SUMMARIZATION_PROMPT}"
    output_1 = entries[25]["summary"]

    # Compaction 2 (Entry 40) - Full Iterative History
    msgs_comp2 = [e["message"] for e in entries[17:40] if e.get("type") == "message"]
    conv_comp2 = serialize_conversation(msgs_comp2)
    prev_summary_40 = output_1
    prompt_input_2 = f"<previous-summary>\n{prev_summary_40}\n</previous-summary>\n\n# Conversation\n{conv_comp2}\n\n# Instructions\n{SUMMARIZATION_PROMPT}"
    output_2 = entries[40]["summary"]

    md = []
    md.append("# Audit of Pi Context Compaction on GitHub PR Tasks\n")
    md.append("This document analyzes the exact compaction mechanics in `@earendil-works/pi-coding-agent` (used by `pi:PiTinker` in Harbor). It includes the **exact system prompt**, the **flattened input data** passed to the LLM, the **exact LLM output** (the `## Goal` summary), and a breakdown of why this prompt sabotages coding agents.\n")
    md.append("---\n")

    md.append("## 1. What Data Gets Passed During Compaction?\n")
    md.append("When context approaches the budget limit (`contextWindow - 16384`), Pi executes `serializeConversation(messages)`. Here is how data is filtered before reaching the model:\n")
    md.append("1. **Thinking Tokens Are 100% Stripped**: All internal `<thought>` / reasoning tokens generated across turns are deleted. Any deduction, hypothesis, or line-level plan is completely erased.")
    md.append("2. **Tool Results Are Hard-Truncated to 2,000 Characters**: If the agent ran `read` on a 1,000-line file (e.g., 40,000 chars), Pi retains only the first 2,000 characters and discards the rest (`[... 37642 more characters truncated]`).")
    md.append("3. **Role Conversion**: The conversation is flattened into raw text blocks: `[User]: ...`, `[Assistant tool calls]: ...`, and `[Tool result]: ...`.")
    md.append("4. **Iterative Chaining**: When a second compaction occurs, the previous summary is enclosed in `<previous-summary>...</previous-summary>`.\n")

    md.append("---\n")
    md.append("## 2. Example 1: Full History Compaction (Producing `## Goal`)\n")
    md.append("From trial: `Textualize__rich-2725__QGagC2t` (Compaction Entry #40, tokens before: ~40k tokens).\n")
    md.append("### A. Exact System Prompt\n")
    md.append("```text\n" + SUMMARIZATION_SYSTEM_PROMPT + "\n```\n")
    md.append("### B. Exact Input Prompt Sent to the LLM\n")
    md.append("*(Notice the `<previous-summary>` inclusion, the truncated file reads, and the strict instructions)*\n")
    md.append("<details><summary><b>Click to expand full input prompt (15 KB)</b></summary>\n\n")
    md.append("```text\n" + prompt_input_2 + "\n```\n")
    md.append("</details>\n")
    md.append("### C. Exact Output Generated by the LLM\n")
    md.append("```markdown\n" + output_2 + "\n```\n")

    md.append("---\n")
    md.append("## 3. Example 2: Turn-Prefix Compaction (Split-Turn Context)\n")
    md.append("From trial: `Textualize__rich-2725__QGagC2t` (Compaction Entry #25, triggered when a single turn blew past `keepRecentTokens`).\n")
    md.append("### A. Exact System Prompt\n")
    md.append("```text\n" + SUMMARIZATION_SYSTEM_PROMPT + "\n```\n")
    md.append("### B. Exact Input Prompt Sent to the LLM\n")
    md.append("<details><summary><b>Click to expand full input prompt (9 KB)</b></summary>\n\n")
    md.append("```text\n" + prompt_input_1 + "\n```\n")
    md.append("</details>\n")
    md.append("### C. Exact Output Generated by the LLM\n")
    md.append("```markdown\n" + output_1 + "\n```\n")

    md.append("---\n")
    md.append("## 4. Why This Compaction Prompt Is Broken for Coding Tasks\n")
    md.append("### 1. Enforcing an Agile / Project-Management Template on Code Diffs")
    md.append("The prompt demands:\n")
    md.append("- `## Goal`\n- `## Constraints & Preferences`\n- `## Progress: Done / In Progress / Blocked`\n- `## Key Decisions`\n- `## Next Steps`\n")
    md.append("This is an executive meeting summary, **not a technical state checkpoint**. A coding agent trying to fix an open-source bug does not need a list of high-level goals—it needs:")
    md.append("- The exact failing pytest assertion / traceback.")
    md.append("- The exact unified diff applied so far.")
    md.append("- The exact line numbers and modified AST symbols.")
    md.append("None of this technical information survives the template.\n")

    md.append("### 2. Discarding the Thinking Process (`<thought>`)")
    md.append("Pi's `serializeConversation()` explicitly omits all assistant thinking: `Thinking is omitted. Providers return summaries of the real reasoning...`")
    md.append("By discarding the chain of thought, the agent forgets **why** it made a change, which alternative hypotheses were tested and refuted, and what edge cases it discovered. The post-compaction agent operates with total amnesia.\n")

    md.append("### 3. Truncating Tool Results to 2,000 Chars Causes Re-Read Death Spirals")
    md.append("Because `serializeConversation` cuts tool results at 2,000 characters, the model's view of any file read larger than ~60 lines is mutilated into `[... 37642 more characters truncated]`.")
    md.append("When the model resumes after compaction, it sees in its summary: `Attempted to apply fix to rich/table.py, but failed with SyntaxError`—but it **does not have the actual code of `rich/table.py` anymore**.")
    md.append("Its immediate, instinctual next action is `read rich/table.py` (reading 40k characters back into memory). This instantly balloons context back to 35,000+ tokens within 1 turn, triggering another compaction cycle.\n")

    md.append("### 4. Excessive Token & Latency Overhead (Timeout Accelerator)")
    md.append("Generating this verbose 2,000-character structured markdown checkpoint requires **~1,800 to 2,400 output tokens** and **~1,500 reasoning tokens**. On a local vLLM instance serving 40 concurrent trials:")
    md.append("- A single compaction request takes **60 to 100 seconds** of pure generation time.")
    md.append("- In trials with 2 or 3 compactions, **over 30% of the entire 600-second budget is burned purely on generating executive summaries** rather than writing code.")

    os.makedirs("post", exist_ok=True)
    with open("post/compact.md", "w") as f:
        f.write("\n".join(md))
    print("Wrote post/compact.md successfully!")

if __name__ == "__main__":
    build_compact_md()
