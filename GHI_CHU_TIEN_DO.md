# Ghi chú tiến độ — Campaign Analyzer

> File này lưu lại quyết định quan trọng + trạng thái hiện tại, để không bị mất
> nếu extension Claude Code bị tắt/bật lại (chat cũ có thể mất, file này thì không).
> Cập nhật lần cuối: 2026-09-07.

## Đang ở đâu

**Chặng 2** trong roadmap gốc (brief): "Kéo số thật từ Adjust + đối chiếu".
Đã mở rộng ra thành bước "kéo dữ liệu lõi" đầy đủ hơn dự kiến ban đầu (CPI, ARPU,
ROAS D0/D7/D30, retention D1/D7) — vẫn CHƯA đụng tới Meta hay AdMob.

Script chính: `adjust_test.py` (cùng thư mục với file này).

## Dimensions + Metrics đã chốt

**Dimensions:**
```
app, day, campaign, country
```

**Metrics kéo trực tiếp từ Adjust Report Service API:**
```
installs, network_cost, network_ecpi, ad_revenue,
roas_ad_d0, roas_ad_d7, roas_ad_d30,
retention_rate_d1, retention_rate_d7
```

**Metrics tự tính thêm (Adjust không có sẵn):**
```
arpu_d0 = roas_ad_d0 × network_cost ÷ installs
arpu_d7 = roas_ad_d7 × network_cost ÷ installs
arpu_d30 = roas_ad_d30 × network_cost ÷ installs
```

## Các quyết định quan trọng + lý do

1. **Dùng `ad_revenue`, KHÔNG dùng `revenue`/`all_revenue`** — app test (AAP874-Face
   Warp Prank) đang tracking sai doanh thu IAP/tổng (ra số vô lý, ROAS >10,000%).
   `ad_revenue` (chỉ tính doanh thu ads) cho số hợp lý.
2. **Dùng `ad_revenue` (theo ngày phát sinh), không dùng `cohort_ad_revenue`** — để
   dễ đối chiếu/ghép với AdMob sau này (AdMob cũng báo cáo theo ngày phát sinh).
3. **CPI dùng `network_ecpi`** (theo yêu cầu) — nhưng LƯU Ý: mẫu số của
   `network_ecpi` là installs do **network** tự báo cáo, KHÁC với cột `installs`
   (Adjust attribute) đang hiển thị trong bảng. Không được nhân chéo 2 thứ này với
   nhau (đã từng tính sai ARPU vì lỗi này, đã sửa).
4. **ROAS/Retention theo mốc ngày dùng hậu tố `_dN`** (N = số ngày sau cài đặt,
   0-120; cũng có `_wN` theo tuần 0-52, `_mN` theo tháng 0-36). Đây KHÔNG phải tên
   biến, phải thay N bằng số cụ thể khi gọi API (`roas_ad_d0`, `roas_ad_d7`...).
   → Lúc đầu tra tài liệu online bị SAI (nói là không tồn tại), phải tự test trực
   tiếp lên API mới xác nhận đúng. Bài học: không tin danh mục liệt kê online là
   đầy đủ, luôn test trực tiếp.
5. **ARPU không có metric trực tiếp trên Adjust** (đã test: `arpu`, `arpu_ad`,
   `arpu_d0`, `cohort_ad_revenue_d0`... đều lỗi "Unsupported metric"). Tự suy ra
   bằng công thức ROAS × cost ÷ installs (xem trên).
6. **Bảng tổng theo app KHÔNG tự cộng dồn từ bảng chi tiết** — vì Adjust làm tròn
   4 chữ số thập phân mỗi dòng, cộng dồn hàng nghìn dòng nhỏ lẻ (day×campaign×
   country) gây sai số tích lũy ~3-4%. Giải pháp: gọi API riêng chỉ với
   `dimensions=app` để lấy đúng số Adjust tự tổng hợp.

## Vấn đề đã đóng

