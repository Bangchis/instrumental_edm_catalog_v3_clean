#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from huggingface_hub import HfApi

from music_pipeline.common import write_json


MODEL_CARD = """---
license: other
library_name: peft
base_model: ACE-Step/acestep-v15-xl-base
tags:
- music-generation
- ace-step
- lora
---

# Melodic EDM Core — ACE-Step 1.5 XL-Base LoRA

LoRA rank 32 adapter trained for instrumental melodic EDM generation on
ACE-Step 1.5 XL-Base. The training audio and preprocessing tensors are not
included. Audio examples in this repository are generated outputs only.

## Use

Load `adapter_model.safetensors` and `adapter_config.json` with ACE-Step 1.5,
then generate with the accompanying `infer_adapter.py` example. The training
configuration is recorded in `training_config.json`.

## Limitations

This adapter may reflect biases or recognizable stylistic patterns present in
its training references. Users are responsible for checking rights, licenses,
and suitability of generated outputs before distribution or commercial use.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish only the trained adapter and generated samples to Hugging Face.")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--repo-id", default="Bangchis/melodic-edm-core-ace-step-lora")
    parser.add_argument("--release-dir", type=Path, default=Path("release/huggingface"))
    parser.add_argument("--inference-script", type=Path, default=Path("scripts/infer_adapter.py"))
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    required = ["adapter_model.safetensors", "adapter_config.json"]
    missing = [name for name in required if not (args.adapter / name).is_file()]
    if missing:
        raise SystemExit(f"adapter is incomplete: {missing}")
    if args.release_dir.is_symlink():
        raise SystemExit(f"refusing symlink release directory: {args.release_dir}")
    args.release_dir.mkdir(parents=True, exist_ok=True)
    allowed_top_level = {
        "adapter_model.safetensors", "adapter_config.json", "infer_adapter.py",
        "README.md", "training_config.json", "samples",
    }
    unexpected = [path.name for path in args.release_dir.iterdir() if path.name not in allowed_top_level]
    if unexpected:
        raise SystemExit(f"refusing to upload unexpected release files: {sorted(unexpected)}")
    for name in required:
        shutil.copy2(args.adapter / name, args.release_dir / name)
    shutil.copy2(args.inference_script, args.release_dir / "infer_adapter.py")
    (args.release_dir / "README.md").write_text(MODEL_CARD, encoding="utf-8")
    write_json(args.release_dir / "training_config.json", {
        "base_model": "ACE-Step/acestep-v15-xl-base",
        "lm_model_for_examples": "ACE-Step/acestep-5Hz-lm-4B",
        "adapter_type": "lora",
        "rank": 32,
        "alpha": 64,
        "dropout": 0.1,
        "epochs": 150,
        "devices": 2,
        "strategy": "ddp",
    })
    if args.samples_dir:
        samples_output = args.release_dir / "samples"
        if samples_output.exists():
            shutil.rmtree(samples_output)
        samples_output.mkdir(parents=True, exist_ok=True)
        for source in sorted(args.samples_dir.rglob("*.flac")):
            destination = samples_output / source.relative_to(args.samples_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    api = HfApi()
    api.create_repo(args.repo_id, repo_type="model", private=args.private, exist_ok=True)
    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="model",
        folder_path=str(args.release_dir),
        commit_message="Publish ACE-Step XL-Base LoRA adapter",
    )
    print(json.dumps({"repo_id": args.repo_id, "private": args.private, "release_dir": str(args.release_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
