import re
import numpy as np
import torch
from safetensors import safe_open

adapters = {
    "Base-LoRA 1e-5 (graft-1e5)": "/content/bucket/final/grafting-lr-1e5-lam-1/adapter_model.safetensors",
    "Base-LoRA 1e-4 (graft-1e4)": "/content/bucket/final/grafting-lr-1e4-lam-1/adapter_model.safetensors",
    "Base-LoRA 1e-3 (graft-1e3)": "/content/bucket/final/grafting-lr-1e3-lam-1/adapter_model.safetensors",
    "IT-LoRA 1e-5   (simple-1e5)": "/content/bucket/final/simple-lora-1e5/adapter_model.safetensors",
    "IT-LoRA 1e-4   (simple-1e4)": "/content/bucket/final/simple-lora-1e4/adapter_model.safetensors",
    "Mix-LoRA 1e-3  (step 100)": "/content/bucket/e4b_mix_termgrade_p95_split_0.001/checkpoint-100/adapter_model.safetensors",
}

print("=" * 105)
h = "%-27s | %-11s | %-8s | %-6s | %-11s | %-10s | %-12s | %-12s" % (
    "Model / Adapter", "Mean ||dW||", "Eff Rank", "s0/s1", "Attn ||dW||", "MLP ||dW||", "Early (0-10)", "Late (30-41)"
)
print(h)
print("-" * 105)

for name, path in adapters.items():
    with safe_open(path, framework="pt") as f:
        keys = [k for k in f.keys() if "lora_A" in k]
        norms, eff_ranks, s0_s1 = [], [], []
        attn_norms, mlp_norms = [], []
        early_norms, late_norms = [], []

        for ak in keys:
            bk = ak.replace("lora_A", "lora_B")
            A = f.get_tensor(ak).float()
            B = f.get_tensor(bk).float()

            # Fast rank-r SVD via QR
            q_b, r_b = torch.linalg.qr(B)
            q_a, r_a = torch.linalg.qr(A.T)
            core = r_b @ r_a.T
            S = torch.linalg.svdvals(core)

            norm = torch.norm(S).item()
            norms.append(norm)

            # Effective rank = (sum(S))^2 / sum(S^2)
            if (S**2).sum() > 0:
                eff_r = ((S.sum()**2) / (S**2).sum()).item()
                eff_ranks.append(eff_r)
            if len(S) >= 2 and S[1] > 1e-7:
                s0_s1.append((S[0] / S[1]).item())

            is_attn = any(m in ak for m in ["q_proj", "k_proj", "v_proj", "o_proj"])
            if is_attn:
                attn_norms.append(norm)
            else:
                mlp_norms.append(norm)

            m = re.search(r"layers\.(\d+)\.", ak)
            if m:
                layer = int(m.group(1))
                if layer <= 10:
                    early_norms.append(norm)
                elif layer >= 30:
                    late_norms.append(norm)

        m_norm = np.mean(norms)
        m_eff = np.mean(eff_ranks)
        m_s = np.mean(s0_s1)
        m_attn = np.mean(attn_norms)
        m_mlp = np.mean(mlp_norms)
        m_early = np.mean(early_norms)
        m_late = np.mean(late_norms)

        print("%-27s | %11.4f | %8.2f | %6.2f | %11.4f | %10.4f | %12.4f | %12.4f" % (
            name, m_norm, m_eff, m_s, m_attn, m_mlp, m_early, m_late
        ))
