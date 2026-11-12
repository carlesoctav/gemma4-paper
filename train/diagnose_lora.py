import json
import time
import torch
import torch.nn.functional as F
from pathlib import Path
from safetensors import safe_open
from datasets import load_dataset
from transformers import AutoTokenizer, Gemma4ForConditionalGeneration
from peft import PeftModel

torch.set_num_threads(8)


def analyze_weights():
    print("=" * 80, flush=True)
    print("1. LORA WEIGHT NORM & SINGULAR VALUE SPECTRUM (SVD) ANALYSIS", flush=True)
    print("=" * 80, flush=True)

    adapters = [
        # Checkpoint progression for Simple LoRA 1e-4
        ("simple-lora-1e4 (step 25)", "/content/bucket/final/simple-lora-1e4-checkpoint-25/adapter_model.safetensors"),
        ("simple-lora-1e4 (step 50)", "/content/bucket/final/simple-lora-1e4-checkpoint-50/adapter_model.safetensors"),
        ("simple-lora-1e4 (step 75)", "/content/bucket/final/simple-lora-1e4-checkpoint-75/adapter_model.safetensors"),
        ("simple-lora-1e4 (step 100)", "/content/bucket/final/simple-lora-1e4/adapter_model.safetensors"),
        
        # Grafting 1e-4 progression
        ("grafting-1e4 (step 50)", "/content/bucket/final/grafting-lr-1e4-lam-1-checkpoint-50/adapter_model.safetensors"),
        ("grafting-1e4 (step 75)", "/content/bucket/final/grafting-lr-1e4-lam-1-checkpoint-75/adapter_model.safetensors"),
        ("grafting-1e4 (step 100)", "/content/bucket/final/grafting-lr-1e4-lam-1/adapter_model.safetensors"),

        # Simple LoRA 1e-5 vs Grafting 1e-5
        ("simple-lora-1e5 (step 100)", "/content/bucket/final/simple-lora-1e5/adapter_model.safetensors"),
        ("grafting-1e5 (step 100)", "/content/bucket/final/grafting-lr-1e5-lam-1/adapter_model.safetensors"),

        # Grafting 1e-3
        ("grafting-1e3 (step 100)", "/content/bucket/final/grafting-lr-1e3-lam-1/adapter_model.safetensors"),

        # IT & Mix direct runs
        ("it-lora-1e4 (step 100)", "/content/bucket/e4b_it_termgrade_p95_split/checkpoint-100/adapter_model.safetensors"),
        ("e4b_mix-1e3 (step 100)", "/content/bucket/e4b_mix_termgrade_p95_split_0.001/checkpoint-100/adapter_model.safetensors"),
    ]

    print(f"{'Adapter / Checkpoint':32s} | {'Modules':7s} | {'Mean ||dW||':11s} | {'Max ||dW||':10s} | {'SVD s0/s1':9s} | {'q_proj':8s} | {'gate_proj':9s}", flush=True)
    print("-" * 105, flush=True)

    for name, path_str in adapters:
        p = Path(path_str)
        if not p.exists():
            alt_path = path_str.replace("/final/simple-lora-1e4-checkpoint-25/", "/e4b_base_termgrade_p95_split_0.0001/checkpoint-25/")
            if Path(alt_path).exists():
                p = Path(alt_path)
            else:
                continue

        with safe_open(str(p), framework="pt") as f:
            keys = f.keys()
            a_keys = [k for k in keys if "lora_A" in k]

            delta_norms = []
            s0_ratios = []
            module_norms = {"q_proj": [], "v_proj": [], "gate_proj": [], "down_proj": []}

            for ak in a_keys:
                bk = ak.replace("lora_A", "lora_B")
                A = f.get_tensor(ak).float()  # (r, in_features)
                B = f.get_tensor(bk).float()  # (out_features, r)

                # Frobenius norm: ||B @ A||_F^2 = Tr(A A^T B^T B)
                AAt = A @ A.T
                BtB = B.T @ B
                norm = torch.sqrt(torch.clamp((AAt * BtB).sum(), min=0)).item()
                delta_norms.append(norm)

                # Fast rank-r SVD via QR decomposition
                try:
                    q_b, r_b = torch.linalg.qr(B)
                    q_a, r_a = torch.linalg.qr(A.T)
                    core = r_b @ r_a.T
                    S = torch.linalg.svdvals(core)
                    if len(S) >= 2 and S[1] > 1e-7:
                        s0_ratios.append((S[0] / S[1]).item())
                except Exception:
                    pass

                for mod in module_norms:
                    if f".{mod}." in ak:
                        module_norms[mod].append(norm)

            mean_norm = sum(delta_norms) / len(delta_norms) if delta_norms else 0
            max_norm = max(delta_norms) if delta_norms else 0
            mean_s_ratio = sum(s0_ratios) / len(s0_ratios) if s0_ratios else 0
            q_norm = sum(module_norms["q_proj"]) / len(module_norms["q_proj"]) if module_norms["q_proj"] else 0
            gate_norm = sum(module_norms["gate_proj"]) / len(module_norms["gate_proj"]) if module_norms["gate_proj"] else 0

            print(f"{name:32s} | {len(a_keys):7d} | {mean_norm:11.4f} | {max_norm:10.4f} | {mean_s_ratio:9.2f} | {q_norm:8.4f} | {gate_norm:9.4f}", flush=True)


