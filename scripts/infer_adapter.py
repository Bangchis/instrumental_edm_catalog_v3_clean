#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from music_pipeline.common import write_json


def worker(args: argparse.Namespace) -> int:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.device)
    os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(args.checkpoints.resolve())

    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    output = args.output / f"gpu{args.device}_seed{args.seed}"
    output.mkdir(parents=True, exist_ok=True)
    dit_handler = AceStepHandler()
    status, ok = dit_handler.initialize_service(
        project_root=str(args.acestep_root),
        config_path="acestep-v15-xl-base",
        device="cuda",
        use_flash_attention=False,
        compile_model=False,
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        quantization=None,
    )
    if not ok:
        raise RuntimeError(f"DiT initialization failed: {status}")

    lora_status = dit_handler.load_lora(str(args.adapter.resolve()))
    if not lora_status.startswith("✅"):
        raise RuntimeError(lora_status)

    llm_handler = LLMHandler()
    lm_status, lm_ok = llm_handler.initialize(
        checkpoint_dir=str(args.lm_root.resolve()),
        lm_model_path="acestep-5Hz-lm-4B",
        backend=args.lm_backend,
        device="cuda",
        offload_to_cpu=False,
    )
    if not lm_ok:
        raise RuntimeError(f"LM initialization failed: {lm_status}")

    params = GenerationParams(
        task_type="text2music",
        caption=args.caption,
        lyrics="[Instrumental]",
        instrumental=True,
        vocal_language="unknown",
        bpm=args.bpm,
        keyscale=args.keyscale,
        timesignature=args.timesignature,
        duration=args.duration,
        inference_steps=args.inference_steps,
        seed=args.seed,
        guidance_scale=args.guidance_scale,
        shift=1.0,
        infer_method="ode",
        thinking=True,
        use_cot_metas=False,
        use_cot_caption=False,
        use_cot_lyrics=False,
        use_cot_language=False,
    )
    config = GenerationConfig(
        batch_size=1,
        allow_lm_batch=False,
        use_random_seed=False,
        seeds=[args.seed],
        audio_format="flac",
    )
    result = generate_music(dit_handler, llm_handler, params, config, save_dir=str(output))
    payload: dict[str, Any] = result.to_dict()
    payload.update({
        "physical_gpu": args.device,
        "seed": args.seed,
        "adapter": str(args.adapter),
        "base_model": "ACE-Step/acestep-v15-xl-base",
        "lm_model": "ACE-Step/acestep-5Hz-lm-4B",
    })
    write_json(output / "inference_result.json", payload)
    if not result.success or not result.audios:
        raise RuntimeError(result.error or "inference produced no audio")
    print(json.dumps({"gpu": args.device, "seed": args.seed, "audios": result.audios}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate two ACE-Step LoRA candidates in parallel on two GPUs.")
    parser.add_argument("--acestep-root", type=Path, default=Path("/workspace/ACE-Step-1.5"))
    parser.add_argument("--checkpoints", type=Path, default=Path("/workspace/instrumental_edm_catalog_v3_clean/checkpoints"))
    parser.add_argument("--lm-root", type=Path, default=Path("/dev/shm/acestep-lm"))
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/inference"))
    parser.add_argument("--caption", required=True)
    parser.add_argument("--bpm", type=int, required=True)
    parser.add_argument("--keyscale", required=True)
    parser.add_argument("--timesignature", default="4")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--inference-steps", type=int, default=64)
    parser.add_argument("--guidance-scale", type=float, default=7.0)
    parser.add_argument("--seeds", type=int, nargs=2, default=[20260717, 20260718])
    parser.add_argument("--lm-backend", choices=["pt", "vllm"], default="pt")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--device", type=int)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    if args.worker:
        if args.device is None or args.seed is None:
            parser.error("--worker requires --device and --seed")
        return worker(args)

    args.output.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[str]] = []
    for device, seed in enumerate(args.seeds):
        command = [
            sys.executable, str(Path(__file__).resolve()),
            "--worker", "--device", str(device), "--seed", str(seed),
            "--acestep-root", str(args.acestep_root),
            "--checkpoints", str(args.checkpoints),
            "--lm-root", str(args.lm_root),
            "--adapter", str(args.adapter),
            "--output", str(args.output),
            "--caption", args.caption,
            "--bpm", str(args.bpm),
            "--keyscale", args.keyscale,
            "--timesignature", args.timesignature,
            "--duration", str(args.duration),
            "--inference-steps", str(args.inference_steps),
            "--guidance-scale", str(args.guidance_scale),
            "--lm-backend", args.lm_backend,
        ]
        processes.append(subprocess.Popen(command, text=True))
    return_codes = [process.wait() for process in processes]
    summary = {"return_codes": return_codes, "ok": all(code == 0 for code in return_codes)}
    write_json(args.output / "parallel_inference_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
