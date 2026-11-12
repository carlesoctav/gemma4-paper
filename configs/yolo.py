import sws


def get_config() -> sws.Config:
    config = sws.Config()

    config.train.model.name = "google/gemma-4-E4B"
    config.train.model.chat_template_path = "chat_template.jinja"
    config.train.model.max_seq_length = 16384
    config.train.model.load_in_4bit = False

    config.train.peft.r = 128
    config.train.peft.lora_alpha = 256
    config.train.peft.target_modules = (
        r".*\.language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj|per_layer_input_gate|per_layer_projection|per_layer_model_projection)"
    )

    config.train.data.path = "carlesoctav/termgrade-p95-split_sft"
    config.train.data.split = "train"

    config.train.sft.output_dir = "/content/bucket"
    config.train.sft.max_seq_length = 16384
    config.train.sft.per_device_train_batch_size = 8
    config.train.sft.gradient_accumulation_steps = 4
    config.train.sft.learning_rate = 1e-3
    config.train.sft.lr_scheduler_type = "cosine"
    config.train.sft.warmup_ratio = 0.1
    config.train.sft.weight_decay = 0.01
    config.train.sft.max_steps = 300
    # config.train.sft.num_train_epochs = 1
    config.train.sft.logging_steps = 1
    config.train.sft.save_strategy = "steps"
    config.train.sft.save_steps = 50
    config.train.sft.report_to = "trackio"
    config.train.sft.project = "termgrade-fix-e4b"
    config.train.sft.run_name = lambda : f"e4b_base_yolo_r128_a256_all_linear_{str(config.train.sft.learning_rate)}"
    config.train.sft.padding_free = True
    # config.train.sft.packing = False

    return config
