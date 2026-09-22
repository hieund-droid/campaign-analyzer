"""
So sánh CPI/ROAS D0/LTV (ARPU D0) "bây giờ" vs "N tiếng trước" (hoặc 1 giờ cụ
thể trong ngày, VD 8h) NGAY TRONG NGÀY — kéo TRỰC TIẾP dimension "hour" của
Adjust (adjust_client.fetch_hourly_today).

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

⚠️ QUAN TRỌNG — vì sao CPI % đổi và LTV (ARPU D0) % đổi CÓ THỂ giống hệt nhau
trong khi ROAS D0 % đổi = 0.0% (user hỏi 23/09/2026, tưởng là bug — ĐÃ KIỂM
CHỨNG bằng đại số, KHÔNG phải bug): vì ROAS_D0 = ARPU_D0 ÷ CPI LUÔN LUÔN đúng
(cả 2 cùng chia cho installs, installs bị triệt tiêu khi lấy tỉ số) — nên hễ
ROAS_D0 không đổi, % đổi của CPI và ARPU_D0 BẮT BUỘC phải bằng nhau, đây là hệ
quả TOÁN HỌC, không phải trùng hợp hay lỗi tính. Nguyên nhân THỰC TẾ hay gặp
nhất khiến ROAS đứng yên trong khi CPI/ARPU cùng đổi: chi phí (network_cost)
và doanh thu D0 giữa 2 mốc KHÔNG ĐỔI (network network chưa kịp báo cáo chi phí
mới — chi phí ads thường có ĐỘ TRỄ báo cáo vài tiếng so với installs, vốn gần
như tức thời), trong khi installs vẫn tăng — CPI/ARPU (chia cho installs) đều
giảm cùng tỉ lệ, còn ROAS (= doanh thu ÷ chi phí, KHÔNG phụ thuộc installs) thì
đứng yên. `list_flagged_hours_ago()`/`list_flagged_since_hour()` trả kèm
installs/chi phí thô ở 2 mốc (baseline/latest) để tự kiểm tra giả thuyết này.

⚠️ Số của giờ HIỆN TẠI vẫn đang chạy (chưa hết giờ) — coi là "tạm thời", sẽ còn
tăng đến hết giờ đó, giống bản chất số "hôm nay" nói chung.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

VN_TZ = timezone(timedelta(hours=7))
# THÊM mốc 6 tiếng (23/09/2026) — đã xác nhận bằng đối chiếu chéo với user
# thật: Adjust chỉ lấy chi phí quảng cáo từ network ~6 lần/ngày (trung bình
# ~4 tiếng/lần), nên so ở mốc 1/2/3 tiếng RẤT HAY rơi vào giữa 2 lần cập nhật
# (chi phí đứng yên, xem docstring _flag_entry()). Giữ 1/2/3 để vẫn bắt được
# biến động nhanh khi CÓ chi phí mới, thêm 6 để tăng khả năng bắt được ít
# nhất 1 mốc có chi phí đã thật sự cập nhật.
DEFAULT_HOURS_AGO = (1, 2, 3, 6)


def _pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b - a) / a * 100


def build_cumulative_by_hour(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Input: df thô từ adjust_client.fetch_hourly_today() (cột app, hour,
    campaign, installs, network_cost, roas_ad_d0, ...). Output: thêm các cột
    CỘNG DỒN từ đầu ngày đến hết mỗi giờ: installs_cum, cost_cum,
    revenue_d0_cum, cpi, roas_d0, arpu_d0 (suy ra từ số ĐÃ cộng dồn).

    Trả về NGUYÊN VẸN nếu df rỗng (VD vừa qua nửa đêm, chưa có install nào
    hôm nay) — tránh KeyError do df rỗng không có cột nào để đọc."""
    if hourly_df is None or hourly_df.empty:
        return hourly_df
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


def _compare_to_target(cum_df: pd.DataFrame, app: str, campaign: str, target_dt: datetime) -> dict | None:
    """Lõi dùng chung: so giờ MỚI NHẤT (đang chạy) với giờ đã có dữ liệu GẦN
    `target_dt` nhất. Trả về None nếu campaign chưa có nổi 2 giờ dữ liệu khác
    nhau hôm nay (VD vừa qua nửa đêm)."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if len(hours_sorted) < 2:
        return None

    latest_hour = hours_sorted[-1]
    latest = g[g["hour"] == latest_hour].iloc[0]
    latest_dt = datetime.fromisoformat(latest_hour)

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


def compare_hours_ago(cum_df: pd.DataFrame, app: str, campaign: str, hours_ago: float) -> dict | None:
    """So giờ MỚI NHẤT với giờ GẦN mốc `hours_ago` tiếng TRƯỚC GIỜ MỚI NHẤT
    (không phải trước giờ hiện tại thực — nếu dữ liệu mới nhất đã trễ vài
    phút, mốc vẫn tính từ đó) nhất trong số các giờ đã có dữ liệu hôm nay."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if not hours_sorted:
        return None
    latest_dt = datetime.fromisoformat(hours_sorted[-1])
    target_dt = latest_dt - timedelta(hours=hours_ago)
    return _compare_to_target(cum_df, app, campaign, target_dt)


