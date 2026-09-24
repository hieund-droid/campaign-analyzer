"""
"Campaign Doctor" — chẩn đoán 1 campaign cụ thể (đang bị cảnh báo ở trang
"Cảnh báo") theo 2 tầng, gắn gợi ý hành động + cắt lát khoanh vùng.

TẦNG 1 — CPI đắt vs User kém: so CPI/ARPU D0 (LTV)/ROAS D0/Retention D1 của
CHÍNH campaign (cộng dồn cả khoảng ngày, tính đúng cách — không trung bình
cộng trực tiếp) với BENCHMARK. ĐỔI 23/09/2026: benchmark giờ nhập THEO QUỐC
GIA (xem benchmarks.py — get_all_country_benchmarks()), KHÔNG còn benchmark
app-level — Tầng 1 (gộp cả campaign) không còn benchmark để so nữa, việc so
benchmark chỉ còn ở hàm country_slice() bên dưới (mỗi quốc gia so với benchmark
của chính nó). `diagnose_tier1()` vẫn giữ nguyên để dùng cho country_slice().
- CPI đắt: CPI thực tế CAO HƠN benchmark quá `threshold_pct`%.
- User kém: ARPU D0 (LTV) HOẶC Retention D1 HOẶC ROAS D0 thực tế THẤP HƠN
  benchmark quá `threshold_pct`% (1 trong 3 thấp là đủ để coi là "user kém").
  Tách riêng ARPU D0 (= LTV tại D0) khỏi ROAS D0 — vì ROAS D0 = ARPU D0 ÷ CPI,
  1 mình ROAS D0 KHÔNG tách được ROAS xấu là do CPI đắt lên hay do LTV tụt
  xuống (user chỉ ra đúng vấn đề này 16/09/2026) — theo dõi cả 2 riêng biệt để
  biết CHÍNH XÁC lever nào đang có vấn đề. (Benchmark theo quốc gia hiện CHỈ
  còn CPI + ARPU D0 — ROAS D0/Retention D1 benchmark đã bỏ 23/09/2026, "chỉ
  cần biết về CPI và LTV thôi" — `diagnose_tier1()` vẫn nhận đủ 4 key, chỉ là
  2 key roas_d0/retention_d1 sẽ luôn None nên tự bỏ qua điều kiện đó.)
Có thể vừa CPI đắt vừa User kém cùng lúc (2 vấn đề riêng biệt, không loại
trừ nhau).

TẦNG 2 — nguyên nhân sâu hơn:
- Nhánh CPI đắt: mổ theo công thức phễu CPI = CPM ÷ (CTR × CVR). TRƯỚC ĐÂY
  (đến 21/09/2026) cần ghép BigQuery (Meta CPM/CTR/CVR) mới có dữ liệu này.
  ĐÃ BỎ BigQuery hẳn (22/09/2026 — user chỉ ra BigQuery không có realtime nên
  vô dụng cho Cảnh báo/Xét nghiệm) — kiểm tra lại thì Adjust CÓ SẴN
  `network_impressions`/`network_clicks` (network tự báo cáo, cùng nguồn với
  network_cost đã dùng từ đầu) — đủ để tự tính CPM/CTR/CVR, KHÔNG cần
  BigQuery/ghép campaign_id gì nữa (xem `aggregate_adjust_funnel()`). So với
  TRUNG BÌNH CÁC CAMPAIGN KHÁC cùng app/khoảng ngày (peer average, tự động
  tính, không cần benchmark tay) để biết CPM/CTR/CVR cái nào lệch nhiều nhất.
- Nhánh User kém: so Retention D1 (giữ chân) vs ROAS D0 (kiếm tiền) với
  benchmark — Retention thấp → vấn đề GIỮ CHÂN; Retention ổn nhưng ROAS D0
  thấp → vấn đề KIẾM TIỀN (monetization).

TẦNG 2 — HỒI SINH 24/09/2026 với thiết kế MỚI (bản cũ dùng `tier1["cpi_dat"]`/
`tier1["user_kem"]` của campaign gộp — từ 23/09/2026 benchmark Tầng 1 luôn
rỗng nên 2 cờ này LUÔN False, Tầng 2 ÂM THẦM không hiện ra nữa, user phát
hiện lại 24/09/2026). Bản mới KHÔNG dùng benchmark gộp cả campaign nữa — xem
`top_markets_slice()`: tự lấy TOP N thị trường (quốc gia) đang TIÊU NHIỀU
NHẤT trong CHÍNH campaign này, so CPI/LTV của MỖI thị trường đó với benchmark
CỦA CHÍNH NÓ. Cách này chạy ĐÚNG cho CẢ campaign GLOBAL (nhiều thị trường quan
trọng — mặc định xem top 3) LẪN campaign chạy lẻ 1 thị trường (top N tự nhiên
co về đúng 1 dòng, các quốc gia khác quá ít install bị lọc) — không cần đoán
GLOBAL hay không qua tên campaign.

Cũng thêm `detect_phantom_revenue()` — phát hiện quốc gia có doanh thu
(`ad_revenue`) dù KHÔNG có install nào trong campaign, giải thích 1 hiện
tượng user gặp: campaign lẻ 1 thị trường (VD Mexico) có CPI/LTV của ĐÚNG thị
trường đó không tốt, nhưng ROAS D0 GỘP CẢ CAMPAIGN vẫn ổn — vì có thêm doanh
thu "lạ" từ 1 nước khác (VD US, dù US không hề có install nào trong campaign
này) đang bù vào, KHÔNG PHẢI vì thị trường chính đang tốt thật.

CẮT LÁT: theo quốc gia (dùng lại dữ liệu Adjust đã kéo, group theo country)
và theo creative (cần gọi thêm 1 lần Adjust API riêng — xem
adjust_client.fetch_creative_summary(), dimension "creative_network" đã
kiểm chứng là dữ liệu thật, không phải suy đoán).
"""

