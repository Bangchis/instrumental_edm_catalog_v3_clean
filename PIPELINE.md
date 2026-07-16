# Pipeline 240 bài → ACE-Step LoRA

Pipeline này cố xử lý toàn bộ 240 dòng lõi và không dùng cột `liked` để lọc.
Mọi audio, model, cache và dependency runtime được tạo trên Vast tại `/workspace`.

## Thư mục runtime

```text
/workspace/instrumental_edm_catalog_v3_clean/
├── data/raw
├── data/canonical
├── data/separated
├── data/training_sources
├── data/mir
├── data/annotations
├── data/final_dataset
├── data/tensors
├── checkpoints
└── outputs
```

`/workspace` của instance hiện tại không có volume. Stop/Start giữ dữ liệu, nhưng
Recycle/Destroy sẽ xóa dữ liệu. Phải đẩy code/checkpoint cần giữ ra GitHub hoặc
Hugging Face trước khi hủy instance.

## 1. Cài dependency trên Vast

```bash
cd /workspace/instrumental_edm_catalog_v3_clean
bash configs/setup_server.sh
source /workspace/ACE-Step-1.5/.venv/bin/activate
```

Script có chốt Linux + `/workspace`, vì vậy không thể vô tình cài model/dependency
lên Mac. ACE-Step được khóa tại commit
`6d467e4b5081ccb0abf1ec1bf4fdf9051a2d34b0`.

Secret chỉ đặt trong `/workspace/.env` với quyền `600`, không đặt trong repo.

## 2. Hydrate và tải tất cả

```bash
python musiccrawl.py hydrate-selection \
  --selection catalog/selection.csv \
  --output data/manifests/selection_hydrated.csv \
  --unresolved data/manifests/hydration_unresolved.csv

python musiccrawl.py export-all \
  --selection data/manifests/selection_hydrated.csv \
  --output data/manifests/all_resolved_urls.txt \
  --unresolved data/manifests/download_unresolved.csv

python musiccrawl.py download \
  --selection data/manifests/selection_hydrated.csv \
  --output data/raw \
  --archive data/state/downloaded_ids.txt \
  --manifest data/manifests/downloads.jsonl
```

`export-all` và `download --selection` bỏ qua hoàn toàn `liked`.

## 3. Chuẩn hóa, fingerprint và xử lý vocal

```bash
python -m scripts.canonicalize \
  --raw-root data/raw --output data/canonical \
  --manifest data/manifests/canonical.jsonl

python -m scripts.fingerprint \
  --input data/canonical \
  --unique-manifest data/manifests/unique_tracks.jsonl \
  --duplicates-manifest data/manifests/duplicates.jsonl

# fpcalc chạy toàn bộ bài (-length 0), không chỉ 120 giây mặc định.
# SHA-256 hoặc full-track Chromaprint giống hệt sẽ bị loại khỏi manifest train;
# audio nguồn không bị xóa và remix có fingerprint khác vẫn được giữ riêng.

python -m scripts.process_vocals \
  --input data/canonical --output data/separated \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --state-dir data/state/vocals --devices 0,1

python -m scripts.select_training_audio \
  --canonical-dir data/canonical \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --unique-manifest data/manifests/unique_tracks.jsonl \
  --output data/training_sources \
  --manifest data/manifests/training_sources.jsonl
```

Nếu Whisper phát hiện câu chữ rõ, pipeline chỉ giữ stem instrumental đã qua
kiểm tra duration/loudness. Nếu không, pipeline giữ mix gốc để không xóa vocal
chop dùng như nhạc cụ. Vocal stem luôn là file tạm; cách này tránh giữ 2 stem
cho cả 240 bài trên ổ 32 GB.

## 4. MIR và OpenRouter annotation

```bash
python -m scripts.analyze_mir \
  --input data/training_sources --output data/mir \
  --manifest data/manifests/mir.jsonl

python -m scripts.annotate_openrouter \
  --audio-dir data/training_sources --mir-dir data/mir \
  --output data/annotations \
  --audio-cache data/annotation_mp3 \
  --manifest data/manifests/annotations.jsonl \
  --model google/gemini-3.1-flash-lite
```

Audio annotation là MP3 192 kbps tối đa 240 giây; FLAC vẫn là nguồn training.
OpenRouter nhận audio base64 và trả JSON theo `configs/annotation_schema.json`.

## 5. Dataset và validation

```bash
python -m scripts.build_acestep_dataset \
  --canonical-dir data/training_sources \
  --separation-manifest data/manifests/separation.jsonl \
  --lyrics-manifest data/manifests/lyrics.jsonl \
  --mir-dir data/mir --annotation-dir data/annotations \
  --output data/final_dataset \
  --manifest data/final_dataset/manifest.jsonl

python -m scripts.validate_dataset \
  --dataset data/final_dataset \
  --report data/final_dataset/validation_report.json
```

Builder tạo cả sidecar từng bài và `data/final_dataset/dataset.json` để CLI
ACE-Step thật sự đọc caption/BPM/key. Chỉ chuyển sang training khi report có
`ok: true`.

## 6. ACE-Step XL-Base, 2×4090

```bash
bash configs/download_acestep_models.sh

PROJECT_ROOT=$PWD ACESTEP_ROOT=/workspace/ACE-Step-1.5 \
  bash configs/preprocess_2x4090.sh

PROJECT_ROOT=$PWD ACESTEP_ROOT=/workspace/ACE-Step-1.5 \
  bash configs/train_smoke_2x4090.sh

PROJECT_ROOT=$PWD ACESTEP_ROOT=/workspace/ACE-Step-1.5 \
  bash configs/train_2x4090.sh
```

Downloader chỉ giữ VAE + text encoder dùng chung trên disk. XL-Base gần 20 GB
được stage ở `/dev/shm/acestep-models` rồi symlink vào `checkpoints`, vì disk
instance chỉ 32 GB. `/dev/shm` mất khi Stop/Restart nên phải chạy lại downloader
trước preprocess/train nếu instance đã restart.

Smoke test phải chứng minh cả hai GPU hoạt động, không OOM/NaN và có adapter
checkpoint trước khi chạy 150 epoch.

## 7. Infer hai candidate và publish adapter

Disk instance chỉ có 32 GB, trong khi XL-Base trên Hub gần 20 GB và LM 4B hơn
8 GB. Vì vậy LM inference được tải vào RAM `/dev/shm`, không nhân đôi trên disk:

```bash
bash configs/download_inference_lm_to_ram.sh

python -m scripts.infer_adapter \
  --adapter outputs/melodic_edm_core_v1/final \
  --caption "melodic instrumental EDM with a memorable lead, wide synths and a powerful clean drop" \
  --bpm 128 --keyscale "F# minor" --timesignature 4 --duration 60

python -m scripts.publish_adapter \
  --adapter outputs/melodic_edm_core_v1/final \
  --samples-dir outputs/inference \
  --repo-id Bangchis/melodic-edm-core-ace-step-lora
```

Inference chạy hai process song song, mỗi GPU một candidate, cùng prompt và
metadata nhưng khác seed. Publisher chỉ đưa adapter, config, code và audio sinh
ra lên Hugging Face; không đưa audio nguồn, secret hoặc tensor cache.
