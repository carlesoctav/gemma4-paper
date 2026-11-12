import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["UNSLOTH_DISABLE_VERSION_CHECK"] = "1"
os.environ["UNSLOTH_BLOCK_COMPILE"] = "0"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRACKIO_DIR"] = "/kaggle/working"

from pathlib import Path
import subprocess

wheelhouse_dir = Path("/kaggle/input/datasets/carlesoctav/final-term-wheelhouse")
if wheelhouse_dir.exists():
    try:
        import unsloth
        import trl
        import trackio
        import sws
        import final_term
    except ImportError:
        subprocess.run(
            ["cp /kaggle/input/datasets/carlesoctav/final-term-wheelhouse/flash_attn* /kaggle/working/flash_attn-2.8.4+cu13torch2.14cxx11abiTRUE-cp313-cp313-linux_x86_64.whl"],
            shell=True,
            check=False,
        )
        whls = [str(p) for p in wheelhouse_dir.glob("*.whl") if "flash_attn" not in p.name]
        subprocess.run(["uv", "pip", "install", "--no-deps"] + whls, check=True)
        subprocess.run(
            ["uv", "pip", "install", "--no-deps", "/kaggle/working/flash_attn-2.8.4+cu13torch2.14cxx11abiTRUE-cp313-cp313-linux_x86_64.whl"],
            check=False,
        )

import unsloth
from unsloth import FastLanguageModel
import torch
import sws
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer
from transformers import TrainerCallback
from final_term.ffpa_attention import register_ffpa_attention
import transformers.integrations.flex_attention as fa

original_flex = fa.compile_friendly_flex_attention
flex_kernel_opts = {
    "BLOCK_M": 32, "BLOCK_N": 32,
    "BLOCK_M1": 16, "BLOCK_N1": 16,
    "BLOCK_M2": 16, "BLOCK_N2": 16,
    "num_stages": 2, "num_warps": 4,
}

def _patched_flex(query, key, value, training=False, **kwargs):
    opts = dict(kwargs.get("kernel_options") or {})
    opts.update(flex_kernel_opts)
    kwargs["kernel_options"] = opts
    return original_flex(query, key, value, training=training, **kwargs)

fa.compile_friendly_flex_attention = _patched_flex

register_ffpa_attention()


class TorchrunGemma4CpuOffloadCallback(TrainerCallback):
    """
    Works with both single-GPU and multi-GPU torchrun (DDP):
    Runs inside on_train_begin AFTER Accelerator.prepare() and DDP.__init__()
    have wrapped the LoRA parameters, so DDP never complains about mixed CPU/CUDA
    devices and Trainer never drags embeddings back to GPU.
    """
    def on_train_begin(self, args, state, control, **kwargs):
        model = kwargs["model"]
        raw_model = model.module if hasattr(model, "module") else model

        local_rank = int(os.environ.get("LOCAL_RANK", 0))
        target_gpu = torch.device(f"cuda:{local_rank}")

        text_model = raw_model.base_model.model.model.language_model
        lm_head = raw_model.base_model.model.lm_head

        # 1. Untie lm_head from embed_tokens so lm_head stays on cuda:{local_rank}
        #    and freeze it so AddmmBackward0 never computes grad_weight (index 2)
        if lm_head.weight.data_ptr() == text_model.embed_tokens.weight.data_ptr():
            lm_head.weight = torch.nn.Parameter(
                text_model.embed_tokens.weight.detach().clone().to(target_gpu),
                requires_grad=False,
            )
        else:
            lm_head.to(target_gpu)
            lm_head.weight.requires_grad_(False)

        # 2. Offload frozen nn.Embedding to CPU (and share OS pages across ranks)
        def _offload_embedding(emb: torch.nn.Embedding):
            emb.to("cpu")
            emb.weight.requires_grad_(False)
            emb.weight.data.share_memory_()

            if not getattr(emb, "_ddp_cpu_patched", False):
                orig_forward = emb.forward
                def _cpu_forward(input_ids, *f_args, **f_kwargs):
                    out = orig_forward(input_ids.to("cpu"), *f_args, **f_kwargs)
                    return out.to(input_ids.device, non_blocking=True)
                emb.forward = _cpu_forward
                emb._ddp_cpu_patched = True

        # 3. Offload Gemma 4 PLE (~4.70 GB table) to CPU while keeping embed_tokens (1.25 GB) on GPU
        # Keeping embed_tokens on GPU ensures pad_embedding and inputs_embeds share device cuda:{local_rank}
        if getattr(text_model, "embed_tokens_per_layer", None) is not None:
            _offload_embedding(text_model.embed_tokens_per_layer)

        # 4. Offload unused multimodal towers (~1.5 GB)
        vlm_base = raw_model.base_model.model.model
        for attr in ("vision_tower", "audio_tower", "embed_vision", "embed_audio"):
            mod = getattr(vlm_base, attr, None)
            if mod is not None:
                mod.to("cpu")
                for p in mod.parameters():
                    p.requires_grad_(False)

        torch.cuda.empty_cache()


