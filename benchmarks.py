"""
Lưu/đọc benchmark do user tự nhập cho trang "Xét nghiệm" (Campaign Doctor) —
CPI/ARPU D0 (LTV)/ROAS D0/Retention D1 + Ngưỡng lệch, MỖI (APP, QUỐC GIA) 1
mốc riêng. ĐỔI 23/09/2026 (theo yêu cầu user): trước đây benchmark chỉ theo
APP (gộp mọi quốc gia) — user chỉ ra campaign chạy GLOBAL, benchmark 1 mốc
chung cho cả app KHÔNG có ý nghĩa vì CPI/LTV "bình thường" của US khác hẳn
Ấn Độ/Brazil... — đổi hẳn sang nhập/lưu theo TỪNG QUỐC GIA của TỪNG app.

Trang "Xét nghiệm" Tầng 1 (đánh giá CẢ campaign, gộp mọi quốc gia) KHÔNG còn
benchmark app-level để so nữa (đã bỏ theo đúng yêu cầu "chỉ nhập theo quốc
gia") — Tầng 1 vẫn hiện số thực tế, chỉ là không còn phần "so benchmark" nếu
không có benchmark app-level. Việc so benchmark giờ CHỈ có ý nghĩa ở bảng
"Theo quốc gia" (mỗi dòng dùng ĐÚNG benchmark của quốc gia đó).

⚠️ Lưu vào file JSON trong project — CHƯA bền vững trên Streamlit Cloud (có
thể mất khi app ngủ/redeploy). Coi đây là benchmark tạm, nếu cần bền vững
tuyệt đối cần đổi sang lưu ở nơi khác (VD Google Sheet) — CHƯA làm việc này.
"""

import json
import os

DOCTOR_BENCHMARK_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "doctor_benchmarks.json"
)
DOCTOR_BENCHMARK_KEYS = ["cpi", "arpu_d0", "roas_d0", "retention_d1", "threshold_pct"]


def load_doctor_benchmarks() -> dict:
    """Trả về dict lồng nhau: {product_id: {country: {"cpi":..., "arpu_d0":...,
    "roas_d0":..., "retention_d1":..., "threshold_pct":...}}}."""
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


def get_doctor_benchmarks(product_id: str, country: str) -> dict:
    """Trả về benchmark của ĐÚNG 1 (app, quốc gia). Thiếu key nào thì key đó
    = None (chưa đặt benchmark cho quốc gia này)."""
    saved = load_doctor_benchmarks().get(product_id, {}).get(country, {})
    return {k: saved.get(k) for k in DOCTOR_BENCHMARK_KEYS}


def get_all_country_benchmarks(product_id: str) -> dict:
    """Trả về TOÀN BỘ benchmark đã lưu của 1 app, theo từng quốc gia:
    {country: {"cpi":..., ...}} — dùng cho bảng "Theo quốc gia" (so MỖI dòng
    với ĐÚNG benchmark của quốc gia đó, thay vì gọi get_doctor_benchmarks()
    lặp lại nhiều lần)."""
    countries = load_doctor_benchmarks().get(product_id, {})
    return {
        country: {k: v.get(k) for k in DOCTOR_BENCHMARK_KEYS}
        for country, v in countries.items()
    }


def save_doctor_benchmarks(product_id: str, country: str, values: dict) -> None:
    """Ghi đè benchmark của ĐÚNG 1 (app, quốc gia)."""
    data = load_doctor_benchmarks()
    app_entry = data.setdefault(product_id, {})
    app_entry[country] = {
        k: float(values[k]) for k in DOCTOR_BENCHMARK_KEYS if values.get(k) is not None
    }
    with open(DOCTOR_BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_benchmarked_countries(product_id: str) -> list:
    """Danh sách quốc gia ĐÃ có benchmark cho app này — dùng để hiện gợi ý/
    trạng thái trên trang Benchmark."""
    return sorted(load_doctor_benchmarks().get(product_id, {}).keys())
