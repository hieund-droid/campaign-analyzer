"""
"Campaign Doctor" — chẩn đoán 1 campaign cụ thể (đang bị cảnh báo ở trang
"Cảnh báo") theo 2 tầng, gắn gợi ý hành động + cắt lát khoanh vùng.

TẦNG 1 — CPI đắt vs User kém: so CPI/ROAS D0/Retention D1 của CHÍNH campaign
(cộng dồn cả khoảng ngày, tính đúng cách — không trung bình cộng trực tiếp)
với BENCHMARK do user tự nhập (xem benchmarks.py — get_doctor_benchmarks()).
- CPI đắt: CPI thực tế CAO HƠN benchmark quá `threshold_pct`%.
- User kém: ROAS D0 HOẶC Retention D1 thực tế THẤP HƠN benchmark quá
  `threshold_pct`% (1 trong 2 thấp là đủ để coi là "user kém").
Có thể vừa CPI đắt vừa User kém cùng lúc (2 vấn đề riêng biệt, không loại
trừ nhau).

TẦNG 2 — nguyên nhân sâu hơn:
- Nhánh CPI đắt: mổ theo công thức phễu CPI = CPM ÷ (CTR × CVR) — CẦN dữ
  liệu BigQuery (Meta CPM/CTR/CVR), CHỈ áp dụng được nếu campaign đã ghép
  được với BigQuery (trích được campaign_id — xem meta_adjust_merge.py). So
  với TRUNG BÌNH CÁC CAMPAIGN KHÁC cùng app/khoảng ngày (peer average, tự
  động tính, không cần benchmark tay) để biết CPM/CTR/CVR cái nào lệch nhiều
  nhất.
- Nhánh User kém: so Retention D1 (giữ chân) vs ROAS D0 (kiếm tiền) với
  benchmark — Retention thấp → vấn đề GIỮ CHÂN; Retention ổn nhưng ROAS D0
  thấp → vấn đề KIẾM TIỀN (monetization).

CẮT LÁT: theo quốc gia (dùng lại dữ liệu Adjust đã kéo, group theo country)
và theo creative (cần gọi thêm 1 lần Adjust API riêng — xem
adjust_client.fetch_creative_summary(), dimension "creative_network" đã
kiểm chứng là dữ liệu thật, không phải suy đoán).
"""

import pandas as pd

import meta_adjust_merge as mam

DEFAULT_THRESHOLD_PCT = 20.0