def get_config() -> sws.Config:
    config = sws.Config()

    config.train.model.name = (
        "/kaggle/input/models/google/gemma-4/transformers/gemma-4-e4b-it/1"
    )
    config.train.model.max_seq_length = 32768
    config.train.model.load_in_4bit = False

    config.train.peft.r = 16
    config.train.peft.lora_alpha = 16
    config.train.peft.target_modules = (
        r".*\.language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
    )

    config.train.data.path = (
        "/kaggle/input/datasets/carlesoctav/final-term-wheelhouse/termgrade_train_sft_32k.jsonl"
    )
    config.train.data.split = "train"

    config.train.sft.output_dir = "/kaggle/working/output"
    config.train.sft.max_seq_length = 32768
    config.train.sft.packing = False
    config.train.sft.per_device_train_batch_size = 1
    config.train.sft.gradient_accumulation_steps = 8
    config.train.sft.learning_rate = 1e-4
    config.train.sft.lr_scheduler_type = "cosine"
    config.train.sft.warmup_ratio = 0.1
    config.train.sft.weight_decay = 0.01
    config.train.sft.max_steps = -1
    config.train.sft.num_train_epochs = 1
    config.train.sft.logging_steps = 1
    config.train.sft.save_strategy = "steps"
    config.train.sft.save_steps = 30
    config.train.sft.report_to = "trackio"
    config.train.sft.project = "termgrade-e4b"
    config.train.sft.run_name = "post-e4b_termgrade_32k"

    return config


def main(config, unused=None):
    model_config = config.train.model.to_dict()
    peft_config = config.train.peft.to_dict()
    data_config = config.train.data.to_dict()
    sft_config = config.train.sft.to_dict()

    model_name = model_config.pop("name")

    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    torch.cuda.set_device(local_rank)

    model, processor = FastLanguageModel.from_pretrained(
        model_name=model_name,
        dtype=torch.bfloat16,
        offload_embedding=False,
        device_map={"": f"cuda:{local_rank}"},
        **model_config,
    )
    model.config._attn_implementation = "ffpa"
    model.config.text_config._attn_implementation = "ffpa"

    model = FastLanguageModel.get_peft_model(
        model,
        **peft_config,
        use_gradient_checkpointing="unsloth",
    )

    for name, param in model.named_parameters():
        if "lora_" not in name:
            param.requires_grad_(False)

    dataset_path = data_config.pop("path")
    dataset = load_dataset("json", data_files=dataset_path, **data_config)

    sft_config["output_dir"] = os.path.join(sft_config["output_dir"], sft_config["run_name"])

    trainer = SFTTrainer(
        model=model,
        processing_class=processor.tokenizer,
        train_dataset=dataset,
        args=SFTConfig(
            **sft_config,
            ddp_find_unused_parameters=False,
            ddp_broadcast_buffers=False,
        ),
        callbacks=[TorchrunGemma4CpuOffloadCallback()],
    )

    trainer.train()

    output_dir = sft_config["output_dir"]
    lora_save_path = os.path.join(output_dir, "lora_adapter")
    trainer.save_model(lora_save_path)
    if trainer.is_world_process_zero():
        processor.save_pretrained(lora_save_path)


if __name__ == "__main__":
    sws.run(main, forward_extras=True)
