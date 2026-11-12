from pathlib import Path
import re
import shutil
from huggingface_hub import HfApi, snapshot_download
from safetensors import safe_open
from safetensors.torch import save_file


BASE_REPO = "unsloth/gemma-4-E4B"
IT_REPO = "google/gemma-4-E4B-it"
TARGET_REPO = "carlesoctav/gemma4-e4b-mix"
OUT_DIR = Path("/content/gemma4-e4b-mix")

LORA_TARGET_RE = re.compile(
    r".*\.language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)\.weight$"
)

METADATA_FILES = [
    "config.json",
    "generation_config.json",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "chat_template.jinja",
]


def main() -> None:
    base_dir = Path(snapshot_download(BASE_REPO))
    it_dir = Path(snapshot_download(IT_REPO))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for fname in METADATA_FILES:
        shutil.copy2(it_dir / fname, OUT_DIR / fname)

    merged_tensors = {}
    it_keys = []
    base_keys = []

    with (
        safe_open(base_dir / "model.safetensors", framework="pt", device="cpu") as f_base,
        safe_open(it_dir / "model.safetensors", framework="pt", device="cpu") as f_it,
    ):
        metadata = f_it.metadata()
        for k in f_base.keys():
            if LORA_TARGET_RE.match(k):
                merged_tensors[k] = f_base.get_tensor(k)
                base_keys.append(k)
            else:
                merged_tensors[k] = f_it.get_tensor(k)
                it_keys.append(k)

    print(f"Loaded {len(base_keys)} LoRA-target tensors from {BASE_REPO} (Base).")
    print(f"Loaded {len(it_keys)} non-LoRA tensors from {IT_REPO} (IT).")

    out_safetensors = OUT_DIR / "model.safetensors"
    print(f"Saving merged safetensors to {out_safetensors}...")
    save_file(merged_tensors, str(out_safetensors), metadata=metadata)
    print("Saved model.safetensors successfully.")

    api = HfApi()
    api.create_repo(repo_id=TARGET_REPO, repo_type="model", exist_ok=True)
    print(f"Uploading {OUT_DIR} to {TARGET_REPO}...")
    api.upload_folder(
        repo_id=TARGET_REPO,
        folder_path=str(OUT_DIR),
        repo_type="model",
        commit_message="Gemma 4 E4B mix: Base on LoRA targets, IT on everything else",
    )
    print(f"Uploaded successfully to https://huggingface.co/{TARGET_REPO}")


if __name__ == "__main__":
    main()
