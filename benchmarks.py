"""
Lưu/đọc benchmark eCPM do user tự nhập cho TỪNG APP — dùng cho "Bảng điểm thị
trường" trong app.py.

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
    """Trả về dict {product_id: benchmark_ecpm}. Rỗng nếu file chưa có/lỗi."""
    if os.path.exists(BENCHMARK_FILE):
        try:
            with open(BENCHMARK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có gì
            return {}
    return {}


def save_benchmark(product_id: str, value: float) -> None:
    data = load_benchmarks()
    data[product_id] = value
    with open(BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
