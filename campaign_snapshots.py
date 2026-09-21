"""
Lưu lại "ảnh chụp" CPI/ROAS D0/ARPU D0 theo TỪNG CAMPAIGN tại nhiều thời điểm
TRONG NGÀY — giải quyết nỗi đau UA: sáng thấy ROAS tốt, chiều thấy tụt nhưng
không nhớ số buổi sáng để so sánh, đánh giá xem có thật sự đáng lo không.

CÁCH CHỤP: KHÔNG chạy nền 24/7 (không khả thi — token Adjust không lưu tập
trung, mỗi người tự nhập, không có tiến trình nền nào dùng được token khi
không ai mở app). Thay vào đó: MỖI LẦN người dùng xem dữ liệu "Hôm nay" (include
_today=True) trên trang Adjust, tự động lưu 1 snapshot nếu đã cách lần chụp
gần nhất của NGÀY HÔM NAY tối thiểu `MIN_INTERVAL_HOURS` tiếng. Vì UA vốn tự
vào xem nhiều lần trong ngày, cách này cho hiệu quả gần giống "chụp theo lịch"
mà không cần hạ tầng chạy nền.

⚠️ Lưu vào file JSON trong project — CHƯA bền vững trên Streamlit Cloud (có
thể mất khi app ngủ/redeploy giữa các lần chụp trong ngày, giống benchmark —
xem benchmarks.py). Đã được user chấp nhận đánh đổi này (16/09/2026) để làm
nhanh, ưu tiên có tính năng hơn là bền vững tuyệt đối.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

SNAPSHOT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campaign_snapshots.json")
MIN_INTERVAL_HOURS = 3
VN_TZ = timezone(timedelta(hours=7))


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


def today_str_vn() -> str:
    """Ngày hôm nay dạng YYYY-MM-DD theo giờ VN — dùng để tách dòng "hôm nay"
    (chưa chốt) ra khỏi dòng ngày đã chốt trong dữ liệu Adjust (cả 2 đều đã
    gọi API với utc_offset=+07:00 nên cột "day" luôn theo lịch VN)."""
    return _now_vn().strftime("%Y-%m-%d")


def load_snapshots() -> dict:
    """{app_key: {campaign: [{"ts": iso-string, "installs":, "cpi":, "roas_d0":, "arpu_d0":}, ...]}}"""
    if os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001 — file hỏng/rỗng, coi như chưa có gì
            return {}
    return {}


def _save_all(data: dict) -> None:
    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_snapshot_app_keys() -> list:
    """Liệt kê mọi app_key (field "app" thật của Adjust) đã từng có snapshot —
    dùng làm fallback khi không có sẵn danh sách app trong df hiện tại (VD
    lịch sử nhiều ngày rỗng nhưng đã từng chụp snapshot hôm nay từ trước)."""
    return list(load_snapshots().keys())


def get_campaign_snapshots(app_key: str, campaign: str) -> list:
    """Trả về TOÀN BỘ snapshot đã lưu của 1 campaign (mọi ngày), sắp theo thời
    gian tăng dần."""
    campaigns = load_snapshots().get(app_key, {})
    return sorted(campaigns.get(campaign, []), key=lambda s: s["ts"])


def get_today_snapshots(app_key: str, campaign: str) -> list:
    """Chỉ snapshot của HÔM NAY (giờ VN) — dùng để so sáng/chiều CÙNG 1 ngày,
    không lẫn dữ liệu hôm qua."""
    today_str = _now_vn().strftime("%Y-%m-%d")
    return [s for s in get_campaign_snapshots(app_key, campaign) if s["ts"].startswith(today_str)]


def _to_native(v):
    """Ép kiểu numpy (int64/float64 từ pandas) về Python thuần — json.dump()
    không tự serialize được kiểu numpy (đã gặp lỗi thật khi test)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return float(v)