def analyze_perplexity_and_accuracy():
    print("\n" + "=" * 80, flush=True)
    print("2. PERPLEXITY, LOSS & NEXT-TOKEN ACCURACY ON TERMGRADE SFT EVAL DATA", flush=True)
    print("=" * 80, flush=True)

    model_id = "google/gemma-4-E4B-it"
    tok = AutoTokenizer.from_pretrained(model_id)

    chat_template_file = Path("/content/final_term/chat_template.jinja")
    if chat_template_file.exists():
        tok.chat_template = chat_template_file.read_text()

    print("Loading base model in float32 on CPU (AVX2-accelerated)...", flush=True)
    t0 = time.time()
    base_model = Gemma4ForConditionalGeneration.from_pretrained(
        model_id,
        torch_dtype=torch.float32,
        device_map="cpu",
    )
    base_model.eval()
    print(f"Model loaded in {time.time() - t0:.1f}s.", flush=True)

    print("Loading carlesoctav/termgrade-p95-split_sft dataset...", flush=True)
    ds = load_dataset("carlesoctav/termgrade-p95-split_sft", split="train")

    # Select 5 representative terminal command completion samples
    indices = [25, 100, 300, 1000, 5000]
    samples = [ds[i] for i in indices]

    eval_batches = []
    total_eval_tokens = 0
    for idx, s in enumerate(samples):
        prompt_msgs = s["prompt"]
        completion_msgs = s["completion"]
        full_convo = list(prompt_msgs) + list(completion_msgs)

        prompt_text = tok.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True)
        full_text = tok.apply_chat_template(full_convo, tokenize=False, add_generation_prompt=False)

        prompt_ids = tok(prompt_text, return_tensors="pt")["input_ids"]
        full_ids = tok(full_text, return_tensors="pt")["input_ids"]

        # Bound sequence length to 768 for fast CPU inference
        if full_ids.shape[1] > 768:
            full_ids = full_ids[:, :768]

        p_len = min(prompt_ids.shape[1], full_ids.shape[1] - 1)
        labels = full_ids.clone()
        labels[:, :p_len] = -100

        active_count = (labels[:, 1:] != -100).sum().item()
        if active_count > 0:
            eval_batches.append((full_ids, labels))
            total_eval_tokens += active_count

    print(f"Prepared {len(eval_batches)} evaluation samples ({total_eval_tokens} completion tokens).", flush=True)

    def evaluate_model(model, label_name):
        total_loss = 0.0
        total_correct = 0
        total_tokens = 0
        t_start = time.time()

        with torch.no_grad():
            for b_idx, (full_ids, labels) in enumerate(eval_batches):
                outputs = model(input_ids=full_ids)
                logits = outputs.logits[:, :-1, :].contiguous()
                target = labels[:, 1:].contiguous()

                mask = (target != -100)
                active_logits = logits[mask]
                active_target = target[mask]

                loss = F.cross_entropy(active_logits, active_target)
                total_loss += loss.item() * active_target.numel()

                preds = active_logits.argmax(dim=-1)
                total_correct += (preds == active_target).sum().item()
                total_tokens += active_target.numel()

        avg_loss = total_loss / total_tokens
        accuracy = (total_correct / total_tokens) * 100
        ppl = torch.exp(torch.tensor(avg_loss)).item()
        elapsed = time.time() - t_start
        print(f"  {label_name:35s} | Loss: {avg_loss:.4f} | Perplexity: {ppl:7.2f} | Next-token Acc: {accuracy:.2f}% | ({elapsed:.1f}s)", flush=True)
        return avg_loss, accuracy

    print("\n--- Evaluating Models on TermGrade Completions ---", flush=True)
    evaluate_model(base_model, "Base IT (Zero-shot / No Adapter)")

    adapters_to_eval = [
        ("Base IT + Simple LoRA 1e-4", "/content/bucket/final/simple-lora-1e4"),
        ("Base IT + Grafting 1e-4 (lam=1)", "/content/bucket/final/grafting-lr-1e4-lam-1"),
        ("Base IT + Simple LoRA 1e-5", "/content/bucket/final/simple-lora-1e5"),
        ("Base IT + Grafting 1e-5 (lam=1)", "/content/bucket/final/grafting-lr-1e5-lam-1"),
        ("Base IT + Grafting 1e-3 (lam=1)", "/content/bucket/final/grafting-lr-1e3-lam-1"),
    ]

    for name, adapter_path in adapters_to_eval:
        if not Path(adapter_path).exists():
            print(f"Skipping {name}: path {adapter_path} not found", flush=True)
            continue
        try:
            peft_m = PeftModel.from_pretrained(base_model, adapter_path)
            peft_m.eval()
            evaluate_model(peft_m, name)
            peft_m.unload()
        except Exception as e:
            print(f"  {name} failed to load: {e}", flush=True)


def main():
    analyze_weights()
    analyze_perplexity_and_accuracy()


if __name__ == "__main__":
    main()
