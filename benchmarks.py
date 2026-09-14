"""
Lưu/đọc benchmark eCPM do user tự nhập — MỖI APP × MỖI QUỐC GIA 1 benchmark
riêng (eCPM lệch rất xa giữa các nước, VD Mỹ ~$20 vs Syria ~$0.8 — không thể
dùng chung 1 mốc cho cả app). Dùng cho "Bảng điểm thị trường" trong app.py.

Cấu trúc lưu: {product_id: {country: benchmark_ecpm}}

⚠️ LƯU Ý QUAN TRỌNG: lưu vào 1 file JSON ngay trong thư mục project. Khi chạy
local, file này bền vững bình thường. Khi deploy Streamlit Cloud, ổ đĩa app
chạy trên đó là TẠM THỜI — file có thể mất khi app "ngủ" rồi thức dậy, hoặc
mỗi khi deploy lại code mới (git clone lại từ đầu). Coi đây là benchmark tạm,
nếu cần bền vững tuyệt đối (không bao giờ mất) cần đổi sang lưu ở nơi khác
(VD Google Sheet, hoặc 1 bảng ghi được trên BigQuery) — CHƯA làm việc này.
"""

import json
import os

BENCHMARK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_benchmarks.json")


def load_benchmarks() -> dict:
    """Trả về dict {product_id: {country: benchmark_ecpm}}. Rỗng nếu file
    chưa có/lỗi/hỏng."""
    if os.path.exists(BENCHMARK_FILE):
        try:
            with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Tương thích ngược: bản cũ lưu {product_id: value} (1 số, không
                # theo quốc gia) — nếu gặp dạng cũ thì bỏ qua (coi như chưa có),
                # tránh crash khi đọc nhầm kiểu dữ liệu.
                return {
                    pid: countries
                    for pid, countries in data.items()
                    if isinstance(countries, dict)
                }
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có gì
            return {}
    return {}


def get_product_benchmarks(product_id: str) -> dict:
    """Trả về {country: benchmark_ecpm} của riêng app này. Rỗng nếu chưa đặt gì."""
    return load_benchmarks().get(product_id, {})


def save_product_benchmarks(product_id: str, country_values: dict) -> None:
    """Ghi đè TOÀN BỘ benchmark theo quốc gia của 1 app (country_values đã là
    bản đầy đủ mới nhất, không phải chỉ phần thay đổi)."""
    data = load_benchmarks()
    data[product_id] = {k: float(v) for k, v in country_values.items()}
    with open(BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