def maybe_capture_snapshots(app_key: str, campaign_stats: dict, min_interval_hours: float = MIN_INTERVAL_HOURS) -> int:
    """campaign_stats: {campaign_name: {"installs":, "cpi":, "roas_d0":, "arpu_d0":}}
    — chụp lại CHỈ những campaign đã cách lần chụp gần nhất (hôm nay) đủ
    `min_interval_hours` tiếng, hoặc chưa từng chụp hôm nay. Bỏ qua campaign có
    installs=0 (chưa có gì để chụp). Trả về SỐ campaign vừa được chụp mới."""
    if not campaign_stats:
        return 0

    data = load_snapshots()
    product_snaps = data.setdefault(app_key, {})
    now = _now_vn()
    now_iso = now.isoformat()
    captured = 0

    for campaign, stats in campaign_stats.items():
        if not stats.get("installs"):
            continue
        history = product_snaps.setdefault(campaign, [])
        today_snaps = [s for s in history if s["ts"].startswith(now.strftime("%Y-%m-%d"))]
        if today_snaps:
            last_ts = max(datetime.fromisoformat(s["ts"]) for s in today_snaps)
            if now - last_ts < timedelta(hours=min_interval_hours):
                continue
        history.append(
            {
                "ts": now_iso,
                "installs": _to_native(stats.get("installs")),
                "cpi": _to_native(stats.get("cpi")),
                "roas_d0": _to_native(stats.get("roas_d0")),
                "arpu_d0": _to_native(stats.get("arpu_d0")),
            }
        )
        captured += 1

    if captured:
        _save_all(data)
    return captured


def compare_today(app_key: str, campaign: str) -> dict | None:
    """So snapshot ĐẦU TIÊN hôm nay (thường = buổi sáng) với snapshot MỚI
    NHẤT hôm nay (thường = hiện tại) — trả về None nếu chưa đủ 2 snapshot."""
    today_snaps = sorted(get_today_snapshots(app_key, campaign), key=lambda s: s["ts"])
    if len(today_snaps) < 2:
        return None

    first, last = today_snaps[0], today_snaps[-1]

    def _pct(a, b):
        if a is None or b is None or a == 0:
            return None
        return (b - a) / a * 100

    return {
        "first_ts": first["ts"],
        "last_ts": last["ts"],
        "first": first,
        "last": last,
        "cpi_pct_change": _pct(first.get("cpi"), last.get("cpi")),
        "roas_d0_pct_change": _pct(first.get("roas_d0"), last.get("roas_d0")),
        "arpu_d0_pct_change": _pct(first.get("arpu_d0"), last.get("arpu_d0")),
        "n_snapshots": len(today_snaps),
    }


def list_flagged_today(app_key: str, threshold_pct: float = 20.0, min_installs: int = 0) -> list:
    """CẢNH BÁO TRONG NGÀY (thời gian thực) — khác hẳn phân tích ngày/tuần đã
    chốt: so snapshot ĐẦU TIÊN hôm nay (thường = sáng) với MỚI NHẤT (thường =
    bây giờ) cho MỌI campaign đã từng được chụp hôm nay, gắn cờ nếu CPI TĂNG
    hoặc ROAS D0/ARPU D0 GIẢM vượt threshold_pct% — để UA phát hiện + xử lý
    ngay trong ngày (VD sáng CPI rẻ, chiều tăng vọt), không phải đợi qua ngày
    hôm sau mới thấy ở "Cảnh báo theo xu hướng"."""
    data = load_snapshots()
    campaigns = data.get(app_key, {})
    flagged = []
    for campaign in campaigns:
        cmp = compare_today(app_key, campaign)
        if not cmp:
            continue
        if min_installs and (cmp["last"].get("installs") or 0) < min_installs:
            continue
        cpi_bad = cmp["cpi_pct_change"] is not None and cmp["cpi_pct_change"] >= threshold_pct
        roas_bad = cmp["roas_d0_pct_change"] is not None and cmp["roas_d0_pct_change"] <= -threshold_pct
        arpu_bad = cmp["arpu_d0_pct_change"] is not None and cmp["arpu_d0_pct_change"] <= -threshold_pct
        if cpi_bad or roas_bad or arpu_bad:
            flagged.append({"campaign": campaign, "cpi_bad": cpi_bad, "roas_bad": roas_bad, "arpu_bad": arpu_bad, **cmp})
    return sorted(flagged, key=lambda f: f.get("roas_d0_pct_change") or 0)
