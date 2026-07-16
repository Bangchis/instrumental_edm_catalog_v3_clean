# Hướng dẫn từng file — Instrumental EDM Catalog v3

## 1. Tóm tắt

Bản v3 có 240 dòng ứng viên lõi, tương ứng 40 dòng cho mỗi nguồn:

```text
Xomu
TheFatRat
Diversity
StarlingEDM
徐梦圆 YUAN
MyoMouse
```

Toàn bộ `liked` và `notes` đang trống. `Xomu - Last Dance (IELY Remix)` được giữ riêng trong Diversity. Danh sách là seed ứng viên 40 bài; cần hydrate live trước khi coi rank là thứ tự view hiện tại.

## 2. Cây thư mục

```text
instrumental_edm_catalog_v3_clean/
├── README.md
├── RUNBOOK.md
├── pyproject.toml
├── requirements.txt
├── musiccrawl.py
├── instrumental_edm_catalog_v3_clean.xlsx
├── config/
│   └── sources.csv
├── catalog/
│   ├── selection.csv
│   ├── selection.ndjson
│   ├── source_summary.csv
│   ├── validation_report.json
│   └── playlist_first37_status.csv
├── docs/
│   ├── FILE_GUIDE.md
│   └── FILE_GUIDE.docx
├── raw/
├── state/
└── logs/
```

## 3. Các file người dùng thao tác

### `catalog/selection.csv`

File chính để nghe và đánh giá gu. Có đúng 240 dòng lõi.

Chỉ chỉnh:

```text
liked
notes
```

Các cột quan trọng:

- `record_key`: khóa nội bộ ổn định theo `source_id:rank`.
- `source_id`, `source_rank`: nguồn và thứ hạng 1–40.
- `video_id`, `webpage_url`: định danh YouTube; trống nghĩa là chưa hydrate.
- `title_raw`, `channel_name`: tên bài và nghệ sĩ/uploader dự kiến.
- `ranking_basis`: dòng đến từ seed cũ, phần mở rộng nghiên cứu hay user pin.
- `rank_confidence`: mức tin cậy của rank hiện tại.
- `metadata_status`: nói rõ dữ liệu nào còn thiếu.
- `user_pinned`: `1` nếu bài được người dùng yêu cầu rõ ràng.
- `duplicate_audio_review`: đánh dấu phiên bản cần fingerprint-review sau download.
- `liked`: trống/1/0.
- `notes`: ghi chú tự do.
- `source_url`, `evidence_url`: nguồn khám phá và bằng chứng cho dòng.

### `instrumental_edm_catalog_v3_clean.xlsx`

Giao diện Excel của seed, gồm:

- `Summary`: số lượng, mức hoàn thiện metadata và chính sách.
- `Selection`: toàn bộ 240 dòng; có dropdown cho `liked`.
- `Sources`: cấu hình nguồn.
- `Playlist Status`: trạng thái playlist 37 bài.
- `File Map`: bản đồ file.

Chỉ sửa `liked` và `notes` trong sheet `Selection`.

### `config/sources.csv`

Cấu hình discovery:

- sáu nguồn lõi có `target_count=40` và `ranking_mode=popular`;
- playlist có `target_count=37` và `ranking_mode=source_order`;
- `candidate_pool` là số ứng viên tối đa cần hydrate trước khi chọn top.

Chỉ sửa khi thêm, tắt hoặc thay URL nguồn.

## 4. Các file mô tả và kiểm tra

### `catalog/selection.ndjson`

Bản machine-readable của `selection.csv`. Không chỉnh tay; sinh lại khi CSV thay đổi nếu cần.

### `catalog/source_summary.csv`

Tổng hợp theo nguồn:

```text
target_count
actual_count
rank_min/rank_max
known_video_ids
unresolved_video_ids
user_pinned_count
ratings_completed
```

### `catalog/validation_report.json`

Kết quả validator: xác nhận mỗi nguồn đủ 40 dòng, rank liên tục và `liked` hợp lệ.

### `catalog/playlist_first37_status.csv`

Ghi trạng thái playlist 37 bài. Hiện là `PENDING_LIVE_ENUMERATION`; file không bịa video ID.

## 5. Code và cấu hình dự án

### `musiccrawl.py`

CLI chính, có các lệnh:

```text
inventory
export-selection
select
download
audit-duplicates
validate
```

Lệnh `select` bỏ qua bài `liked=1` chưa có URL và ghi chúng vào `unresolved_liked.csv`.

### `pyproject.toml`

Khai báo package Python và entry point `musiccrawl`.

### `requirements.txt`

Danh sách dependency tối thiểu.

## 6. File sinh trong lúc chạy

### `catalog/catalog.ndjson`

Source of truth cho metadata sau live crawl. Chứa video ID, URL, duration, upload date, view/like count, channel và `source_refs`.

### `catalog/live_review_queue.csv`

File xuất từ catalog live để review/merge. Không ghi đè seed đã chấm một cách mù quáng.

### `catalog/selected_urls.txt`

Chỉ chứa URL của dòng `liked=1` đã có định danh YouTube.

### `catalog/unresolved_liked.csv`

Các dòng đã thích nhưng còn thiếu `video_id`/URL. Phải hydrate trước khi download.

### `catalog/duplicate_audit.csv`

Kết quả SHA/fingerprint sau download. Chỉ dùng để review.

### `raw/<video_id>/`

Audio và sidecar của yt-dlp.

### `state/source_state.json`

Trạng thái crawl từng nguồn, bao gồm số item đã lấy và lỗi nếu có.

### `state/downloaded_ids.txt`

Archive của yt-dlp để không tải trùng khi chạy lại.

### `logs/`

Log chạy và lỗi.

## 7. Quy tắc duplicate và phiên bản

- Cùng `video_id`: gộp provenance vào `source_refs`.
- Khác `video_id`: giữ riêng, kể cả tên giống nhau.
- Remix, edit, live, alternate upload hoặc thay nhạc cụ đều có thể là ứng viên hợp lệ.
- Sau download mới so sánh file hash, decoded PCM hash và Chromaprint.
- Không tự động xóa chỉ vì title giống hoặc fingerprint match; đưa vào review.

## 8. Thứ tự source of truth

```text
Trước live crawl:
catalog/selection.csv = source of truth cho lựa chọn theo gu

Sau live crawl:
catalog/catalog.ndjson = source of truth cho metadata

Mọi thời điểm:
liked và notes trong selection.csv = source of truth cho sở thích

Sau preprocess:
manifest QC riêng = source of truth cho chất lượng instrumental/training-ready
```

## 9. Hạn chế hiện tại

- 240 dòng đã đủ 40 ứng viên mỗi nguồn, nhưng không phải toàn bộ rank được xác nhận bằng view count live.
- Chỉ khoảng 10 dòng mỗi nguồn hiện có video ID trực tiếp; các dòng còn lại cần hydrate.
- Playlist 37 bài chưa được enumerate do môi trường tạo bundle không truy cập YouTube ổn định.
- Không nên download các dòng chưa có video ID/URL.
