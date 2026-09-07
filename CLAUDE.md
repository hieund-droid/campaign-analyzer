# CLAUDE.md — Campaign Analyzer (đọc TRƯỚC khi làm bất cứ gì trong project này)

> File này Claude Code TỰ ĐỘNG đọc mỗi khi mở session mới tại thư mục này —
> kể cả người khác mở, hoặc session bị mất do tắt/bật lại extension.
> Mục đích: KHÔNG bắt đầu lại từ đầu, không hỏi lại những gì đã chốt.

## QUY TẮC BẮT BUỘC CHO CLAUDE

1. **Đọc `GHI_CHU_TIEN_DO.md`** (cùng thư mục) NGAY khi bắt đầu session — đó là
   nhật ký chi tiết: đã làm gì, quyết định gì + vì sao, còn vướng gì.
2. **Sau khi hoàn thành 1 việc lớn / chốt 1 quyết định quan trọng / phát hiện lỗi
   cần sửa** → PHẢI cập nhật `GHI_CHU_TIEN_DO.md` ngay trong lúc làm, KHÔNG đợi
   user nhắc "lưu lại nhé". Việc lớn = thêm/đổi metric, sửa công thức tính, phát
   hiện+xử lý discrepancy, chuyển sang chặng mới trong roadmap.
3. **Không tự ý làm lại việc đã xong** — nếu `GHI_CHU_TIEN_DO.md` nói 1 việc đã
   chốt (VD: dùng `ad_revenue` không dùng `revenue`), đừng hỏi lại hay đổi lại
   trừ khi user yêu cầu rõ ràng.
4. **Không đưa API token / secret vào file này hay `GHI_CHU_TIEN_DO.md`** — chỉ
   nói TÊN biến môi trường cần có (`ADJUST_API_TOKEN`, `ADJUST_APP_TOKENS`), không
   bao giờ ghi giá trị thật. Người dùng mới phải tự điền `.env` (xem `.env.example`).
5. Toàn bộ luật ở CLAUDE.md gốc (global, không nằm trong repo này) vẫn áp dụng:
   trả lời tiếng Việt, không đoán số, hỏi trước khi làm việc lớn, v.v.

## Trạng thái nhanh (xem chi tiết ở GHI_CHU_TIEN_DO.md)

- Đang ở: Chặng 2 mở rộng (kéo "dữ liệu lõi" Adjust) + đã build dashboard web
  (`app.py`, Streamlit) song song — chưa đụng Meta/AdMob.
- File chính: `adjust_client.py` (dùng chung), `adjust_test.py` (xem tay),
  `adjust_pull_and_cache.py` (chạy nền, lưu SQLite `adjust_data.db`), `app.py`
  (dashboard web — TỰ GỌI Adjust API, không đọc từ `adjust_data.db`, xem lý do ở
  GHI_CHU_TIEN_DO.md mục "Dashboard web").
- Cần có `.env` (copy từ `.env.example`) với `ADJUST_API_TOKEN` + `ADJUST_APP_TOKENS`
  — người dùng mới PHẢI tự điền, Claude không tự tạo được token.
- Vấn đề installs lệch đã ĐÓNG (07/09/2026) — do thiếu `utc_offset=+07:00`, đã sửa.
- Còn treo: user tự làm phần push GitHub + deploy Streamlit Cloud + dán secrets
  (Claude không làm được); chưa dựng xong lịch tự chạy Task Scheduler cho
  `adjust_pull_and_cache.py` (đang hỏi user máy có hay tắt hẳn không); chưa đối
  chiếu Datascape cho các cột mới (network_ecpi, roas_ad_dN, retention_rate_dN,
  arpu_dN).

## Việc tiếp theo có thể làm (hỏi user trước khi chọn)

- Đối chiếu các cột mới (network_ecpi, roas_ad_dN, retention_rate_dN, arpu_dN) với
  Datascape — CHƯA làm.
- Dựng cache (SQLite) + lịch tự chạy hàng ngày — đang chờ quyết định.
- Bắt đầu Meta / AdMob — cần user tự làm thủ tục thủ công trước (xem
  GHI_CHU_TIEN_DO.md mục cuối).
