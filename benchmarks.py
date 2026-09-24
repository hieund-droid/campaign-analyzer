"""
Lưu/đọc benchmark CPI + LTV (ARPU D0) cho trang "Xét nghiệm" — MỖI (APP, QUỐC
GIA) 1 mốc riêng. Campaign chạy GLOBAL thì CPI/LTV "bình thường" của mỗi nước
khác nhau rất nhiều — benchmark 1 mốc chung cho cả app KHÔNG có ý nghĩa.

ĐỔI 23/09/2026 — CHUYỂN TỪ FILE JSON SANG GOOGLE SHEET: user lưu benchmark
cho US xong bị MẤT khi mở lại — nguyên nhân: file JSON nằm trong project trên
Streamlit Cloud KHÔNG bền vững (bị reset về rỗng mỗi khi app redeploy — mà
redeploy xảy ra MỖI LẦN tải code mới lên GitHub — hoặc app ngủ rồi thức dậy).
Chuyển sang Google Sheet để dữ liệu KHÔNG mất qua các lần redeploy nữa.

Dùng CHUNG 1 service account đã có sẵn từ thời BigQuery (đã bỏ BigQuery
nhưng service account key vẫn giữ lại, xin dùng lại cho việc này) — đọc
credentials theo ĐÚNG cách project đã làm trước đây:
  - Local: biến môi trường `GOOGLE_APPLICATION_CREDENTIALS` (đường dẫn tới
    file .json service account, KHÔNG commit git).
  - Deploy (Streamlit Cloud): Streamlit Secrets mục `[gcp_service_account]`.
Cần thêm biến môi trường/Secrets `BENCHMARK_SHEET_ID` — ID của Google Sheet
(user tự tạo Sheet trống + chia sẻ quyền Editor cho email service account,
rồi lấy ID trong URL Sheet đưa vào).

Cấu trúc Sheet: 1 sheet tên "benchmarks" (tự tạo nếu chưa có), 4 cột:
product_id, country, cpi, arpu_d0 — MỖI DÒNG là 1 (app, quốc gia).
`save_all_country_benchmarks()` ghi đè TOÀN BỘ dòng của 1 product_id (giữ
nguyên dòng của app khác) — cùng ngữ nghĩa với bản JSON cũ, chỉ đổi nơi lưu.

⚠️ Vẫn có rủi ro riêng của Google Sheet (API có thể lỗi/chậm, quota giới hạn)
— nhưng KHÔNG còn bị mất dữ liệu khi app redeploy/ngủ như file JSON cũ nữa.
"""

import json
import os

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORKSHEET_NAME = "benchmarks"
HEADER = ["product_id", "country", "cpi", "arpu_d0"]
DOCTOR_BENCHMARK_KEYS = ["cpi", "arpu_d0"]


def _get_credentials_info() -> dict | None:
    """Đọc service account credentials — ƯU TIÊN Streamlit Secrets (deploy),
    fallback về file local qua GOOGLE_APPLICATION_CREDENTIALS (giống cách
    project đã dùng cho BigQuery trước đây)."""
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:  # noqa: BLE001 — chưa có secrets.toml (local) là bình thường
        pass
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _get_sheet_id() -> str | None:
    """Đọc BENCHMARK_SHEET_ID từ biến môi trường HOẶC Streamlit Secrets.

    THÊM 23/09/2026 — cũng tự dò trong `[gcp_service_account]`: nếu user lỡ
    dán `BENCHMARK_SHEET_ID = "..."` ở CUỐI ô Secrets (SAU dòng
    `[gcp_service_account]`), theo cú pháp TOML nó sẽ bị hiểu nhầm thành 1
    field NẰM TRONG bảng đó (mọi dòng key=value sau 1 tiêu đề [bảng] đều
    thuộc về bảng đó cho đến tiêu đề [bảng] tiếp theo) — đã gặp lỗi thật vì
    hướng dẫn "thêm ở đầu hoặc cuối" không nói rõ vị trí bắt buộc phải TRƯỚC
    dòng [gcp_service_account]. Dò thêm chỗ này để không cần user phải sửa
    lại Secrets, dù cách đúng vẫn là đặt ở ĐẦU."""
    sheet_id = os.environ.get("BENCHMARK_SHEET_ID")
    if sheet_id:
        return sheet_id
    try:
        sheet_id = st.secrets.get("BENCHMARK_SHEET_ID")
        if sheet_id:
            return sheet_id
        gcp = st.secrets.get("gcp_service_account")
        if gcp:
            return gcp.get("BENCHMARK_SHEET_ID")
    except Exception:  # noqa: BLE001
        return None
    return None


