import sws


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
    config.train.sft.adam_beta1 = 0.9
    config.train.sft.adam_beta2 = 0.95
    config.train.sft.max_steps = -1
    config.train.sft.num_train_epochs = 1
    config.train.sft.logging_steps = 1
    config.train.sft.save_strategy = "steps"
    config.train.sft.save_steps = 30
    config.train.sft.report_to = "trackio"
    config.train.sft.project = "termgrade-e4b"
    config.train.sft.run_name = "post-e4b_termgrade_32k"

    return config
