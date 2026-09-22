"""
Lưu/đọc benchmark do user tự nhập cho trang "Xét nghiệm" (Campaign Doctor) —
CPI + ARPU D0 (LTV) MỖI (APP, QUỐC GIA) 1 mốc riêng. Campaign chạy GLOBAL thì
CPI/LTV "bình thường" của mỗi nước khác nhau rất nhiều — benchmark 1 mốc
chung cho cả app KHÔNG có ý nghĩa (user chỉ ra 23/09/2026).

ĐỔI 23/09/2026 (theo yêu cầu user, lần 2 — đơn giản hoá): BỎ HẲN ROAS D0,
Retention D1, "Ngưỡng lệch (%)" khỏi benchmark — "benchmark chỉ cần biết về
CPI và LTV thôi". Ngưỡng lệch coi là có vấn đề giờ dùng CỐ ĐỊNH
`campaign_doctor.DEFAULT_THRESHOLD_PCT` (20%) cho mọi nơi, không tự nhập
được nữa.

Trang "Benchmark" giờ là 1 BẢNG SỬA TRỰC TIẾP (st.data_editor) — mỗi dòng là
1 quốc gia của 1 app, sửa/xoá/thêm dòng ngay trên bảng rồi lưu — dùng
`save_all_country_benchmarks()` (ghi đè TOÀN BỘ danh sách quốc gia của app đó
theo đúng bảng đang hiện, xoá dòng nào thì mất benchmark quốc gia đó).

Trang "Xét nghiệm" Tầng 1 (đánh giá CẢ campaign, gộp mọi quốc gia) KHÔNG còn
benchmark app-level để so nữa — Tầng 1 vẫn hiện số thực tế, chỉ là không còn
phần "so benchmark" (việc so benchmark giờ CHỈ có ý nghĩa ở bảng "Theo quốc
gia", mỗi dòng dùng ĐÚNG benchmark của quốc gia đó).

⚠️ Lưu vào file JSON trong project — CHƯA bền vững trên Streamlit Cloud (có
thể mất khi app ngủ/redeploy). Coi đây là benchmark tạm, nếu cần bền vững
tuyệt đối cần đổi sang lưu ở nơi khác (VD Google Sheet) — CHƯA làm việc này.
"""

import json
import os

DOCTOR_BENCHMARK_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "doctor_benchmarks.json"
)
DOCTOR_BENCHMARK_KEYS = ["cpi", "arpu_d0"]


def load_doctor_benchmarks() -> dict:
    """Trả về dict lồng nhau: {product_id: {country: {"cpi":..., "arpu_d0":...}}}."""
    if os.path.exists(DOCTOR_BENCHMARK_FILE):
        try:
            with open(DOCTOR_BENCHMARK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    pid: {c: v for c, v in countries.items() if isinstance(v, dict)}
                    for pid, countries in data.items()
                    if isinstance(countries, dict)
                }
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có gì
            return {}
    return {}


def get_all_country_benchmarks(product_id: str) -> dict:
    """Trả về TOÀN BỘ benchmark đã lưu của 1 app, theo từng quốc gia:
    {country: {"cpi":..., "arpu_d0":...}} — dùng cho bảng sửa trực tiếp ở
    trang Benchmark, và cho bảng "Theo quốc gia" ở trang Xét nghiệm (so MỖI
    dòng với ĐÚNG benchmark của quốc gia đó)."""
    countries = load_doctor_benchmarks().get(product_id, {})
    return {
        country: {k: v.get(k) for k in DOCTOR_BENCHMARK_KEYS}
        for country, v in countries.items()
    }


def save_all_country_benchmarks(product_id: str, entries: list) -> None:
    """Ghi đè TOÀN BỘ benchmark của 1 app bằng danh sách entries (mỗi entry:
    {"country":.., "cpi":.., "arpu_d0":..}) — dùng cho bảng sửa trực tiếp
    (data_editor) ở trang Benchmark: dòng nào bị xoá khỏi bảng (hoặc để
    trống cả CPI lẫn LTV) thì MẤT LUÔN benchmark của quốc gia đó — bảng phản
    ánh đúng trạng thái hiện tại, không phải chỉ cộng dồn thêm."""
    data = load_doctor_benchmarks()
    app_entry = {}
    for e in entries:
        country = e.get("country")
        if not country:
            continue
        vals = {k: e.get(k) for k in DOCTOR_BENCHMARK_KEYS if e.get(k) not in (None, "")}
        if vals:
            app_entry[country] = {k: float(v) for k, v in vals.items()}
    data[product_id] = app_entry
    with open(DOCTOR_BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