def compare_since_hour(cum_df: pd.DataFrame, app: str, campaign: str, baseline_hour_of_day: int) -> dict | None:
    """So giờ MỚI NHẤT với 1 GIỜ CỤ THỂ trong ngày hôm nay (VD baseline_hour_of_day=8
    → so với ~8h sáng) — THAY THẾ mốc cố định "0h" (nửa đêm gần như không có
    hoạt động, so với nó ra % đổi cực đoan vô nghĩa, user phản ánh 23/09/2026).
    Tự chọn giờ ĐÃ CÓ DỮ LIỆU gần `baseline_hour_of_day` nhất (không nhất thiết
    đúng tuyệt đối vì Adjust có thể thiếu 1 vài giờ)."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if not hours_sorted:
        return None
    latest_dt = datetime.fromisoformat(hours_sorted[-1])
    target_dt = latest_dt.replace(hour=int(baseline_hour_of_day), minute=0, second=0, microsecond=0)
    return _compare_to_target(cum_df, app, campaign, target_dt)


def _flag_entry(app: str, campaign: str, cmp: dict, threshold_pct: float, min_installs: int, target_label) -> dict | None:
    if cmp is None:
        return None
    if min_installs and (cmp["latest"].get("installs_cum") or 0) < min_installs:
        return None
    cpi_bad = cmp["cpi_pct_change"] is not None and cmp["cpi_pct_change"] >= threshold_pct
    roas_bad = cmp["roas_d0_pct_change"] is not None and cmp["roas_d0_pct_change"] <= -threshold_pct
    arpu_bad = cmp["arpu_d0_pct_change"] is not None and cmp["arpu_d0_pct_change"] <= -threshold_pct
    if not (cpi_bad or roas_bad or arpu_bad):
        return None
    # ĐÃ KIỂM CHỨNG bằng đối chiếu chéo với user thật (23/09/2026): khi chi phí
    # (cost_cum) KHÔNG đổi giữa 2 mốc, CPI/ARPU đổi chỉ do installs bị pha
    # loãng — KHÔNG phải campaign đổi chất lượng thật. Đánh dấu rõ để ưu tiên
    # chọn mốc có chi phí ĐÃ cập nhật khi có nhiều mốc cùng vượt ngưỡng (xem
    # list_flagged_hours_ago()).
    cost_b = cmp["baseline"].get("cost_cum") or 0
    cost_l = cmp["latest"].get("cost_cum") or 0
    cost_changed = abs(cost_b - cost_l) >= 0.01
    return {
        "app": app, "campaign": campaign, "target": target_label,
        "cpi_bad": cpi_bad, "roas_bad": roas_bad, "arpu_bad": arpu_bad,
        "cost_changed": cost_changed,
        **cmp,
    }


def list_flagged_hours_ago(
    cum_df: pd.DataFrame,
    hours_ago_list: tuple = DEFAULT_HOURS_AGO,
    threshold_pct: float = 20.0,
    min_installs: int = 0,
) -> list:
    """CẢNH BÁO TRONG NGÀY — kiểm tra các mốc 1/2/3/6 tiếng trước (mặc định),
    gắn cờ nếu BẤT KỲ mốc nào cho thấy CPI TĂNG hoặc ROAS D0/ARPU D0 GIẢM vượt
    threshold_pct%. Mỗi campaign chỉ trả về 1 dòng — ƯU TIÊN mốc có chi phí ĐÃ
    THẬT SỰ cập nhật (cost_changed=True, đáng tin hơn — xem _flag_entry()),
    trong số đó chọn ROAS D0 giảm NHIỀU NHẤT; nếu KHÔNG mốc nào có chi phí
    cập nhật, đành chọn mốc ROAS giảm nhiều nhất trong số còn lại (vẫn hiện,
    có nhãn cảnh báo riêng ở UI)."""
    if cum_df is None or cum_df.empty:
        return []
    flagged = []
    for (app, campaign), _ in cum_df.groupby(["app", "campaign"]):
        candidates = []
        for h in hours_ago_list:
            entry = _flag_entry(app, campaign, compare_hours_ago(cum_df, app, campaign, h), threshold_pct, min_installs, h)
            if entry is not None:
                candidates.append(entry)
        if not candidates:
            continue
        cost_changed_candidates = [e for e in candidates if e["cost_changed"]]
        pool = cost_changed_candidates or candidates
        worst = min(pool, key=lambda e: e.get("roas_d0_pct_change") if e.get("roas_d0_pct_change") is not None else 0)
        flagged.append(worst)
    return sorted(flagged, key=lambda f: f.get("roas_d0_pct_change") or 0)


def list_flagged_since_hour(
    cum_df: pd.DataFrame,
    baseline_hour_of_day: int = 8,
    threshold_pct: float = 20.0,
    min_installs: int = 0,
) -> list:
    """So với 1 GIỜ CỤ THỂ user tự chọn trong ngày (mặc định 8h) — THAY THẾ
    `list_flagged_since_day_start()` cũ (cố định 0h, không hữu ích vì nửa đêm
    gần như không có hoạt động — user phản ánh 23/09/2026)."""
    if cum_df is None or cum_df.empty:
        return []
    flagged = []
    for (app, campaign), _ in cum_df.groupby(["app", "campaign"]):
        cmp = compare_since_hour(cum_df, app, campaign, baseline_hour_of_day)
        entry = _flag_entry(app, campaign, cmp, threshold_pct, min_installs, baseline_hour_of_day)
        if entry:
            flagged.append(entry)
    return sorted(flagged, key=lambda f: f.get("roas_d0_pct_change") or 0)