import pandas as pd

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
        "arpu_d0": (revenue_d0 / installs) if installs else None,
        "roas_d0": (revenue_d0 / cost) if cost else None,
        "retention_d1": (retained_d1 / installs) if installs else None,
    }


def diagnose_tier1(stats: dict, benchmark: dict, threshold_pct: float = DEFAULT_THRESHOLD_PCT) -> dict:
    """benchmark: {"cpi":.., "arpu_d0":.., "roas_d0":.., "retention_d1":..} —
    key nào None (chưa nhập) thì BỎ QUA điều kiện đó (không tự đoán benchmark)."""
    cpi_dat = False
    cpi_pct = None
    if stats.get("cpi") is not None and benchmark.get("cpi"):
        cpi_pct = (stats["cpi"] - benchmark["cpi"]) / benchmark["cpi"] * 100
        cpi_dat = cpi_pct > threshold_pct

    arpu_pct = None
    arpu_kem = False
    if stats.get("arpu_d0") is not None and benchmark.get("arpu_d0"):
        arpu_pct = (stats["arpu_d0"] - benchmark["arpu_d0"]) / benchmark["arpu_d0"] * 100
        arpu_kem = arpu_pct < -threshold_pct

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
        "user_kem": roas_kem or retention_kem or arpu_kem,
        "arpu_kem": arpu_kem,
        "arpu_pct_vs_bench": arpu_pct,
        "roas_kem": roas_kem,
        "roas_pct_vs_bench": roas_pct,
        "retention_kem": retention_kem,
        "retention_pct_vs_bench": retention_pct,
    }


