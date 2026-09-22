"""
Lưu/đọc benchmark do user tự nhập cho trang "Xét nghiệm" (Campaign Doctor) —
CPI/ARPU D0 (LTV)/ROAS D0/Retention D1 MỖI APP 1 mốc (không chia theo quốc
gia — mục đích: phân loại nhanh "CPI đắt" hay "User kém" ở tầng 1 xét
nghiệm). Thêm `arpu_d0` (16/09/2026) — CPI+ROAS không đủ để biết ROAS biến
động do CPI hay do LTV, cần benchmark riêng cho LTV (= ARPU D0) để tách 2
nguyên nhân.

⚠️ Lưu vào file JSON trong project — CHƯA bền vững trên Streamlit Cloud (có
thể mất khi app ngủ/redeploy). Coi đây là benchmark tạm, nếu cần bền vững
tuyệt đối cần đổi sang lưu ở nơi khác (VD Google Sheet) — CHƯA làm việc này.

Đã bỏ hẳn benchmark eCPM theo quốc gia (dùng cho "Market Board" cũ) —
22/09/2026, trang đó đã xóa cùng lúc bỏ BigQuery khỏi project (xem
GHI_CHU_TIEN_DO.md).
"""

import json
import os

DOCTOR_BENCHMARK_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "doctor_benchmarks.json"
)
# THÊM "threshold_pct" (23/09/2026) — chuyển ô nhập benchmark (5 ô, gồm cả
# ngưỡng lệch coi là có vấn đề) từ trang Xét nghiệm LÊN SIDEBAR theo yêu cầu
# user ("nhập 1 lần dùng cho mọi tính năng") — lưu CHUNG 1 chỗ với benchmark
# CPI/ARPU/ROAS/Retention cho gọn, dù về bản chất là 1 con số % ngưỡng, không
# phải benchmark tuyệt đối.
DOCTOR_BENCHMARK_KEYS = ["cpi", "arpu_d0", "roas_d0", "retention_d1", "threshold_pct"]


def load_doctor_benchmarks() -> dict:
    """Trả về dict {product_id: {"cpi":..., "arpu_d0":..., "roas_d0":..., "retention_d1":...}}."""
    if os.path.exists(DOCTOR_BENCHMARK_FILE):
        try:
            with open(DOCTOR_BENCHMARK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {pid: v for pid, v in data.items() if isinstance(v, dict)}
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có gì
            return {}
    return {}


def get_doctor_benchmarks(product_id: str) -> dict:
    """Trả về {"cpi":..., "roas_d0":..., "retention_d1":...} của riêng app này.
    Thiếu key nào thì key đó = None (chưa đặt benchmark)."""
    saved = load_doctor_benchmarks().get(product_id, {})
    return {k: saved.get(k) for k in DOCTOR_BENCHMARK_KEYS}


def save_doctor_benchmarks(product_id: str, values: dict) -> None:
    """Ghi đè benchmark CPI/ROAS D0/Retention D1 của 1 app."""
    data = load_doctor_benchmarks()
    data[product_id] = {
        k: float(values[k]) for k in DOCTOR_BENCHMARK_KEYS if values.get(k) is not None
    }
    with open(DOCTOR_BENCHMARK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