@st.cache_resource(show_spinner=False)
def _get_worksheet():
    """Cache RESOURCE (không phải data) — kết nối gspread chỉ cần dựng 1 lần
    cho cả tiến trình, tái dùng qua các lần rerun/user khác nhau."""
    creds_info = _get_credentials_info()
    if not creds_info:
        raise RuntimeError(
            "Thiếu Google service account credentials — cần GOOGLE_APPLICATION_CREDENTIALS "
            "(local) hoặc Streamlit Secrets [gcp_service_account] (deploy)."
        )
    sheet_id = _get_sheet_id()
    if not sheet_id:
        raise RuntimeError("Thiếu BENCHMARK_SHEET_ID (biến môi trường hoặc Streamlit Secrets).")

    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADER))
        ws.append_row(HEADER)
    return ws


def get_all_country_benchmarks(product_id: str) -> dict:
    """Trả về TOÀN BỘ benchmark đã lưu của 1 app, theo từng quốc gia:
    {country: {"cpi":..., "arpu_d0":...}} — dùng cho bảng sửa trực tiếp ở
    trang Benchmark, và cho bảng "Theo quốc gia" ở trang Xét nghiệm.

    QUAN TRỌNG — value_render_option="UNFORMATTED_VALUE": đã kiểm chứng bằng
    số thật (23/09/2026), Sheet này có locale vi_VN (dấu PHẨY là thập phân,
    dấu CHẤM là phân cách hàng nghìn) — mặc định gspread đọc theo giá trị ĐÃ
    ĐỊNH DẠNG hiển thị (VD 1.8 hiện thành "1,8") rồi tự chuyển đổi lại thành
    số theo kiểu Mỹ (coi dấu phẩy là phân cách hàng nghìn) → RA SAI (1,8 →
    18.0). Dùng UNFORMATTED_VALUE để lấy đúng số gốc, bỏ qua định dạng hiển
    thị theo locale."""
    ws = _get_worksheet()
    rows = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    result = {}
    for r in rows:
        if str(r.get("product_id")) != str(product_id):
            continue
        country = r.get("country")
        if not country:
            continue
        result[country] = {
            "cpi": float(r["cpi"]) if r.get("cpi") not in (None, "") else None,
            "arpu_d0": float(r["arpu_d0"]) if r.get("arpu_d0") not in (None, "") else None,
        }
    return result


def save_all_country_benchmarks(product_id: str, entries: list) -> None:
    """Ghi đè TOÀN BỘ benchmark của 1 app bằng danh sách entries (mỗi entry:
    {"country":.., "cpi":.., "arpu_d0":..}) — GIỮ NGUYÊN dòng của app khác,
    xoá hết dòng CŨ của app này rồi ghi lại đúng những gì đang có trong bảng
    (dòng nào để trống cả CPI lẫn LTV thì không lưu — coi như đã xoá).

    value_render_option="UNFORMATTED_VALUE": BẮT BUỘC — hàm này đọc lại dòng
    của CÁC APP KHÁC để giữ nguyên rồi ghi lại y hệt; nếu đọc sai theo locale
    (xem docstring get_all_country_benchmarks()) sẽ GHI ĐÈ SAI benchmark của
    app khác mỗi lần lưu bất kỳ app nào — đã gặp lỗi thật lúc test, sửa ở cả
    2 hàm."""
    ws = _get_worksheet()
    all_rows = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    kept = [r for r in all_rows if str(r.get("product_id")) != str(product_id)]

    new_rows = []
    for e in entries:
        country = e.get("country")
        if not country:
            continue
        cpi = e.get("cpi")
        arpu = e.get("arpu_d0")
        if cpi in (None, "") and arpu in (None, ""):
            continue
        new_rows.append({"product_id": product_id, "country": country, "cpi": cpi, "arpu_d0": arpu})

    final_rows = kept + new_rows
    ws.clear()
    ws.append_row(HEADER)
    if final_rows:
        ws.append_rows([[r.get(h, "") for h in HEADER] for r in final_rows])
