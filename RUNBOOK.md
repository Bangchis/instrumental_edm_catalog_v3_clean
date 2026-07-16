# RUNBOOK — Instrumental EDM Catalog v3

## 1. Cài đặt

```bash
cd instrumental_edm_catalog_v3_clean
python -m pip install -e .
```

Yêu cầu chính:

```text
Python >= 3.11
yt-dlp
ffmpeg             # cần khi download/audit decoded PCM
fpcalc/Chromaprint # tùy chọn, dùng cho perceptual fingerprint
```

## 2. Kiểm tra seed

```bash
musiccrawl validate \
  --selection catalog/selection.csv
```

Kết quả hợp lệ phải có sáu nguồn, mỗi nguồn 40 dòng và rank 1–40 liên tục. `rated=0` là đúng ở trạng thái ban đầu.

## 3. Đánh giá gu nhạc

Chỉnh trực tiếp:

```text
catalog/selection.csv
```

hoặc sheet `Selection` trong:

```text
instrumental_edm_catalog_v3_clean.xlsx
```

Chỉ sửa:

```text
liked
notes
```

Không dùng `liked` để biểu diễn “không lời” hay chất lượng audio. Đó là nhãn sở thích.

## 4. Xuất URL đã chọn

```bash
musiccrawl select \
  --selection catalog/selection.csv \
  --output catalog/selected_urls.txt \
  --unresolved-output catalog/unresolved_liked.csv
```

Kết quả:

```text
catalog/selected_urls.txt  # liked=1 và đã có video_id/URL
catalog/unresolved_liked.csv # liked=1 nhưng metadata chưa được hydrate
```

CLI không tạo URL dạng `https://www.youtube.com/watch?v=` khi `video_id` còn trống.

## 5. Crawl metadata live và nhập playlist 37 bài

Chạy trên máy có truy cập YouTube bình thường:

```bash
musiccrawl inventory \
  --sources config/sources.csv \
  --output catalog/catalog.ndjson \
  --state state/source_state.json
```

Lệnh này:

- lấy tối đa 40 video cho mỗi nguồn lõi;
- hydrate metadata đầy đủ;
- với nguồn `ranking_mode=popular`, sắp xếp theo `view_count`, rồi `like_count`, rồi `upload_date`;
- với playlist 37 bài, giữ nguyên `source_index` của playlist;
- chỉ gộp khi cùng `video_id`;
- giữ nhiều `source_refs` nếu một video được phát hiện từ nhiều nguồn.

Kiểm tra `state/source_state.json`. Mỗi nguồn lõi nên có `items_selected=40`; playlist nên có `items_selected=37`.

## 6. Xuất hàng đợi metadata live

Không ghi đè ngay lên seed đã chấm. Xuất riêng:

```bash
musiccrawl export-selection \
  --catalog catalog/catalog.ndjson \
  --output catalog/live_review_queue.csv
```

Sau đó merge với `catalog/selection.csv` theo quy tắc:

1. Cùng `video_id`: cập nhật metadata và giữ nguyên `liked`, `notes`.
2. Khác `video_id`: giữ thành dòng riêng, kể cả tên giống nhau.
3. Dòng seed chưa có `video_id`: chỉ ghép khi đã xác minh chắc chắn bằng title + uploader hoặc thủ công.
4. Không tự động xóa remix, live edit hay alternate arrangement.

## 7. Download audio

Sau khi đã xử lý `unresolved_liked.csv`:

```bash
musiccrawl download \
  --urls catalog/selected_urls.txt \
  --output raw/ \
  --archive state/downloaded_ids.txt
```

Mỗi video được lưu trong:

```text
raw/<video_id>/
├── audio.<ext>
├── audio.info.json
├── audio.description
└── audio.<thumbnail_ext>
```

## 8. Audit duplicate sau download

```bash
musiccrawl audit-duplicates \
  --input raw/ \
  --output catalog/duplicate_audit.csv
```

Audit dùng ba tầng:

```text
file SHA-256
SHA-256 của PCM đã decode
Chromaprint
```

Kết quả chỉ là hàng đợi review. Không tự động xóa file.

## 9. Preprocess instrumental

Chỉ thực hiện sau khi đã chọn bài:

```text
raw audio
→ ưu tiên official instrumental/off-vocal
→ nếu cần thì source separation
→ residual-vocal QC + ASR + nghe spot-check
→ canonical FLAC
→ segmentation
→ annotation
→ training manifest
```

Bài có vocal không nên bị loại ở bước taste nếu mày thích arrangement; có thể xử lý ở giai đoạn audio QC.

## 10. File cần backup

Quan trọng nhất:

```text
catalog/selection.csv
catalog/catalog.ndjson
state/downloaded_ids.txt
state/source_state.json
raw/
```
