import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["UNSLOTH_DISABLE_VERSION_CHECK"] = "1"
os.environ["UNSLOTH_BLOCK_COMPILE"] = "0"

import unsloth
from unsloth import FastLanguageModel
import torch
import sws
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from transformers import AutoTokenizer, TrainerCallback


def project_left(tensor: torch.Tensor, u_k: torch.Tensor) -> torch.Tensor:
    t_f32 = tensor.float()
    u_f32 = u_k.to(device=tensor.device, dtype=torch.float32, non_blocking=True)
    return (t_f32 - u_f32 @ (u_f32.T @ t_f32)).to(tensor.dtype)


def project_right(tensor: torch.Tensor, v_k: torch.Tensor) -> torch.Tensor:
    t_f32 = tensor.float()
    v_f32 = v_k.to(device=tensor.device, dtype=torch.float32, non_blocking=True)
    return (t_f32 - (t_f32 @ v_f32) @ v_f32.T).to(tensor.dtype)


def compute_top_k_basis(w0: torch.Tensor, k: int):
    d_out, d_in = w0.shape
    if d_in <= d_out:
        evals, evecs = torch.linalg.eigh(w0.T @ w0)
        v_k = evecs[:, -k:].contiguous()
        u_k = ((w0 @ v_k) * evals[-k:].rsqrt()).contiguous()
    else:
        evals, evecs = torch.linalg.eigh(w0 @ w0.T)
        u_k = evecs[:, -k:].contiguous()
        v_k = ((w0.T @ u_k) * evals[-k:].rsqrt()).contiguous()

    return u_k.cpu(), v_k.cpu()


class OPLoRAImproveCallback(TrainerCallback):
    def __init__(self, projections):
        self.projections = projections

    @torch.no_grad()
    def project_weights(self):
        for lora_A, lora_B, u_k, v_k in self.projections:
            lora_A.data.copy_(project_right(lora_A.data, v_k))
            lora_B.data.copy_(project_left(lora_B.data, u_k))

    def on_step_end(self, args, state, control, **kwargs):
        self.project_weights()


def apply_oplora_improve(model, k: int, r_frac: float) -> OPLoRAImproveCallback:
    assert (k > 0) != (r_frac > 0.0), "Specify exactly one of k > 0 or r_frac > 0.0"
    projections = []
    with torch.no_grad():
        for _, module in model.named_modules():
            if "lora_A" in module._modules and "lora_B" in module._modules:
                w0 = module.base_layer.weight.data.float()
                d_min = min(w0.shape)
                k_layer = int(r_frac * d_min) if r_frac > 0.0 else k
                u_k, v_k = compute_top_k_basis(w0, k_layer)

                lora_A = module.lora_A["default"].weight
                lora_B = module.lora_B["default"].weight

                lora_A.data.copy_(project_right(lora_A.data, v_k))
                lora_B.data.copy_(project_left(lora_B.data, u_k))

                projections.append((lora_A, lora_B, u_k, v_k))

    return OPLoRAImproveCallback(projections)


def main(config, unused=None):
    model_config = config.train.model.to_dict()
    peft_config = config.train.peft.to_dict()
    oplora_config = config.train.oplora.to_dict()
    data_config = config.train.data.to_dict()
    sft_config = config.train.sft.to_dict()

    model_name = model_config.pop("name")
    model_config.pop("chat_template_path")
    tok = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")

    model, _ = FastLanguageModel.from_pretrained(
        model_name=model_name,
        dtype=torch.bfloat16,
        **model_config,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        **peft_config,
        use_gradient_checkpointing="unsloth",
    )

    oplora_cb = apply_oplora_improve(model, **oplora_config)

    dataset = load_dataset(**data_config)
    sft_config["output_dir"] = os.path.join(sft_config["output_dir"], sft_config["run_name"])

    trainer = SFTTrainer(
        model=model,
        processing_class=tok,
        train_dataset=dataset,
        args=SFTConfig(**sft_config),
        callbacks=[oplora_cb],
    )

    trainer.train()
    oplora_cb.project_weights()

    output_dir = sft_config["output_dir"]
    lora_save_path = os.path.join(output_dir, "lora_adapter")
    trainer.model.save_pretrained(lora_save_path)
    tok.save_pretrained(lora_save_path)


if __name__ == "__main__":
    sws.run(main, forward_extras=True)
