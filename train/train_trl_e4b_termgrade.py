import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import torch
import sws
from datasets import load_dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer


def main(config, unused=None):
    model_config = config.train.model.to_dict()
    peft_config_dict = config.train.peft.to_dict()
    data_config = config.train.data.to_dict()
    sft_config = config.train.sft.to_dict()

    model_name = model_config.pop("name")
    chat_template_path = model_config.pop("chat_template_path")

    sft_config["chat_template_path"] = chat_template_path
    sft_config["bf16"] = True
    sft_config["model_init_kwargs"] = {"dtype": torch.bfloat16}
    sft_config["output_dir"] = os.path.join(sft_config["output_dir"], sft_config["run_name"])

    if "max_seq_length" in sft_config:
        sft_config["max_length"] = sft_config.pop("max_seq_length")
    if "warmup_ratio" in sft_config:
        sft_config["warmup_steps"] = sft_config.pop("warmup_ratio")

    peft_config = LoraConfig(**peft_config_dict)
    dataset = load_dataset(**data_config)

    trainer = SFTTrainer(
        model=model_name,
        peft_config=peft_config,
        train_dataset=dataset,
        args=SFTConfig(**sft_config),
    )

    trainer.train()

    lora_save_path = os.path.join(sft_config["output_dir"], "lora_adapter")
    trainer.model.save_pretrained(lora_save_path)
    trainer.processing_class.save_pretrained(lora_save_path)


if __name__ == "__main__":
    sws.run(main, forward_extras=True)
