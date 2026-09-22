"""
Chụp snapshot NGẦM cho "Cảnh báo trong ngày" — không cần ai mở app liên tục.

CÁCH HOẠT ĐỘNG: MẶC ĐỊNH — hễ ai đó nhập ĐỦ API Token + App Token ở sidebar
(để dùng app bình thường), token đó TỰ ĐỘNG được thêm vào 1 DANH SÁCH lưu
trong file JSON phía SERVER (KHÁC HẲN "Ghi nhớ" — cái đó chỉ lưu vào
localStorage TRÌNH DUYỆT của riêng người đó, server không đọc được khi họ
đóng tab). KHÔNG cần tick riêng gì cả (đã bỏ checkbox 22/09/2026 theo yêu cầu
user: "mặc định tất cả mọi người đều cần đến việc data cần được chạy ngầm")
— nhưng vẫn HIỂN THỊ RÕ RÀNG bằng 1 caption ở sidebar, không âm thầm giấu.
Từ đó, 1 luồng (thread) chạy NGẦM bên trong chính tiến trình Streamlit sẽ tự
gọi Adjust API mỗi `CAPTURE_INTERVAL_SECONDS` giây, LẦN LƯỢT dùng TỪNG token
đã góp, để chụp snapshot — không cần ai đang mở tab tại thời điểm đó.

QUAN TRỌNG — vì sao phải lưu THÀNH DANH SÁCH (nhiều token), không phải 1 token
duy nhất: đã hỏi user (22/09/2026) và xác nhận mỗi người trong team CHỈ được
Adjust phân quyền xem 1 vài app riêng (không phải ai cũng xem được hết mọi
app) — nếu chỉ dùng token của 1 người, luồng ngầm sẽ BỎ SÓT các app mà người
đó không có quyền xem. Vì vậy: MỖI NGƯỜI nhập token sẽ tự động GÓP THÊM 1 mục
(không ghi đè mục của người khác) — luồng ngầm gọi API riêng cho từng mục,
gộp lại đủ mọi app cả team quản lý.

LƯU Ý — "cho cả team" KHÔNG có nghĩa 1 người chụp ngầm thì cả team tự nhiên
xem được app của nhau: ai xem được app nào vẫn do CHÍNH ADJUST phân quyền,
không đổi được qua tính năng này. Nó chỉ giúp: khi CHÍNH người có quyền xem 1
app quay lại kiểm tra, dữ liệu trong ngày đã có sẵn (được chụp ngầm từ trước),
không phải đợi tự bấm Apply mới có.

GIỚI HẠN THẬT (đã nói rõ với user trước khi làm, KHÔNG giấu): luồng ngầm chỉ
chạy được khi tiến trình Streamlit Cloud đang SỐNG (có người ghé thăm gần
đây) — Streamlit Community Cloud "ngủ" hẳn (tắt tiến trình) nếu không ai ghé
qua đủ lâu, lúc đó luồng ngầm cũng dừng theo, chỉ chạy lại khi có người mở
app tiếp theo. Đây KHÔNG phải cron 24/7 thật sự (không có hạ tầng nào cho
phép điều đó ở gói Streamlit Cloud miễn phí) — nhưng đỡ hơn nhiều so với
"phải tự bấm Apply": miễn app còn được ai đó ghé thăm định kỳ trong ngày (dù
không cần đúng lúc, không cần vào đúng trang Cảnh báo), snapshot vẫn tự tích
lũy nhờ luồng ngầm này.

⚠️ Danh sách token dùng chung lưu vào file JSON phía server — CHƯA bền vững
trên Streamlit Cloud (có thể mất khi app ngủ/redeploy, giống mọi file JSON
khác của project) — nếu mất, từng người cần tick lại.
"""

import json
import os
import threading
import time

SHARED_TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_capture_token.json")
CAPTURE_INTERVAL_SECONDS = 60 * 60  # 1 tiếng — theo yêu cầu user (22/09/2026)


