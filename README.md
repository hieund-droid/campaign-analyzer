# Campaign Analyzer

Đọc `CLAUDE.md` và `GHI_CHU_TIEN_DO.md` trước — 2 file đó ghi trạng thái/quyết định
mới nhất. File này chỉ hướng dẫn cách chạy.

## Các file chính

| File | Vai trò |
|---|---|
| `adjust_client.py` | Cấu hình + hàm gọi Adjust Report Service API (dùng chung) |
| `adjust_test.py` | Chạy tay, in bảng ra màn hình để xem/đối chiếu Datascape |
| `adjust_pull_and_cache.py` | Chạy nền (Task Scheduler), lưu vào `adjust_data.db` (SQLite) |
| `app.py` | Dashboard Streamlit — tự gọi Adjust API, có cache tạm 15 phút |

## Cài đặt lần đầu

1. Cài thư viện:
   ```
   pip install -r requirements.txt
   ```

2. Tạo file `.env` (copy từ `.env.example`), điền:
   - `ADJUST_API_TOKEN` — Adjust → Settings góc dưới trái → Account settings → tab
     "My profile" → API Token.
   - `ADJUST_APP_TOKENS` — danh sách App Token của các app muốn kéo, cách nhau bởi
     dấu phẩy, không khoảng trắng thừa. Lấy ở: Adjust → mở app → Cài đặt app →
     "App Token" (~12 ký tự). VD: `ADJUST_APP_TOKENS=abc123def456,xyz789uvw012`

## Chạy tay để xem/đối chiếu

```
python adjust_test.py
```
In 2 bảng: chi tiết (app+day+campaign+country) và tổng theo app — đối chiếu với
Datascape trong Adjust (bạn tự làm, xem GHI_CHU_TIEN_DO.md mục "Đối chiếu").

## Chạy dashboard web (local)

```
streamlit run app.py
```
Mở trình duyệt tại địa chỉ Streamlit in ra (thường `http://localhost:8501`).

## Chạy cache nền (thủ công hoặc qua Task Scheduler)

```
python adjust_pull_and_cache.py
```
Lưu/cập nhật dữ liệu vào `adjust_data.db`. Dùng cho việc lưu lịch sử — **KHÔNG
phải nguồn dữ liệu của `app.py`** (app.py tự gọi Adjust trực tiếp, xem lý do ở
GHI_CHU_TIEN_DO.md mục kiến trúc deploy).

## Deploy `app.py` lên Streamlit Community Cloud

1. Push code (không gồm `.env`, `adjust_data.db` — đã có trong `.gitignore`) lên
   1 repo GitHub (bạn tự làm phần này).
2. Vào https://share.streamlit.io → New app → chọn repo, branch, file `app.py`.
3. **Trước khi deploy**, vào mục **Secrets** của app, dán (xem mẫu ở
   `.streamlit/secrets.toml.example`):
   ```
   ADJUST_API_TOKEN = "token_that_cua_ban"
   ADJUST_APP_TOKENS = "app_token_1,app_token_2"
   ```
   ⚠️ KHÔNG bao giờ dán token vào code hay file commit lên git — chỉ dán ở đây.
4. Deploy. App tự gọi Adjust API mỗi khi có người mở, cache tạm 15 phút.

## Lưu ý an toàn

- `.env`, `adjust_data.db`, `.streamlit/secrets.toml` đều chứa/liên quan dữ liệu
  thật hoặc token — đã có trong `.gitignore`, **không commit lên git**.
- Không chia sẻ nội dung các file trên ra ngoài (Slack, chat, email...).