- ✅ **Installs lệch ~488 (đã tìm ra nguyên nhân, đã sửa — 07/09/2026):** do THIẾU
  tham số `utc_offset` trong mọi lệnh gọi API. Tài khoản Adjust của công ty set
  giờ Việt Nam (UTC+7), nhưng Adjust mặc định tính "ngày" theo giờ UTC nếu không
  truyền `utc_offset` → lệch 7 tiếng ở ranh giới mỗi ngày. Phát hiện ra nhờ test
  dữ liệu "hôm nay" (lúc chưa hết ngày, sai lệch rất rõ — 70%). Đã thêm
  `UTC_OFFSET = "+07:00"` vào `adjust_client.py`, áp dụng cho MỌI lệnh gọi. Sau
  khi sửa: installs 27,843 so với Datascape 27,826 — chênh chỉ còn 0.06% (trước
  đó chênh 1.8%). Coi như đã khớp.
  → Lưu ý: earlier có thử loại trừ timezone bằng cách so sánh local time vs UTC
  time tại 1 thời điểm cụ thể và kết luận "không lệch ngày" — kết luận đó ĐÚNG
  cho việc lệch NGÀY (calendar date), nhưng SAI ở chỗ bỏ qua việc Adjust vẫn cần
  tham số `utc_offset` để bucket đúng ranh giới giờ trong mỗi ngày. Bài học: kiểm
  tra tham số API đầy đủ trước khi loại trừ 1 giả thuyết.

## Vấn đề còn tồn đọng (chưa đóng)

- Còn 1 số cột mới (network_ecpi, roas_ad_dN, retention_rate_dN, arpu_dN) **chưa
  được đối chiếu với Datascape lần nào** — cần làm trước khi coi Chặng 2 là xong.

## Cách chạy

```
python adjust_test.py
```
Cần file `.env` (xem `.env.example`) với `ADJUST_API_TOKEN` và `ADJUST_APP_TOKENS`
đã điền token thật. Xem thêm `README.md`.

## Dashboard web (07/09/2026)

Đã quyết định + build xong bản đầu:
- **Phạm vi:** chỉ dữ liệu Adjust hiện có (không đợi AdMob/Meta/Bác sĩ chiến dịch).
  Bỏ tính năng xuất Excel khỏi bản đầu (user quyết định không cần).
- **Deploy:** Streamlit Community Cloud (user tự làm phần push GitHub + deploy).
- **Kiến trúc quan trọng:** `app.py` **TỰ GỌI Adjust API trực tiếp** mỗi khi có
  người mở (cache tạm 15 phút bằng `st.cache_data`), KHÔNG đọc từ
  `adjust_data.db`. Lý do: app chạy trên máy chủ Streamlit Cloud, không truy cập
  được file SQLite nằm trên máy cá nhân. → `adjust_pull_and_cache.py` +
  `adjust_data.db` vẫn giữ lại (dùng cho việc lưu lịch sử/phân tích sau), nhưng
  KHÔNG phải nguồn dữ liệu của dashboard web.
- File `app.py` dùng lại `adjust_client.py` (không viết lại logic gọi API).
- Token đọc qua `st.secrets` (khi deploy) hoặc `.env` (khi chạy local) — file mẫu
  ở `.streamlit/secrets.toml.example`.
- Đã sửa 1 deprecation warning của Streamlit (`use_container_width` → `width=`).
- Đã test chạy local (`streamlit run app.py`) — logic tính KPI (weighted_kpis)
  chạy đúng, không lỗi, số liệu hợp lý.
- **Việc user tự làm (Claude không làm được):** tạo/push code lên GitHub repo
  private, tạo app trên Streamlit Cloud, dán secrets vào Cloud.

## Việc dở dang / hỏi đang treo

- Chưa quyết định: dựng cache (SQLite) + lịch tự chạy hàng ngày, hay tiếp tục đối
  chiếu số trước.
- Chưa bắt đầu: Meta (phễu CPM/CTR/CVR/frequency) và AdMob (eCPM) — cần bạn tự làm
  thủ tục thủ công trước (Meta: xin quyền Marketing API, System User token; AdMob:
  tạo Google Cloud project, bật AdMob API, OAuth).
