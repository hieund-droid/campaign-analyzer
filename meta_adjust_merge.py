"""
Ghép dữ liệu Meta (BigQuery, view `v_campaign_4c_daily`, channel="Facebook")
với Adjust (Report Service API) theo campaign + day + country.

QUAN TRỌNG — đã kiểm chứng bằng số thật (15/09/2026), KHÔNG phải suy đoán:
1. Khóa ghép campaign: Adjust không có cột campaign_id riêng, nhưng TÊN
   campaign bên Adjust luôn có 1 dãy số ở trong ngoặc đơn tại CUỐI chuỗi, và
   dãy số đó CHÍNH LÀ `campaign_id` bên BigQuery. Đã test: 278/278 campaign_id
   Facebook trong BigQuery (30 ngày, app AAP874) đều tìm thấy trong Adjust —
   khớp 100%. Adjust có dư ra một số campaign KHÔNG trích được số (khoảng 15
   trong 312 dòng) — đó là các campaign không thuộc Meta (search keyword, tên
   app, "unknown"...), không phải lỗi ghép.
2. Khóa ghép country: cả 2 bên đều dùng TÊN nước tiếng Anh đầy đủ (VD
   "Vietnam", "United States") — GHÉP TRỰC TIẾP bằng chuỗi, không cần bảng
   quy đổi mã nước.
3. Khóa ghép app/product: Adjust không có cột product_id, nhưng field "app"
   luôn bắt đầu bằng đúng product_id (VD "AAP874-Face Warp Prank") — lọc
   bằng app.str.startswith(product_id).
4. Khóa ghép ngày: cả 2 bên đều có cột ngày dạng "YYYY-MM-DD" — ghép trực
   tiếp (ép cùng kiểu string trước khi merge để tránh lệch kiểu dữ liệu).

Các cột TỈ LỆ của Adjust (ecpi_all, roas_ad_dN, retention_rate_dN) áp dụng
đúng quy tắc đã chốt trong `adjust_client.py`: KHÔNG cộng dồn trực tiếp qua
nhiều dòng — phải nhân ra số tuyệt đối, cộng dồn, rồi chia lại.
"""

import re

import pandas as pd

CAMPAIGN_ID_RE = re.compile(r"\((\d{6,25})\)\s*$")


def extract_campaign_id(campaign_name: str) -> str | None:
    """Trích số campaign_id từ tên campaign Adjust (số trong ngoặc, cuối chuỗi).
    Trả về None nếu không trích được (campaign không thuộc Meta/Facebook)."""
    if not isinstance(campaign_name, str):
        return None
    m = CAMPAIGN_ID_RE.search(campaign_name.strip())
    return m.group(1) if m else None


def prepare_adjust_for_merge(adjust_df: pd.DataFrame, product_id: str) -> pd.DataFrame:
    """Lọc Adjust về đúng app/product đang xem, trích campaign_id, rồi gộp về
    đúng grain day+country+campaign_id (đề phòng nhiều dòng campaign khác
    tên nhưng cùng campaign_id — VD bản "Dup1" của cùng 1 campaign)."""
    df = adjust_df[adjust_df["app"].astype(str).str.startswith(product_id, na=False)].copy()
    df["campaign_id"] = df["campaign"].apply(extract_campaign_id)
    df = df[df["campaign_id"].notna()].copy()
    if df.empty:
        return df

    for col in ("installs", "network_cost", "ad_revenue"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Số tuyệt đối trước, cộng dồn theo grain mới, rồi chia lại ở dưới —
    # không cộng dồn cột tỉ lệ trực tiếp (xem docstring module).
    for label in ("d0", "d7", "d30"):
        col = f"roas_ad_{label}"
        if col in df.columns:
            df[f"_revenue_{label}"] = pd.to_numeric(df[col], errors="coerce").fillna(0) * df["network_cost"]
    for label in ("d1", "d7"):
        col = f"retention_rate_{label}"
        if col in df.columns:
            df[f"_retained_{label}"] = pd.to_numeric(df[col], errors="coerce").fillna(0) * df["installs"]

    agg_cols = {"installs": "sum", "network_cost": "sum", "ad_revenue": "sum"}
    for c in df.columns:
        if c.startswith("_revenue_") or c.startswith("_retained_"):
            agg_cols[c] = "sum"

    grouped = df.groupby(["day", "country", "campaign_id"], as_index=False).agg(agg_cols)

    grouped["cpi_adjust"] = grouped["network_cost"] / grouped["installs"].replace(0, pd.NA)
    grouped["arpu_d0"] = grouped.get("_revenue_d0", 0) / grouped["installs"].replace(0, pd.NA)
    for label in ("d0", "d7", "d30"):
        rev_col = f"_revenue_{label}"
        if rev_col in grouped.columns:
            grouped[f"roas_ad_{label}"] = grouped[rev_col] / grouped["network_cost"].replace(0, pd.NA)
    for label in ("d1", "d7"):
        ret_col = f"_retained_{label}"
        if ret_col in grouped.columns:
            grouped[f"retention_rate_{label}"] = grouped[ret_col] / grouped["installs"].replace(0, pd.NA)

    grouped = grouped.rename(columns={"installs": "installs_adjust", "network_cost": "spend_adjust"})
    return grouped.drop(columns=[c for c in grouped.columns if c.startswith("_revenue_") or c.startswith("_retained_")])


def merge_meta_adjust(bq_df: pd.DataFrame, adjust_prepared: pd.DataFrame) -> pd.DataFrame:
    """Ghép BigQuery (Facebook, đã lọc product_id+channel) với Adjust (đã
    chuẩn hoá bằng prepare_adjust_for_merge). OUTER JOIN để thấy rõ cả phần
    KHÔNG khớp (VD campaign mới chưa kịp lên BigQuery, hoặc ngược lại)."""
    left = bq_df.copy()
    left["day"] = left["day"].astype(str)
    left["campaign_id"] = left["campaign_id"].astype(str)

    right = adjust_prepared.copy()
    if right.empty:
        merged = left.copy()
        merged["_merge"] = "left_only"
    else:
        right["day"] = right["day"].astype(str)
        right["campaign_id"] = right["campaign_id"].astype(str)
        merged = left.merge(
            right, on=["day", "country", "campaign_id"], how="outer", indicator=True, suffixes=("", "_adj")
        )

    status_map = {"left_only": "Chỉ có ở BigQuery (Meta)", "right_only": "Chỉ có ở Adjust", "both": "Khớp cả 2 nguồn"}
    merged["Trạng thái ghép"] = merged["_merge"].map(status_map).fillna(status_map["left_only"])
    return merged.drop(columns=["_merge"])
