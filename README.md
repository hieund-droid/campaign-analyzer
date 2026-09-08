# Campaign Analyzer

Đọc `CLAUDE.md` và `GHI_CHU_TIEN_DO.md` trước — 2 file đó ghi trạng thái/quyết định
mới nhất. File này chỉ hướng dẫn cách chạy.

## Các file chính

| File | Vai trò |
|---|---|
| `adjust_client.py` | Cấu hình + hàm gọi Adjust Report Service API (dùng chung) |
| `adjust_test.py` | Chạy tay, in bảng ra màn hình để xem/đối chiếu Datascape |
| `adjust_pull_and_cache.py` | Chạy nền (Task Scheduler), lưu vào `adjust_data.db` (SQLite) |
| `bq_client.py` | Hàm query 2 view BigQuery (Meta/TikTok/Google Ads + AdMob) |
| `app.py` | Dashboard Streamlit — 2 tab: Adjust (mỗi người tự nhập token) + BigQuery (dùng chung 1 key) |

## Dashboard web (`app.py`)

### Tab "Adjust" — mỗi người tự nhập token riêng

Mỗi người trong Apero dùng **account Adjust riêng** (API Token cá nhân + App
Token đều khác nhau) — tab này **không đọc token từ Secrets/`.env`**. Mở app,
tự nhập ngay trên giao diện:
- **API Token cá nhân** (Adjust → Settings góc dưới trái → Account settings →
  tab "My profile" → API Token)
- **App Token** của app muốn xem (Adjust → mở app → Cài đặt app → "App Token",
  ~12 ký tự; nhiều app thì cách nhau bởi dấu phẩy)

Token chỉ lưu tạm trong phiên trình duyệt của người đó (session_state), không
lưu trên server, không ai khác dùng chung app thấy được.

### Tab "BigQuery" (Meta/TikTok/Google Ads + AdMob) — dùng chung 1 key

Khác với Adjust, đây là 1 service account key của team Data, **dùng chung cho
cả team** — không cần mỗi người tự nhập. Chỉ cần chọn app (`product_id`) và
khoảng ngày. Xem `AGENT-BRIEF.md` (không commit git) để biết chi tiết 2 view
đang dùng và các quy tắc tính toán bắt buộc phải theo (không AVG cột tỉ lệ,
loại Google Ads khỏi CPM/CTR, v.v).

### Chạy local

```
pip install -r requirements.txt
streamlit run app.py
```
Mở trình duyệt tại địa chỉ Streamlit in ra (thường `http://localhost:8501`).
Tab Adjust: nhập token ở trên. Tab BigQuery: cần `.env` có
`GOOGLE_APPLICATION_CREDENTIALS=<đường dẫn tới file service account key>`.

### Deploy lên Streamlit Community Cloud

1. Push code lên GitHub (không gồm `.env`, `adjust_data.db`, `credentials/`,
   `AGENT-BRIEF.md` — đã có trong `.gitignore`).
2. Vào https://share.streamlit.io → New app → chọn repo, branch, file `app.py`.
3. **Trước khi deploy**, vào mục **Secrets**, dán (thay giá trị thật vào — lấy
   từ file JSON key, xem `.env.example` để biết đường dẫn key đang lưu ở máy nào):
   ```toml
   [gcp_service_account]
   type = "service_account"
   project_id = "..."
   private_key_id = "..."
   private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
   client_email = "..."
   client_id = "..."
   auth_uri = "https://accounts.google.com/o/oauth2/auth"
   token_uri = "https://oauth2.googleapis.com/token"
   auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
   client_x509_cert_url = "..."
   universe_domain = "googleapis.com"
   ```
   (copy nguyên nội dung file JSON key, giữ đúng format `\n` trong `private_key`)
   ⚠️ Chỉ dán vào ô Secrets này, KHÔNG bao giờ đưa vào code/file commit lên git.
4. Deploy. Tab Adjust vẫn không cần Secrets (mỗi người tự nhập token khi dùng).

## Script `adjust_test.py` / `adjust_pull_and_cache.py` — dùng `.env` chung

2 script này (xem tay + cache nền, KHÔNG phải `app.py`) dùng chung 1 bộ token
Adjust qua `.env`:

1. Tạo file `.env` (copy từ `.env.example`), điền:
   - `ADJUST_API_TOKEN` — API Token cá nhân của người chạy script này.
   - `ADJUST_APP_TOKENS` — danh sách App Token, cách nhau bởi dấu phẩy, không
     khoảng trắng thừa. VD: `ADJUST_APP_TOKENS=abc123def456,xyz789uvw012`
   - `GOOGLE_APPLICATION_CREDENTIALS` — đường dẫn tới file service account key
     BigQuery (dùng khi test tab BigQuery ở máy local).

2. Chạy tay để xem/đối chiếu Datascape:
   ```
   python adjust_test.py
   ```

3. Chạy cache nền (thủ công hoặc qua Task Scheduler):
   ```
   python adjust_pull_and_cache.py
   ```
   Lưu/cập nhật dữ liệu vào `adjust_data.db` — dùng cho việc lưu lịch sử, KHÔNG
   phải nguồn dữ liệu của `app.py` (xem GHI_CHU_TIEN_DO.md mục kiến trúc deploy).

## Lưu ý an toàn

- `.env`, `adjust_data.db`, `credentials/`, `AGENT-BRIEF.md` chứa/liên quan dữ
  liệu thật hoặc bí mật — đã có trong `.gitignore`, **không commit lên git**.
- Không chia sẻ nội dung các file trên ra ngoài (Slack, chat, email...).
- Tab Adjust: mỗi người tự nhập token của mình, không gõ hộ/chia sẻ token của
  mình cho người khác dùng chung link.
- Tab BigQuery: key dùng chung cho team — không tự ý đổi/xoá key trên Google
  Cloud Console mà không báo trước.