def _load_entries() -> list:
    """[{"api_token":.., "app_tokens_raw":..}, ...] — 1 mục cho MỖI người đã
    tick góp token (không phải 1 token duy nhất — xem docstring đầu file)."""
    if os.path.exists(SHARED_TOKENS_FILE):
        try:
            with open(SHARED_TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                entries = data.get("entries", [])
                return entries if isinstance(entries, list) else []
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có
            return []
    return []


def _save_entries(entries: list) -> None:
    with open(SHARED_TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f)


def add_or_update_shared_token(api_token: str, app_tokens_raw: str) -> None:
    """Thêm 1 mục MỚI, hoặc cập nhật app_tokens_raw nếu api_token này ĐÃ có
    trong danh sách (người đó tick lại/đổi App Token) — KHÔNG đụng tới mục
    của người khác."""
    entries = _load_entries()
    for e in entries:
        if e.get("api_token") == api_token:
            e["app_tokens_raw"] = app_tokens_raw
            _save_entries(entries)
            return
    entries.append({"api_token": api_token, "app_tokens_raw": app_tokens_raw})
    _save_entries(entries)


def remove_shared_token(api_token: str) -> None:
    """Bỏ ĐÚNG mục của token này (khi người đó bỏ tick) — giữ nguyên mục của
    người khác."""
    entries = _load_entries()
    entries = [e for e in entries if e.get("api_token") != api_token]
    _save_entries(entries)


def count_shared_tokens() -> int:
    return len(_load_entries())


def _capture_once() -> None:
    """1 lần chụp — LẦN LƯỢT gọi Adjust (hôm nay) cho TỪNG token đã góp, chụp
    snapshot cho MỌI app xuất hiện trong dữ liệu trả về của token đó. 1 token
    lỗi (VD bị thu hồi) KHÔNG được chặn các token khác — bọc riêng từng vòng."""
    entries = _load_entries()
    if not entries:
        return

    import pandas as pd

    import adjust_client as ac
    import campaign_snapshots as csnap

    today_str = csnap.today_str_vn()

    for entry in entries:
        api_token = entry.get("api_token")
        app_tokens_raw = entry.get("app_tokens_raw")
        if not api_token or not app_tokens_raw:
            continue

        app_tokens = ac.parse_app_tokens(app_tokens_raw)
        try:
            data = ac.fetch_detail(
                api_token, app_tokens, days_back=1, exit_on_error=False,
                include_today=True, include_country=False,
            )
        except Exception:  # noqa: BLE001 — token này sai/mạng lỗi — bỏ qua,
            # KHÔNG dừng cả vòng lặp, thử token khác + thử lại chu kỳ sau.
            continue

        rows = data.get("rows") or []
        if not rows:
            continue
        df = pd.DataFrame(rows)
        for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        today_df = df[df["day"] == today_str]
        if today_df.empty:
            continue

        for app_name, g_app in today_df.groupby("app"):
            campaign_stats = {}
            for campaign_name, g in g_app.groupby("campaign"):
                installs = g["installs"].sum()
                cost = g["network_cost"].sum()
                revenue_d0 = (g["roas_ad_d0"].fillna(0) * g["network_cost"]).sum()
                campaign_stats[campaign_name] = {
                    "installs": installs,
                    "cpi": (cost / installs) if installs else None,
                    "roas_d0": (revenue_d0 / cost) if cost else None,
                    "arpu_d0": (revenue_d0 / installs) if installs else None,
                }
            try:
                csnap.maybe_capture_snapshots(app_name, campaign_stats)
            except Exception:  # noqa: BLE001
                continue


def _background_loop() -> None:
    while True:
        try:
            _capture_once()
        except Exception:  # noqa: BLE001 — luồng ngầm KHÔNG được phép chết vì
            # 1 lần lỗi — bỏ qua, thử lại ở chu kỳ sau.
            pass
        time.sleep(CAPTURE_INTERVAL_SECONDS)


_thread_started = False
_thread_lock = threading.Lock()


def ensure_background_thread_started() -> None:
    """Bảo đảm CHỈ 1 thread chạy ngầm cho CẢ TIẾN TRÌNH (không phải mỗi
    session/mỗi lần rerun 1 thread mới) — gọi hàm này ở module-level trong
    app.py (ngoài mọi hàm trang), tự động no-op nếu đã chạy rồi."""
    global _thread_started
    with _thread_lock:
        if not _thread_started:
            t = threading.Thread(target=_background_loop, daemon=True)
            t.start()
            _thread_started = True
