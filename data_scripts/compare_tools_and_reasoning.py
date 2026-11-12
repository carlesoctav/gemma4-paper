import json
import glob
import os
import re
import numpy as np
from collections import Counter

def parse_bash_commands(command_str):
    """Extract individual commands / tools invoked in a bash script or pipeline."""
    # Find tool occurrences like grep, git, pytest, python, cat, etc.
    invoked = set()
    # Normalize
    lines = command_str.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Split pipelines and semicolons and && / ||
        subcmds = re.split(r"[|;&]+", line)
        for sc in subcmds:
            sc = sc.strip()
            if not sc:
                continue
            tokens = sc.split()
            first = tokens[0]
            # remove variable assignments like VAR=val
            if "=" in first and not first.startswith("-"):
                if len(tokens) > 1:
                    first = tokens[1]
                else:
                    continue
            base = os.path.basename(first)
            invoked.add(base)
    return invoked

def analyze_job(job_dir):
    tool_counts = Counter()
    bash_tool_counts = Counter()
    bash_full_calls = 0
    
    # Reasoning stats
    reasoning_tokens_per_step = []
    reasoning_tokens_per_trial = []
    output_tokens_per_step = []
    output_tokens_per_trial = []
    steps_per_trial = []
    
    trials = 0
    
    for trial_dir in sorted(glob.glob(f"{job_dir}/*")):
        if not os.path.isdir(trial_dir):
            continue
        traj_file = os.path.join(trial_dir, "agent", "trajectory.json")
        if not os.path.exists(traj_file):
            continue
            
        trials += 1
        with open(traj_file) as f:
            traj = json.load(f)
            
        steps = traj.get("steps", [])
        steps_per_trial.append(len(steps))
        
        trial_r_tok = 0
        trial_o_tok = 0
        
        for step in steps:
            metrics = step.get("metrics", {})
            r_tok = metrics.get("extra", {}).get("reasoning_tokens", 0) or 0
            o_tok = metrics.get("completion_tokens", 0) or 0
            
            if r_tok > 0:
                reasoning_tokens_per_step.append(r_tok)
                trial_r_tok += r_tok
            if o_tok > 0:
                output_tokens_per_step.append(o_tok)
                trial_o_tok += o_tok
                
            for tc in step.get("tool_calls", []):
                tname = tc.get("function_name") or tc.get("name") or "unknown"
                tool_counts[tname] += 1
                if tname == "bash":
                    bash_full_calls += 1
                    args = tc.get("arguments", {})
                    cmd = args.get("command", "") if isinstance(args, dict) else str(args)
                    cmds_in_call = parse_bash_commands(cmd)
                    for c in cmds_in_call:
                        bash_tool_counts[c] += 1
                        
        reasoning_tokens_per_trial.append(trial_r_tok)
        output_tokens_per_trial.append(trial_o_tok)
        
    return {
        "trials": trials,
        "tool_counts": tool_counts,
        "bash_tool_counts": bash_tool_counts,
        "bash_full_calls": bash_full_calls,
        "r_step": reasoning_tokens_per_step,
        "r_trial": reasoning_tokens_per_trial,
        "o_step": output_tokens_per_step,
        "o_trial": output_tokens_per_trial,
        "steps_per_trial": steps_per_trial
    }

def get_percentiles(arr):
    if not arr:
        return {}
    a = np.array(arr)
    return {
        "mean": float(np.mean(a)),
        "std": float(np.std(a)),
        "min": float(np.min(a)),
        "p25": float(np.percentile(a, 25)),
        "p50": float(np.percentile(a, 50)),
        "p75": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
        "max": float(np.max(a)),
        "total": float(np.sum(a))
    }

lora = analyze_job("harbor/jobs/fix-simple-lora-1e4-eval_tasks-gemma4_gh_pr")
graft = analyze_job("harbor/jobs/fix-grafting-lr-1e4-lam-1-eval_tasks-gemma4_gh_pr")

print(f"=== GENERAL OVERVIEW ===")
print(f"Trials: LoRA={lora['trials']}, Grafting={graft['trials']}")
print(f"Steps/Trial: LoRA mean={np.mean(lora['steps_per_trial']):.1f}, Grafting mean={np.mean(graft['steps_per_trial']):.1f}")
print(f"Total Tool Calls: LoRA={sum(lora['tool_counts'].values())}, Grafting={sum(graft['tool_counts'].values())}")

