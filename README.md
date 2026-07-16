# Instrumental EDM Catalog v3 — bản làm lại sạch

Đây là bản thay thế hoàn toàn cho các bundle cũ bị lẫn giữa seed Top 30 và mục tiêu Top 40. Bản v3 không chứa file legacy hay migration seed.

## Trạng thái thực tế

- `catalog/selection.csv` có **240 dòng lõi**: 40 ứng viên cho mỗi nguồn Xomu, TheFatRat, Diversity, StarlingEDM, 徐梦圆 YUAN và MyoMouse.
- Mỗi nguồn có `source_rank` liên tục từ `1` đến `40`.
- Toàn bộ `liked` và `notes` đang để trống.
- `Xomu - Last Dance (IELY Remix)` được giữ riêng dưới nguồn Diversity với video ID `YOcwtc9Jpls`.
- Mười video YUAN do người dùng chỉ định nằm ở rank 31–40 của `xu_mengyuan`; `CHINA-冬雪` chỉ xuất hiện một lần.

## Cảnh báo về “Top 40”

Danh sách hiện tại là **popular-candidate seed 40 bài**, chưa phải tuyên bố rằng thứ tự 1–40 khớp tuyệt đối với view YouTube tại thời điểm hiện tại.

- Rank 1–30 kế thừa seed cũ.
- Rank 31–40 là phần mở rộng có URL/bằng chứng.
- Nhiều dòng rank 1–30 mới có tên bài, chưa có `video_id`.
- Muốn có thứ tự phổ biến chính xác phải chạy `musiccrawl inventory` trên máy truy cập YouTube bình thường để hydrate `view_count` và metadata.

## Playlist 37 bài

Playlist `PLdzH6pYmEFNNi6LB6EZF5Y07rXm3q7rjC` đã được cấu hình với `target_count=37` và giữ nguyên thứ tự playlist. Môi trường tạo bundle không enumerate được YouTube nên 37 dòng này **chưa được bịa thêm vào seed**. Chạy inventory trên máy cá nhân để materialize chúng.

## Bắt đầu

```bash
python -m pip install -e .

musiccrawl validate \
  --selection catalog/selection.csv
```

Sau đó chỉ sửa hai cột trong `catalog/selection.csv` hoặc sheet `Selection` của Excel:

```text
liked trống = chưa nghe/chưa đánh giá
liked = 1   = thích, muốn giữ
liked = 0   = không dùng
notes       = ghi chú tùy chọn
```

Xuất URL của các bài đã thích:

```bash
musiccrawl select \
  --selection catalog/selection.csv \
  --output catalog/selected_urls.txt
```

Bài `liked=1` nhưng chưa có URL sẽ được ghi vào `catalog/unresolved_liked.csv`, không tạo URL YouTube rỗng.

Đọc `RUNBOOK.md` để chạy pipeline và `docs/FILE_GUIDE.md` hoặc `docs/FILE_GUIDE.docx` để hiểu từng file.