def period_stats_for_campaign(raw_adjust_df: pd.DataFrame, product_id: str, campaign: str) -> dict | None:
    """Cộng dồn ĐÚNG CÁCH cho 1 campaign, cả khoảng ngày đã kéo, mọi quốc gia."""
    if raw_adjust_df is None or raw_adjust_df.empty:
        return None
    df = raw_adjust_df[
        raw_adjust_df["app"].astype(str).str.startswith(product_id, na=False)
        & (raw_adjust_df["campaign"] == campaign)
    ].copy()
    if df.empty:
        return None

    for col in ("installs", "network_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    installs = df["installs"].sum()
    cost = df["network_cost"].sum()
    revenue_d0 = (pd.to_numeric(df.get("roas_ad_d0"), errors="coerce").fillna(0) * df["network_cost"]).sum()
    retained_d1 = (pd.to_numeric(df.get("retention_rate_d1"), errors="coerce").fillna(0) * df["installs"]).sum()

    return {
        "installs": installs,
        "network_cost": cost,
        "cpi": (cost / installs) if installs else None,
        "roas_d0": (revenue_d0 / cost) if cost else None,
        "retention_d1": (retained_d1 / installs) if installs else None,
    }


def diagnose_tier1(stats: dict, benchmark: dict, threshold_pct: float = DEFAULT_THRESHOLD_PCT) -> dict:
    """benchmark: {"cpi":.., "roas_d0":.., "retention_d1":..} — key nào None
    (chưa nhập) thì BỎ QUA điều kiện đó (không tự đoán benchmark)."""
    cpi_dat = False
    cpi_pct = None
    if stats.get("cpi") is not None and benchmark.get("cpi"):
        cpi_pct = (stats["cpi"] - benchmark["cpi"]) / benchmark["cpi"] * 100
        cpi_dat = cpi_pct > threshold_pct

    roas_pct = None
    roas_kem = False
    if stats.get("roas_d0") is not None and benchmark.get("roas_d0"):
        roas_pct = (stats["roas_d0"] - benchmark["roas_d0"]) / benchmark["roas_d0"] * 100
        roas_kem = roas_pct < -threshold_pct

    retention_pct = None
    retention_kem = False
    if stats.get("retention_d1") is not None and benchmark.get("retention_d1"):
        retention_pct = (stats["retention_d1"] - benchmark["retention_d1"]) / benchmark["retention_d1"] * 100
        retention_kem = retention_pct < -threshold_pct

    return {
        "cpi_dat": cpi_dat,
        "cpi_pct_vs_bench": cpi_pct,
        "user_kem": roas_kem or retention_kem,
        "roas_kem": roas_kem,
        "roas_pct_vs_bench": roas_pct,
        "retention_kem": retention_kem,
        "retention_pct_vs_bench": retention_pct,
    }


def country_slice(raw_adjust_df: pd.DataFrame, product_id: str, campaign: str, min_installs: int = 5) -> pd.DataFrame:
    """Cắt lát theo quốc gia cho ĐÚNG 1 campaign — sắp ROAS D0 thấp nhất lên
    đầu (nghi phạm chính) để dễ soi.

    min_installs: lọc bớt quốc gia quá ít traffic (mặc định 5) — 1-2 install
    dễ ra ROAS D0 = 0.0 (chưa kịp có revenue D0) trông như "tệ nhất" dù không
    có ý nghĩa thống kê gì, đã gặp thật khi test (145 nước, rất nhiều nước chỉ
    1 install)."""
    if raw_adjust_df is None or raw_adjust_df.empty:
        return pd.DataFrame()
    df = raw_adjust_df[
        raw_adjust_df["app"].astype(str).str.startswith(product_id, na=False)
        & (raw_adjust_df["campaign"] == campaign)
    ].copy()
    if df.empty:
        return df

    for col in ("installs", "network_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["_revenue_d0"] = pd.to_numeric(df.get("roas_ad_d0"), errors="coerce").fillna(0) * df["network_cost"]
    df["_retained_d1"] = pd.to_numeric(df.get("retention_rate_d1"), errors="coerce").fillna(0) * df["installs"]

    grouped = df.groupby("country", as_index=False).agg(
        installs=("installs", "sum"),
        network_cost=("network_cost", "sum"),
        _revenue_d0=("_revenue_d0", "sum"),
        _retained_d1=("_retained_d1", "sum"),
    )
    grouped["CPI"] = grouped["network_cost"] / grouped["installs"].replace(0, pd.NA)
    grouped["ROAS D0"] = grouped["_revenue_d0"] / grouped["network_cost"].replace(0, pd.NA)
    grouped["Retention D1"] = grouped["_retained_d1"] / grouped["installs"].replace(0, pd.NA)
    grouped = grouped.rename(columns={"country": "Quốc gia", "installs": "Installs"})
    # Bỏ quốc gia quá ít install (xem docstring) — tránh nhiễu chiếm hết đầu bảng.
    grouped = grouped[grouped["Installs"] >= min_installs]
    return (
        grouped[["Quốc gia", "Installs", "CPI", "ROAS D0", "Retention D1"]]
        .sort_values("ROAS D0")
        .reset_index(drop=True)
    )


def creative_slice(creative_df: pd.DataFrame, campaign: str) -> pd.DataFrame:
    """creative_df: kết quả thô từ adjust_client.fetch_creative_summary() (đã
    parse thành DataFrame) — lọc về ĐÚNG 1 campaign, sắp ROAS D0 thấp nhất lên
    đầu. Adjust ĐÃ tự tổng hợp đúng cho combo (campaign, creative_network) nên
    KHÔNG cần cộng dồn lại ở đây."""
    if creative_df is None or creative_df.empty:
        return pd.DataFrame()
    df = creative_df[creative_df["campaign"] == campaign].copy()
    if df.empty:
        return df
    for col in ("installs", "network_cost", "ecpi_all", "roas_ad_d0", "retention_rate_d1"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.rename(
        columns={
            "creative_network": "Creative",
            "installs": "Installs",
            "ecpi_all": "CPI",
            "roas_ad_d0": "ROAS D0",
            "retention_rate_d1": "Retention D1",
        }
    )
    cols = [c for c in ["Creative", "Installs", "CPI", "ROAS D0", "Retention D1"] if c in df.columns]
    return df[cols].sort_values("ROAS D0").reset_index(drop=True)


def aggregate_bq_rows(bq_df: pd.DataFrame) -> dict:
    """Gộp ĐÚNG CÁCH nhiều dòng BigQuery (day/country) thành 1 bộ CPM/CTR/CVR —
    cộng dồn spend/impressions/clicks/installs rồi chia lại (không trung bình
    cộng trực tiếp cột cpm/ctr_pct/cvr_pct qua nhiều dòng)."""
    if bq_df is None or bq_df.empty:
        return {"cpm": None, "ctr_pct": None, "cvr_pct": None, "cpi": None, "spend": 0, "installs": 0}
    spend = pd.to_numeric(bq_df["spend"], errors="coerce").fillna(0).sum()
    impressions = pd.to_numeric(bq_df["impressions"], errors="coerce").fillna(0).sum()
    clicks = pd.to_numeric(bq_df["clicks"], errors="coerce").fillna(0).sum()
    installs = pd.to_numeric(bq_df["installs"], errors="coerce").fillna(0).sum()
    return {
        "spend": spend,
        "installs": installs,
        "cpm": (spend / impressions * 1000) if impressions else None,
        "ctr_pct": (clicks / impressions * 100) if impressions else None,
        "cvr_pct": (installs / clicks * 100) if clicks else None,
        "cpi": (spend / installs) if installs else None,
    }


def diagnose_tier2_cpi(campaign_bq_row: dict, peer_avg: dict, threshold_pct: float = DEFAULT_THRESHOLD_PCT) -> dict:
    """So CPM/CTR/CVR của campaign với TRUNG BÌNH các campaign khác cùng app/
    khoảng ngày (peer_avg, tự động tính — không cần benchmark tay)."""
    findings = []
    if campaign_bq_row.get("cpm") is not None and peer_avg.get("cpm"):
        pct = (campaign_bq_row["cpm"] - peer_avg["cpm"]) / peer_avg["cpm"] * 100
        if pct > threshold_pct:
            findings.append(("CPM cao hơn trung bình", pct))
    if campaign_bq_row.get("ctr_pct") is not None and peer_avg.get("ctr_pct"):
        pct = (campaign_bq_row["ctr_pct"] - peer_avg["ctr_pct"]) / peer_avg["ctr_pct"] * 100
        if pct < -threshold_pct:
            findings.append(("CTR thấp hơn trung bình", pct))
    if campaign_bq_row.get("cvr_pct") is not None and peer_avg.get("cvr_pct"):
        pct = (campaign_bq_row["cvr_pct"] - peer_avg["cvr_pct"]) / peer_avg["cvr_pct"] * 100
        if pct < -threshold_pct:
            findings.append(("CVR thấp hơn trung bình", pct))
    return {"findings": findings}


SUGGESTION_TEXT = {
    "CPM cao hơn trung bình": "CPM cao hơn các campaign khác → có thể đang đấu giá "
    "audience đắt/cạnh tranh cao — thử mở rộng đối tượng nhắm hoặc đổi khung giờ chạy.",
    "CTR thấp hơn trung bình": "CTR thấp hơn các campaign khác → creative có thể chưa "
    "đủ hấp dẫn để người xem bấm vào — thử đổi creative/hình ảnh mở đầu.",
    "CVR thấp hơn trung bình": "CVR thấp hơn các campaign khác → có click nhưng ít cài "
    "đặt — kiểm tra lại trang store/app hoặc xem targeting có đúng đối tượng không.",
    "retention_kem": "Retention D1 thấp hơn benchmark → user cài xong rồi bỏ sớm — kiểm "
    "tra xem creative có đang hứa hẹn sai với trải nghiệm thật trong app không, hoặc "
    "xem lại phần onboarding.",
    "roas_kem": "Retention ổn nhưng ROAS D0 thấp hơn benchmark → vấn đề có thể nằm ở khả "
    "năng kiếm tiền (ít xem ads, hoặc quốc gia đang chạy có eCPM thấp) — xem thêm ở "
    "Market Board theo quốc gia của campaign này.",
}