print(f"\n=== HIGH-LEVEL TOOL DISTRIBUTION ===")
all_tools = sorted(set(list(lora['tool_counts'].keys()) + list(graft['tool_counts'].keys())))
print(f"{'Tool':<15} | {'LoRA Count':<12} | {'LoRA %':<8} | {'Graft Count':<12} | {'Graft %':<8}")
print("-" * 65)
tot_lora_tools = sum(lora['tool_counts'].values())
tot_graft_tools = sum(graft['tool_counts'].values())
for t in all_tools:
    c_l = lora['tool_counts'][t]
    c_g = graft['tool_counts'][t]
    p_l = (c_l / tot_lora_tools * 100) if tot_lora_tools else 0
    p_g = (c_g / tot_graft_tools * 100) if tot_graft_tools else 0
    print(f"{t:<15} | {c_l:<12} | {p_l:>6.1f}% | {c_g:<12} | {p_g:>6.1f}%")

print(f"\n=== BASH COMMAND DISTRIBUTION (Common Tools) ===")
top_bash = [
    "python", "python3", "pytest", "git", "grep", "rg", "find",
    "cat", "ls", "cd", "mkdir", "rm", "cp", "mv", "sed", "head",
    "tail", "echo", "which", "pip", "uv"
]
print(f"{'Bash Command':<15} | {'LoRA Calls':<12} | {'LoRA/Trial':<10} | {'Graft Calls':<12} | {'Graft/Trial':<10}")
print("-" * 70)
for cmd in top_bash:
    c_l = lora['bash_tool_counts'][cmd]
    c_g = graft['bash_tool_counts'][cmd]
    l_pt = c_l / lora['trials'] if lora['trials'] else 0
    g_pt = c_g / graft['trials'] if graft['trials'] else 0
    print(f"{cmd:<15} | {c_l:<12} | {l_pt:>8.2f}  | {c_g:<12} | {g_pt:>8.2f}")

# Other notable commands in either
other_cmds = sorted(set(list(lora['bash_tool_counts'].keys()) + list(graft['bash_tool_counts'].keys())))
notable_others = [c for c in other_cmds if c not in top_bash and (lora['bash_tool_counts'][c] > 5 or graft['bash_tool_counts'][c] > 5)]
print(f"\nOther notable bash commands: {notable_others}")
for cmd in notable_others:
    print(f"  {cmd:<15}: LoRA={lora['bash_tool_counts'][cmd]} vs Graft={graft['bash_tool_counts'][cmd]}")

print(f"\n=== REASONING TOKENS DISTRIBUTION (PER STEP) ===")
r_step_lora = get_percentiles(lora['r_step'])
r_step_graft = get_percentiles(graft['r_step'])
print(f"{'Metric':<10} | {'LoRA (tokens)':<15} | {'Grafting (tokens)':<15}")
print("-" * 45)
for k in ["mean", "std", "min", "p25", "p50", "p75", "p90", "max", "total"]:
    print(f"{k:<10} | {r_step_lora.get(k, 0):<15.1f} | {r_step_graft.get(k, 0):<15.1f}")

print(f"\n=== REASONING TOKENS DISTRIBUTION (PER TRIAL) ===")
r_trial_lora = get_percentiles(lora['r_trial'])
r_trial_graft = get_percentiles(graft['r_trial'])
print(f"{'Metric':<10} | {'LoRA (tokens)':<15} | {'Grafting (tokens)':<15}")
print("-" * 45)
for k in ["mean", "std", "min", "p25", "p50", "p75", "p90", "max", "total"]:
    print(f"{k:<10} | {r_trial_lora.get(k, 0):<15.1f} | {r_trial_graft.get(k, 0):<15.1f}")

print(f"\n=== REASONING FRACTION OF OUTPUT TOKENS ===")
# reasoning / completion tokens
tot_r_l = sum(lora['r_step'])
tot_o_l = sum(lora['o_step'])
tot_r_g = sum(graft['r_step'])
tot_o_g = sum(graft['o_step'])
print(f"LoRA: {tot_r_l:.0f} reasoning / {tot_o_l:.0f} total completion ({tot_r_l/tot_o_l*100:.1f}%)")
print(f"Graft: {tot_r_g:.0f} reasoning / {tot_o_g:.0f} total completion ({tot_r_g/tot_o_g*100:.1f}%)")
