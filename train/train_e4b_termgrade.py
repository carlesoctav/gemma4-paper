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
from transformers import AutoTokenizer


def main(config, unused=None):
    model_config = config.train.model.to_dict()
    peft_config = config.train.peft.to_dict()
    data_config = config.train.data.to_dict()
    sft_config = config.train.sft.to_dict()

    model_name = model_config.pop("name")
    chat_template_path = model_config.pop("chat_template_path")
    tok = AutoTokenizer.from_pretrained('google/gemma-4-E4B-it')

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
    dataset = load_dataset(**data_config)
    sft_config["output_dir"] = os.path.join(sft_config["output_dir"], sft_config["run_name"])

    trainer = SFTTrainer(
        model=model,
        processing_class=tok,
        train_dataset=dataset,
        args=SFTConfig(**sft_config),
    )

    trainer.train()

    output_dir = sft_config["output_dir"]
    lora_save_path = os.path.join(output_dir, "lora_adapter")
    trainer.model.save_pretrained(lora_save_path)
    tok.save_pretrained(lora_save_path)


if __name__ == "__main__":
    sws.run(main, forward_extras=True)
