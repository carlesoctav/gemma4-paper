import sws


def get_config() -> sws.Config:
    config = sws.Config()

    config.train.model.name = "google/gemma-4-E4B"
    config.train.model.chat_template_path = "chat_template.jinja"
    config.train.model.max_seq_length = 32768
    config.train.model.load_in_4bit = False

    config.train.peft.r = 16
    config.train.peft.lora_alpha = 16
    config.train.peft.target_modules = (
        r".*\.language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
    )

    config.train.data.path = "data/termgrade_train_sft_32k.jsonl"
    config.train.data.split = "train"

    config.train.sft.output_dir = "/content/bucket"
    config.train.sft.max_seq_length = 32768
    config.train.sft.packing = False
    config.train.sft.per_device_train_batch_size = 4
    config.train.sft.gradient_accumulation_steps = 8
    config.train.sft.learning_rate = 1e-4
    config.train.sft.lr_scheduler_type = "constant"
    config.train.sft.warmup_ratio = 0
    config.train.sft.weight_decay = 0.01
    config.train.sft.max_steps = -1
    config.train.sft.num_train_epochs = 1
    config.train.sft.logging_steps = 1
    config.train.sft.save_strategy = "steps"
    config.train.sft.save_steps = 30
    config.train.sft.report_to = "trackio"
    config.train.sft.project = "termgrade-e4b"
    config.train.sft.run_name = "e4b_termgrade_32k_fix-chat-template"

    return config