def country_slice(
    campaign_country_df: pd.DataFrame,
    min_installs: int = 5,
    benchmark_by_country: dict | None = None,
) -> pd.DataFrame:
    """Cắt lát theo quốc gia cho ĐÚNG 1 campaign — sắp ROAS D0 thấp nhất lên
    đầu (nghi phạm chính) để dễ soi.

    campaign_country_df: kết quả THÔ từ adjust_client.fetch_campaign_country_summary()
    (đã parse thành DataFrame) — ĐÃ lọc sẵn về đúng 1 campaign + tự tổng hợp
    đúng CPI/ROAS D0/Retention D1 theo quốc gia (Adjust tự tính vì dimension
    KHÔNG có "day" — không cần cộng dồn tay ở đây nữa, xem docstring
    fetch_campaign_country_summary()). ĐỔI 22/09/2026: trước đây hàm này tự
    lọc + cộng dồn từ raw_adjust_df (bảng chi tiết đầy đủ) — đổi sang nhận
    thẳng data đã lọc sẵn server-side, vì trang Cảnh báo đã bỏ cột "country"
    khỏi truy vấn chính (để nhanh hơn), nên không còn raw_adjust_df có country
    để tái sử dụng — phải kéo riêng, nhẹ, chỉ cho đúng 1 campaign.

    min_installs: lọc bớt quốc gia quá ít traffic (mặc định 5) — 1-2 install
    dễ ra ROAS D0 = 0.0 (chưa kịp có revenue D0) trông như "tệ nhất" dù không
    có ý nghĩa thống kê gì, đã gặp thật khi test (145 nước, rất nhiều nước chỉ
    1 install).

    THÊM 23/09/2026 (theo yêu cầu user — campaign GLOBAL không nhìn CPI/LTV cả
    campaign được, phải bóc tách từng nước): thêm cột "LTV (ARPU D0)" (=
    ROAS D0 × CPI — ĐÚNG về đại số vì ROAS_D0 = ARPU_D0 ÷ CPI luôn luôn đúng,
    xem intraday_alerts.py để biết lý do — KHÔNG cần gọi thêm API).

    ĐỔI 23/09/2026 (theo yêu cầu user — benchmark giờ nhập THEO QUỐC GIA, xem
    benchmarks.py): `benchmark_by_country` là dict {country: {"cpi":...,
    "arpu_d0":..., "roas_d0":..., "retention_d1":..., "threshold_pct":...}}
    (từ `benchmarks.get_all_country_benchmarks(product_id)`) — MỖI QUỐC GIA
    so với ĐÚNG benchmark của chính nó (không còn 1 benchmark chung cho cả
    bảng như trước). Quốc gia nào chưa có benchmark thì cột so benchmark/
    Cảnh báo để trống cho quốc gia đó (không suy đoán bằng benchmark nước
    khác)."""
    if campaign_country_df is None or campaign_country_df.empty:
        return pd.DataFrame()

    df = campaign_country_df.copy()
    for col in ("installs", "ecpi_all", "roas_ad_d0", "retention_rate_d1", "ad_revenue"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # LTV (ARPU D0) suy ra từ ROAS D0 × CPI — KHÔNG lấy trung bình cộng qua các
    # dòng (đã là 1 dòng/quốc gia, Adjust tự tổng hợp đúng, chỉ tính lại 1 lần).
    df["arpu_d0"] = df["roas_ad_d0"] * df["ecpi_all"]

    # Bỏ quốc gia quá ít install TRƯỚC khi tính benchmark (xem docstring) —
    # tránh nhiễu chiếm hết đầu bảng.
    df = df[pd.to_numeric(df["installs"], errors="coerce") >= min_installs].copy()

    if benchmark_by_country:
        # Benchmark giờ CHỈ còn cpi/arpu_d0 (đã bỏ ROAS D0/Retention D1/ngưỡng
        # lệch tự nhập — user: "benchmark chỉ cần biết về CPI và LTV thôi").
        # Ngưỡng lệch dùng CỐ ĐỊNH DEFAULT_THRESHOLD_PCT cho mọi quốc gia.
        def _diagnose_row(r):
            country_bench = benchmark_by_country.get(r.get("country")) or {}
            if not any(country_bench.values()):
                return None
            return diagnose_tier1(
                {"cpi": r.get("ecpi_all"), "arpu_d0": r.get("arpu_d0")},
                country_bench,
                threshold_pct=DEFAULT_THRESHOLD_PCT,
            )

        bench_results = df.apply(_diagnose_row, axis=1)
        df["_cpi_pct_vs_bench"] = [b["cpi_pct_vs_bench"] if b else None for b in bench_results]
        df["_arpu_pct_vs_bench"] = [b["arpu_pct_vs_bench"] if b else None for b in bench_results]
        df["_canh_bao"] = [
            " · ".join(
                p for p in (
                    ("🔴 CPI đắt" if b["cpi_dat"] else None),
                    ("🔴 LTV thấp" if b["arpu_kem"] else None),
                ) if p
            ) if b else ""
            for b in bench_results
        ]

    df = df.rename(
        columns={
            "country": "Quốc gia",
            "installs": "Installs",
            "ad_revenue": "Doanh thu",
            "ecpi_all": "CPI",
            "arpu_d0": "LTV (ARPU D0)",
            "roas_ad_d0": "ROAS D0",
            "retention_rate_d1": "Retention D1",
            "_cpi_pct_vs_bench": "CPI so benchmark",
            "_arpu_pct_vs_bench": "LTV so benchmark",
            "_canh_bao": "Cảnh báo",
        }
    )
    # THÊM 24/09/2026 (theo yêu cầu user — "thêm cả rev vào thì mới nhìn
    # được"): "Doanh thu" = tổng ad_revenue THẬT của cả khoảng ngày cho đúng
    # quốc gia đó (KHÔNG suy ra từ ROAS D0 × CPI như "LTV (ARPU D0)" — đây là
    # số THÔ, giúp thấy ngay quốc gia nào đang đóng góp nhiều/ít tiền thật,
    # tách biệt với CPI/LTV vốn là số TRUNG BÌNH trên mỗi install).
    cols = [
        c for c in [
            "Quốc gia", "Installs", "Doanh thu", "CPI", "LTV (ARPU D0)", "ROAS D0", "Retention D1",
            "CPI so benchmark", "LTV so benchmark", "Cảnh báo",
        ] if c in df.columns
    ]
    return df[cols].sort_values("ROAS D0").reset_index(drop=True)


def top_markets_slice(
    campaign_country_df: pd.DataFrame,
    benchmark_by_country: dict | None = None,
    top_n: int = 3,
    min_installs: int = 5,
) -> pd.DataFrame:
    """TẦNG 2 MỚI (24/09/2026, theo yêu cầu user): thay vì đánh giá CPI/LTV gộp
    CẢ campaign (Tầng 1 — bị pha loãng nếu campaign chạy GLOBAL nhiều nước),
    chỉ soi TOP `top_n` thị trường đang TIÊU NHIỀU NHẤT (network_cost) trong
    CHÍNH campaign này, mỗi thị trường so với ĐÚNG benchmark của nó.

    KHÔNG cần biết trước campaign là GLOBAL hay chạy lẻ 1 thị trường — cách
    này tự nhiên co về ĐÚNG 1 dòng cho campaign lẻ (các quốc gia khác quá ít
    install bị `min_installs` lọc bỏ), và ra ĐÚNG top N thị trường quan trọng
    cho campaign GLOBAL — không cần đoán qua tên campaign.

    Tái dùng `country_slice()` để có sẵn CPI/LTV (ARPU D0)/ROAS D0/Retention D1/
    so-benchmark/Cảnh báo cho mỗi quốc gia, chỉ lọc lại còn đúng top N theo chi
    tiêu (network_cost) — thứ tự ROAS D0 thấp nhất lên đầu vẫn giữ nguyên
    (kế thừa từ country_slice(), lọc bằng isin không đổi thứ tự)."""
    full = country_slice(campaign_country_df, min_installs=min_installs, benchmark_by_country=benchmark_by_country)
    if full.empty or campaign_country_df is None or campaign_country_df.empty:
        return full

    df = campaign_country_df.copy()
    df["installs"] = pd.to_numeric(df["installs"], errors="coerce").fillna(0)
    df["network_cost"] = pd.to_numeric(df["network_cost"], errors="coerce").fillna(0)
    df = df[df["installs"] >= min_installs]
    top_countries = (
        df.groupby("country")["network_cost"].sum().sort_values(ascending=False).head(top_n).index.tolist()
    )
    return full[full["Quốc gia"].isin(top_countries)].reset_index(drop=True)


def detect_phantom_revenue(campaign_country_df: pd.DataFrame, min_revenue: float = 0.01) -> pd.DataFrame:
    """THÊM 24/09/2026 (theo yêu cầu user): tìm quốc gia có `ad_revenue` > 0
    nhưng KHÔNG có install nào (installs == 0) trong CHÍNH campaign này —
    dấu hiệu doanh thu "lạ" đến từ NGOÀI thị trường mục tiêu (VD user đổi vị
    trí/di chuyển sau khi cài, hoặc Adjust gán quốc gia theo nơi PHÁT SINH sự
    kiện thay vì nơi cài — không phải bug của tool).

    Hữu ích để giải thích 1 hiện tượng cụ thể user gặp: campaign chạy lẻ 1
    thị trường (VD Mexico) có CPI/LTV CỦA ĐÚNG THỊ TRƯỜNG ĐÓ không tốt, nhưng
    ROAS D0 GỘP CẢ CAMPAIGN vẫn ổn — vì có thêm doanh thu từ 1 nước khác (VD
    US) dù nước đó không hề có install nào trong campaign — số ROAS D0 gộp
    đang được "bù" bởi doanh thu ngoài thị trường chính, không phải vì thị
    trường chính đang tốt.

    Dùng `ad_revenue` (tổng doanh thu THẬT của cả khoảng ngày, metric có sẵn
    trong METRICS của adjust_client.py — không phải suy ra từ roas_ad_d0, vì
    installs=0 sẽ khiến các tỉ lệ suy ra vô nghĩa/NaN)."""
    if campaign_country_df is None or campaign_country_df.empty:
        return pd.DataFrame()
    df = campaign_country_df.copy()
    df["installs"] = pd.to_numeric(df["installs"], errors="coerce").fillna(0)
    df["ad_revenue"] = pd.to_numeric(df["ad_revenue"], errors="coerce").fillna(0)
    phantom = df[(df["installs"] == 0) & (df["ad_revenue"] > min_revenue)]
    if phantom.empty:
        return pd.DataFrame()
    return (
        phantom[["country", "ad_revenue"]]
        .rename(columns={"country": "Quốc gia", "ad_revenue": "Doanh thu (không có install)"})
        .sort_values("Doanh thu (không có install)", ascending=False)
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


def aggregate_adjust_funnel(
    raw_adjust_df: pd.DataFrame,
    product_id: str,
    campaign: str | None = None,
    exclude_campaign: str | None = None,
) -> dict:
    """Gộp ĐÚNG CÁCH network_impressions/network_clicks/network_cost/installs
    (Adjust) thành CPM/CTR/CVR/CPI — THAY THẾ aggregate_bq_rows() cũ (đã bỏ
    BigQuery 22/09/2026 — xem docstring đầu file). Cộng dồn tử/mẫu rồi chia
    lại, không trung bình cộng trực tiếp cột %.

    campaign: lọc về ĐÚNG 1 campaign (số của campaign đang xem).
    exclude_campaign: LOẠI 1 campaign ra (dùng để tính peer average — "trung
    bình các campaign KHÁC cùng app"). Chỉ truyền 1 trong 2 tham số này.
    """
    empty_result = {"cpm": None, "ctr_pct": None, "cvr_pct": None, "cpi": None, "spend": 0, "installs": 0}
    if raw_adjust_df is None or raw_adjust_df.empty:
        return empty_result

    df = raw_adjust_df[raw_adjust_df["app"].astype(str).str.startswith(product_id, na=False)]
    if campaign is not None:
        df = df[df["campaign"] == campaign]
    if exclude_campaign is not None:
        df = df[df["campaign"] != exclude_campaign]
    if df.empty:
        return empty_result

    cost = pd.to_numeric(df["network_cost"], errors="coerce").fillna(0).sum()
    impressions = pd.to_numeric(df.get("network_impressions"), errors="coerce").fillna(0).sum()
    clicks = pd.to_numeric(df.get("network_clicks"), errors="coerce").fillna(0).sum()
    installs = pd.to_numeric(df["installs"], errors="coerce").fillna(0).sum()
    return {
        "spend": cost,
        "installs": installs,
        "cpm": (cost / impressions * 1000) if impressions else None,
        "ctr_pct": (clicks / impressions * 100) if impressions else None,
        "cvr_pct": (installs / clicks * 100) if clicks else None,
        "cpi": (cost / installs) if installs else None,
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
    "arpu_kem": "LTV (ARPU D0) thấp hơn benchmark → user vẫn ở lại nhưng KHÔNG tạo ra "
    "đủ giá trị (ít xem ads, hoặc quốc gia đang chạy có eCPM thấp) — khác với vấn đề "
    "CPI đắt (chi phí), đây là vấn đề GIÁ TRỊ NGƯỜI DÙNG — xem cắt lát theo quốc gia "
    "bên dưới để biết quốc gia nào đang kéo LTV xuống nhiều nhất.",
    "roas_kem": "ROAS D0 thấp hơn benchmark nhưng CPI và LTV riêng lẻ đều chưa rõ nguyên "
    "nhân — có thể do kết hợp cả 2 lệch nhẹ cùng lúc, xem thêm chi tiết CPI/LTV ở trên.",
}
