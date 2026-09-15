"""
Phát hiện "đột biến" (spike) và "giảm dần" (gradual decline) cho CPI/ROAS D0
theo TỪNG CAMPAIGN — dùng riêng dữ liệu Adjust (KHÔNG cần ghép BigQuery, nên
áp dụng được cho MỌI channel, không chỉ Meta/Facebook).

Đột biến: so 1 NGÀY GẦN NHẤT với TRUNG BÌNH của `spike_days` ngày TRƯỚC ĐÓ
(mặc định 7 ngày, không tính ngày gần nhất vào trung bình) — lệch quá
`spike_threshold_pct`% (2 chiều, tăng hoặc giảm) thì báo.

Giảm dần: so TRUNG BÌNH `decline_window` ngày GẦN NHẤT (mặc định 7) với TRUNG
BÌNH `decline_window` ngày TRƯỚC ĐÓ NỮA (tổng cộng cần 2×decline_window ngày)
— chỉ báo theo ĐÚNG CHIỀU XẤU: CPI tăng hoặc ROAS D0 giảm quá
`decline_threshold_pct`%.

Cả 2 đều tính CPI/ROAS D0 ĐÚNG CÁCH mỗi khi gộp nhiều ngày/nhiều dòng — cộng
dồn installs/network_cost (và revenue suy từ roas_ad_d0 × network_cost) rồi
chia lại, KHÔNG trung bình cộng trực tiếp cột CPI/ROAS D0 (xem quy tắc đã chốt
trong adjust_client.py — sai số 3-4% nếu làm sai).

`min_installs`: lọc bớt campaign quá ít traffic trong CẢ khoảng ngày đã kéo —
tránh báo động giả (mẫu nhỏ, 1-2 install cũng đủ làm CPI/ROAS nhảy vọt vô nghĩa).
"""

import pandas as pd


def build_campaign_daily(adjust_df: pd.DataFrame, product_id: str) -> pd.DataFrame:
    """Gộp dữ liệu Adjust (app,day,campaign,country) về grain campaign+day —
    bỏ quốc gia (tính năng này chỉ theo dõi theo campaign, không chia quốc gia)."""
    if adjust_df is None or adjust_df.empty:
        return pd.DataFrame()

    df = adjust_df[adjust_df["app"].astype(str).str.startswith(product_id, na=False)].copy()
    if df.empty:
        return df

    for col in ("installs", "network_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["_revenue_d0"] = pd.to_numeric(df.get("roas_ad_d0"), errors="coerce").fillna(0) * df["network_cost"]

    grouped = df.groupby(["campaign", "day"], as_index=False).agg(
        installs=("installs", "sum"),
        network_cost=("network_cost", "sum"),
        _revenue_d0=("_revenue_d0", "sum"),
    )
    grouped["cpi"] = grouped["network_cost"] / grouped["installs"].replace(0, pd.NA)
    grouped["roas_ad_d0"] = grouped["_revenue_d0"] / grouped["network_cost"].replace(0, pd.NA)
    return grouped.drop(columns=["_revenue_d0"]).sort_values(["campaign", "day"])


def _weighted_cpi_roas(g: pd.DataFrame):
    installs = g["installs"].sum()
    cost = g["network_cost"].sum()
    revenue_d0 = (g["roas_ad_d0"].fillna(0) * g["network_cost"]).sum()
    cpi = (cost / installs) if installs else None
    roas = (revenue_d0 / cost) if cost else None
    return cpi, roas


def analyze_campaigns(
    daily_df: pd.DataFrame,
    min_installs: int = 30,
    spike_days: int = 7,
    spike_threshold_pct: float = 30.0,
    decline_window: int = 7,
    decline_threshold_pct: float = 20.0,
) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()

    rows = []
    for campaign, g in daily_df.groupby("campaign"):
        g = g.sort_values("day").reset_index(drop=True)
        total_installs = g["installs"].sum()
        if total_installs < min_installs:
            continue

        latest = g.iloc[-1]
        cpi_spike_pct = roas_spike_pct = None
        if len(g) >= spike_days + 1:
            baseline = g.iloc[-(spike_days + 1):-1]
            base_cpi, base_roas = _weighted_cpi_roas(baseline)
            if base_cpi is not None and base_cpi != 0 and pd.notna(latest["cpi"]):
                cpi_spike_pct = (latest["cpi"] - base_cpi) / base_cpi * 100
            if base_roas is not None and base_roas != 0 and pd.notna(latest["roas_ad_d0"]):
                roas_spike_pct = (latest["roas_ad_d0"] - base_roas) / base_roas * 100

        cpi_decline_pct = roas_decline_pct = None
        if len(g) >= decline_window * 2:
            recent = g.iloc[-decline_window:]
            previous = g.iloc[-decline_window * 2 : -decline_window]
            recent_cpi, recent_roas = _weighted_cpi_roas(recent)
            prev_cpi, prev_roas = _weighted_cpi_roas(previous)
            if prev_cpi is not None and prev_cpi != 0 and recent_cpi is not None:
                cpi_decline_pct = (recent_cpi - prev_cpi) / prev_cpi * 100
            if prev_roas is not None and prev_roas != 0 and recent_roas is not None:
                roas_decline_pct = (recent_roas - prev_roas) / prev_roas * 100

        flags = []
        if cpi_spike_pct is not None and cpi_spike_pct >= spike_threshold_pct:
            flags.append("🔴 CPI tăng đột biến")
        elif cpi_spike_pct is not None and cpi_spike_pct <= -spike_threshold_pct:
            flags.append("🟢 CPI giảm đột biến")
        if roas_spike_pct is not None and roas_spike_pct <= -spike_threshold_pct:
            flags.append("🔴 ROAS D0 tụt đột biến")
        elif roas_spike_pct is not None and roas_spike_pct >= spike_threshold_pct:
            flags.append("🟢 ROAS D0 tăng đột biến")
        if cpi_decline_pct is not None and cpi_decline_pct >= decline_threshold_pct:
            flags.append("🟠 CPI tăng dần")
        if roas_decline_pct is not None and roas_decline_pct <= -decline_threshold_pct:
            flags.append("🟠 ROAS D0 giảm dần")

        rows.append(
            {
                "Campaign": campaign,
                "Installs (cả khoảng)": int(total_installs),
                "CPI gần nhất": round(latest["cpi"], 4) if pd.notna(latest["cpi"]) else None,
                "CPI % lệch vs TB 7 ngày trước": round(cpi_spike_pct, 1) if cpi_spike_pct is not None else None,
                "ROAS D0 gần nhất": round(latest["roas_ad_d0"], 4) if pd.notna(latest["roas_ad_d0"]) else None,
                "ROAS D0 % lệch vs TB 7 ngày trước": round(roas_spike_pct, 1) if roas_spike_pct is not None else None,
                "CPI % đổi (7 ngày vs 7 ngày trước đó)": round(cpi_decline_pct, 1) if cpi_decline_pct is not None else None,
                "ROAS D0 % đổi (7 ngày vs 7 ngày trước đó)": round(roas_decline_pct, 1) if roas_decline_pct is not None else None,
                "Cảnh báo": " · ".join(flags) if flags else "Bình thường",
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    # Campaign có cảnh báo lên đầu — "Bình thường" xuống cuối.
    return result.sort_values(by="Cảnh báo", key=lambda s: s.eq("Bình thường")).reset_index(drop=True)
