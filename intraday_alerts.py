"""
So sánh CPI/ROAS D0/LTV (ARPU D0) "bây giờ" vs "N tiếng trước" NGAY TRONG NGÀY
— kéo TRỰC TIẾP dimension "hour" của Adjust (adjust_client.fetch_hourly_today).

THAY THẾ HẲN (22/09/2026) cơ chế "chụp snapshot" cũ (`campaign_snapshots.py` +
`background_capture.py`, đã xóa): cơ chế cũ chỉ ghi được số tại những THỜI ĐIỂM
có người mở app (hoặc tiến trình chạy ngầm, vốn cũng cần app "còn sống") — nên
lỗi "chưa đủ 2 lần chụp" rất hay gặp, và độ chính xác phụ thuộc may rủi (ai mở
app lúc mấy giờ). Đã kiểm chứng bằng số thật: Adjust TỰ LƯU SẴN lịch sử theo
giờ — hỏi lúc nào cũng ra đúng số của giờ đó trong quá khứ, cộng dồn từ 0h đến
giờ X khớp 100% với tổng theo ngày Adjust tự tính (app AAP874, hôm qua: cộng 24
dòng theo giờ = 47 installs, khớp đúng tổng "app,day" cũng ra 47). Nên KHÔNG
cần tự lưu trữ/chụp/chạy ngầm gì nữa — mỗi lần bấm Apply, gọi thẳng Adjust là
đủ dữ liệu để so bất kỳ mốc giờ nào trong ngày.

CÁCH TÍNH: mỗi dòng Adjust trả về (dimension "hour") là số PHÁT SINH TRONG giờ
đó, KHÔNG PHẢI cộng dồn — build_cumulative_by_hour() tự cộng dồn theo (app,
campaign) rồi tính lại CPI/ROAS D0/ARPU D0 từ số ĐÃ CỘNG DỒN (đúng cách — KHÔNG
lấy trung bình cộng cột tỉ lệ qua nhiều giờ, xem RATIO_COLS ở adjust_client.py
để biết vì sao sai).

⚠️ Số của giờ HIỆN TẠI vẫn đang chạy (chưa hết giờ) — coi là "tạm thời", sẽ còn
tăng đến hết giờ đó, giống bản chất số "hôm nay" nói chung.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

VN_TZ = timezone(timedelta(hours=7))
DEFAULT_HOURS_AGO = (1, 2, 3)


def _pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b - a) / a * 100


def build_cumulative_by_hour(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Input: df thô từ adjust_client.fetch_hourly_today() (cột app, hour,
    campaign, installs, network_cost, roas_ad_d0, ...). Output: thêm các cột
    CỘNG DỒN từ đầu ngày đến hết mỗi giờ: installs_cum, cost_cum,
    revenue_d0_cum, cpi, roas_d0, arpu_d0 (suy ra từ số ĐÃ cộng dồn)."""
    df = hourly_df.copy()
    for col in ("installs", "network_cost", "roas_ad_d0"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["revenue_d0"] = df["roas_ad_d0"] * df["network_cost"]
    df = df.sort_values("hour")
    grp = df.groupby(["app", "campaign"], group_keys=False)
    df["installs_cum"] = grp["installs"].cumsum()
    df["cost_cum"] = grp["network_cost"].cumsum()
    df["revenue_d0_cum"] = grp["revenue_d0"].cumsum()
    df["cpi"] = df["cost_cum"] / df["installs_cum"].replace(0, pd.NA)
    df["roas_d0"] = df["revenue_d0_cum"] / df["cost_cum"].replace(0, pd.NA)
    df["arpu_d0"] = df["revenue_d0_cum"] / df["installs_cum"].replace(0, pd.NA)
    return df


def compare_hours_ago(cum_df: pd.DataFrame, app: str, campaign: str, hours_ago: float) -> dict | None:
    """So giờ MỚI NHẤT (đang chạy) với giờ GẦN mốc `hours_ago` tiếng trước
    nhất (trong số các giờ đã có dữ liệu hôm nay cho campaign này). Trả về
    None nếu campaign chưa có nổi 2 giờ dữ liệu khác nhau (VD vừa qua nửa
    đêm). `hours_ago` lớn hơn số giờ đã qua trong ngày (VD 24) sẽ tự động lấy
    giờ SỚM NHẤT có dữ liệu làm gốc — dùng để so "từ đầu ngày đến giờ"."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if len(hours_sorted) < 2:
        return None

    latest_hour = hours_sorted[-1]
    latest = g[g["hour"] == latest_hour].iloc[0]
    latest_dt = datetime.fromisoformat(latest_hour)
    target_dt = latest_dt - timedelta(hours=hours_ago)

    earlier_hours = hours_sorted[:-1]
    baseline_hour = min(earlier_hours, key=lambda h: abs((datetime.fromisoformat(h) - target_dt).total_seconds()))
    baseline = g[g["hour"] == baseline_hour].iloc[0]
    actual_hours_gap = (latest_dt - datetime.fromisoformat(baseline_hour)).total_seconds() / 3600

    return {
        "baseline_ts": baseline_hour,
        "latest_ts": latest_hour,
        "baseline": baseline.to_dict(),
        "latest": latest.to_dict(),
        "actual_hours_gap": round(actual_hours_gap, 1),
        "cpi_pct_change": _pct(baseline["cpi"], latest["cpi"]),
        "roas_d0_pct_change": _pct(baseline["roas_d0"], latest["roas_d0"]),
        "arpu_d0_pct_change": _pct(baseline["arpu_d0"], latest["arpu_d0"]),
    }


def list_flagged_hours_ago(
    cum_df: pd.DataFrame,
    hours_ago_list: tuple = DEFAULT_HOURS_AGO,
    threshold_pct: float = 20.0,
    min_installs: int = 0,
) -> list:
    """CẢNH BÁO TRONG NGÀY — kiểm tra CẢ 3 mốc 1/2/3 tiếng trước (mặc định),
    gắn cờ nếu BẤT KỲ mốc nào cho thấy CPI TĂNG hoặc ROAS D0/ARPU D0 GIẢM vượt
    threshold_pct%. Mỗi campaign chỉ trả về 1 dòng — chọn mốc có ROAS D0 giảm
    NHIỀU NHẤT (nghi phạm rõ nhất) trong số các mốc đã vượt ngưỡng."""
    if cum_df is None or cum_df.empty:
        return []
    flagged = []
    for (app, campaign), _ in cum_df.groupby(["app", "campaign"]):
        worst = None
        for h in hours_ago_list:
            cmp = compare_hours_ago(cum_df, app, campaign, h)
            if not cmp:
                continue
            if min_installs and (cmp["latest"].get("installs_cum") or 0) < min_installs:
                continue
            cpi_bad = cmp["cpi_pct_change"] is not None and cmp["cpi_pct_change"] >= threshold_pct
            roas_bad = cmp["roas_d0_pct_change"] is not None and cmp["roas_d0_pct_change"] <= -threshold_pct
            arpu_bad = cmp["arpu_d0_pct_change"] is not None and cmp["arpu_d0_pct_change"] <= -threshold_pct
            if not (cpi_bad or roas_bad or arpu_bad):
                continue
            entry = {
                "app": app, "campaign": campaign, "hours_ago_target": h,
                "cpi_bad": cpi_bad, "roas_bad": roas_bad, "arpu_bad": arpu_bad,
                **cmp,
            }
            worst_roas = worst.get("roas_d0_pct_change") if worst else None
            entry_roas = entry.get("roas_d0_pct_change")
            if worst is None or (entry_roas is not None and (worst_roas is None or entry_roas < worst_roas)):
                worst = entry
        if worst:
            flagged.append(worst)
    return sorted(flagged, key=lambda f: f.get("roas_d0_pct_change") or 0)


def list_flagged_since_day_start(cum_df: pd.DataFrame, threshold_pct: float = 20.0, min_installs: int = 0) -> list:
    """So với giờ SỚM NHẤT có dữ liệu hôm nay (thường = 0h) — thay thế
    `list_flagged_today` cũ (so với "lần đầu ai đó mở app hôm nay", vốn phụ
    thuộc may rủi). Dùng hours_ago=24 (lớn hơn mọi khoảng cách có thể có trong
    ngày) để compare_hours_ago tự chọn giờ sớm nhất làm gốc — xem docstring đó."""
    return list_flagged_hours_ago(cum_df, hours_ago_list=(24,), threshold_pct=threshold_pct, min_installs=min_installs)
