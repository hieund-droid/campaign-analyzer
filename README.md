# Campaign Analyzer

Đọc `CLAUDE.md` và `GHI_CHU_TIEN_DO.md` trước — 2 file đó ghi trạng thái/quyết định
mới nhất. File này chỉ hướng dẫn cách chạy.

## Các file chính

| File | Vai trò |
|---|---|
| `adjust_client.py` | Cấu hình + hàm gọi Adjust Report Service API (dùng chung) |
| `adjust_test.py` | Chạy tay, in bảng ra màn hình để xem/đối chiếu Datascape |
| `adjust_pull_and_cache.py` | Chạy nền (Task Scheduler), lưu vào `adjust_data.db` (SQLite) |
| `app.py` | Dashboard Streamlit — mỗi người tự nhập token của mình, không dùng chung |

## Dashboard web (`app.py`) — mỗi người tự nhập token riêng

Mỗi người trong Apero dùng **account Adjust riêng** (API Token cá nhân + App
Token đều khác nhau) — nên `app.py` **không đọc token từ Secrets/`.env` nữa**.
Mở app lên, ở sidebar tự nhập:
- **API Token cá nhân** (Adjust → Settings góc dưới trái → Account settings →
  tab "My profile" → API Token)
- **App Token** của app muốn xem (Adjust → mở app → Cài đặt app → "App Token",
  ~12 ký tự; nhiều app thì cách nhau bởi dấu phẩy)

Token chỉ lưu tạm trong phiên trình duyệt của người đó (session_state), không
lưu trên server, không ai khác dùng chung app thấy được.

Chạy local:
```
pip install -r requirements.txt
streamlit run app.py
```
Mở trình duyệt tại địa chỉ Streamlit in ra (thường `http://localhost:8501`),
nhập token ở sidebar, chọn số ngày, bấm "Kéo dữ liệu".

### Deploy lên Streamlit Community Cloud

1. Push code (không gồm `.env`, `adjust_data.db` — đã có trong `.gitignore`) lên
   1 repo GitHub (bạn tự làm phần này).
2. Vào https://share.streamlit.io → New app → chọn repo, branch, file `app.py`.
3. Deploy — **không cần cấu hình Secrets gì cả**, vì token do người dùng tự nhập
   trên giao diện mỗi lần mở app.

## Script `adjust_test.py` / `adjust_pull_and_cache.py` — dùng `.env` chung

2 script này (xem tay + cache nền) vẫn dùng chung 1 bộ token qua `.env`, khác
với `app.py` (mỗi người tự nhập trên giao diện):

1. Tạo file `.env` (copy từ `.env.example`), điền:
   - `ADJUST_API_TOKEN` — API Token cá nhân của người chạy script này.
   - `ADJUST_APP_TOKENS` — danh sách App Token, cách nhau bởi dấu phẩy, không
     khoảng trắng thừa. VD: `ADJUST_APP_TOKENS=abc123def456,xyz789uvw012`

2. Chạy tay để xem/đối chiếu Datascape:
   ```
   python adjust_test.py
   ```
   In 2 bảng: chi tiết (app+day+campaign+country) và tổng theo app.

3. Chạy cache nền (thủ công hoặc qua Task Scheduler):
   ```
   python adjust_pull_and_cache.py
   ```
   Lưu/cập nhật dữ liệu vào `adjust_data.db` — dùng cho việc lưu lịch sử, KHÔNG
   phải nguồn dữ liệu của `app.py` (xem GHI_CHU_TIEN_DO.md mục kiến trúc deploy).

## Lưu ý an toàn

- `.env`, `adjust_data.db` chứa/liên quan dữ liệu thật hoặc token — đã có trong
  `.gitignore`, **không commit lên git**.
- Không chia sẻ nội dung các file trên ra ngoài (Slack, chat, email...).
- Trên `app.py`: mỗi người tự nhập token của mình, không gõ hộ/chia sẻ token
  của mình cho người khác dùng chung link.
