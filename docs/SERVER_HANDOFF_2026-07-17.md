# Bàn giao khẩn cấp Vast — 2026-07-17

Tài liệu này ghi lại trạng thái chính xác lúc dừng Vast server để có thể tiếp tục
trên một server mới mà không phải làm lại từ đầu.

## Nơi đã lưu

- Code public: <https://github.com/Bangchis/instrumental_edm_catalog_v3_clean>
- Commit bàn giao code: `f4c055a19aa00f3b9535e9fac5d89ec3bdbc8d4d`
- Checkpoint metadata public: <https://huggingface.co/datasets/Bangchis/instrumental-edm-catalog-v3-checkpoint>

Checkpoint Hugging Face chứa hai manifest đang chạy dở, thông tin môi trường và
checksum. Không có API key, token, cookie, Codex session, audio nguồn hoặc tensor
cache trong gói này.

## Trạng thái lúc dừng

Tất cả tiến trình đã dừng. `edm-download`, `edm-prepare`, `edm-models`,
`edm-preprocess`, `edm-train-smoke`, `edm-train-full`, `edm-infer` và
`edm-publish` chưa từng được khởi động.

Manifest có đủ 240 dòng:

| Trạng thái | Số dòng |
|---|---:|
| `resolved` | 201 |
| `errors` | 5 |
| `low_score` | 5 |
| `no_candidates` | 29 |

Chưa tải audio thật. Trên server chỉ có vài tone/MP3 synthetic dùng smoke test;
chúng không thuộc dataset và không được upload. Chưa tải model weight ACE-Step,
chưa preprocess, chưa train LoRA, chưa infer và chưa publish adapter.

## Đã làm xong

- Repository GitHub đã public và toàn bộ code/config đã push lên `main`.
- Vast đã cài ACE-Step 1.5 tại commit pin, Python environment và dependency cần
  cho yt-dlp, Demucs, faster-whisper, MIR, OpenRouter, ACE-Step và 2-GPU DDP.
- CUDA nhận đủ 2×RTX 4090; smoke test Demucs/Whisper dùng được cả hai GPU.
- OpenRouter đã test thành công với `google/gemini-3.1-flash-lite`, audio input và
  strict JSON schema.
- Hugging Face auth đã test thành công trên server cũ.
- Pipeline đã có guard: bỏ qua `liked`, audit đủ 240 dòng trước download, kiểm tra
  file audio thực, full-track SHA/Chromaprint dedupe, vocal/MIR/annotation,
  dataset validation, 2-GPU preprocess/DDP train, infer và publish có allowlist.
- Bộ hydrate đã được sửa để giữ token Unicode. Lỗi từng coi `CHINA-团圆` giống
  `CHINA-新春` đã có regression test; 16/16 test qua trên local và Vast.
- Các match sai đã được sửa bằng `catalog/hydration_overrides.csv`, gồm cả
  `CHINA-团圆`, `CHINA-韵`, `CHINA-花灯`, `China-A`, `China-C`, `China-L` và
  các bản remix/instrumental đã duyệt trước đó.

## Vì sao còn 39 dòng chưa resolved

Bốn video YUAN chính thức vẫn hiện trong search nhưng direct page báo
`This video is not available`:

- `xu_mengyuan:015` — `China-L` — `z90U94tWceU`
- `xu_mengyuan:022` — `CHINA-妄念` — `N8dfwoJDgwU`
- `xu_mengyuan:023` — `CHINA-山花` — `QwpsHKLWIvI`
- `xu_mengyuan:024` — `CHINA-自在` — `btZZ5Af54Ic`

Năm dòng MyoMouse cần duyệt tay vì candidate không đủ chắc:

- `myomouse:002` — `Viet Nam`
- `myomouse:007` — `Blood and Tears`; candidate `0Qn4UKn5QyQ` là đúng bản
  `MÁU VÀ NƯỚC MẮT (Blood & Tears)` và có thể thêm override sau khi kiểm tra lại.
- `myomouse:008` — `Hoạ Cảnh`
- `myomouse:009` — `Nhân Gian Xuân Ý`
- `myomouse:010` — `Maiden`

`myomouse:012` lỗi do SOCKS proxy mất kết nối. Từ đoạn đó trở đi có 29
`no_candidates`, bao gồm cả 10 dòng rank 31–40 vốn đã có video ID; đây chủ yếu là
lỗi đường truyền lúc server bị dừng, không phải bằng chứng video không tồn tại.

## Tiếp tục trên Vast server mới

Mọi lệnh cài package, tải audio/model và workload phải chạy trên Vast, không chạy
trên máy local.

1. Clone code và checkout `main`:

   ```bash
   cd /workspace
   git clone https://github.com/Bangchis/instrumental_edm_catalog_v3_clean.git
   cd instrumental_edm_catalog_v3_clean
   ```

2. Chạy setup server theo `RUNBOOK.md`/`configs/setup_server.sh`, rồi cấp lại
   OpenRouter và Hugging Face token bằng file mode `600`. Không commit token.

3. Tải checkpoint trực tiếp trên server mới:

   ```bash
   hf download Bangchis/instrumental-edm-catalog-v3-checkpoint \
     --repo-type dataset \
     --local-dir /workspace/edm-checkpoint
   mkdir -p data/manifests
   cp /workspace/edm-checkpoint/manifests/*.csv data/manifests/
   ```

4. Tạo lại SOCKS/SSH route tới YouTube, xác nhận `curl` và một truy vấn `yt-dlp`
   đi qua proxy thành công. Sau đó chạy hydrate với `--resume`; đừng chạy nhiều
   worker cùng lúc.

5. Duyệt và thêm exact public alternatives cho bốn video YUAN unavailable cùng
   các dòng MyoMouse còn thiếu. Chạy lại tới khi audit báo đủ `240/240 resolved`:

   ```bash
   python scripts/audit_hydration.py \
     --seed catalog/selection.csv \
     --hydrated data/manifests/selection_hydrated.csv \
     --overrides catalog/hydration_overrides.csv \
     --report data/manifests/hydration_audit.json \
     --expected-rows 240
   ```

6. Chỉ sau khi audit `ok: true`: chạy lần lượt `edm-download`, `edm-prepare`,
   `edm-models`, `edm-preprocess`, `edm-train-smoke`, kiểm tra OOM/NaN và hai GPU,
   rồi `edm-train-full`, `edm-infer`, `edm-publish`.

## Những thứ phải cấp lại, không nằm trong checkpoint

- OpenRouter API key.
- Hugging Face token.
- Codex/ChatGPT login trên server mới.
- SSH reverse SOCKS route từ máy local.
- ACE-Step virtualenv và model cache; tất cả đều tái tạo được bằng script/runbook.

