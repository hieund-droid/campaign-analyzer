"""
Phần dùng CHUNG để gọi 2 view BigQuery mô tả trong `AGENT-BRIEF.md` (không commit
lên git — xem .gitignore): dữ liệu Meta/TikTok/Google Ads (View A) và AdMob eCPM
(View B). Dùng 1 service account key CHUNG cho cả team (không phải cá nhân như
Adjust) — xem GHI_CHU_TIEN_DO.md mục "Google Cloud service account key".

QUAN TRỌNG — đã kiểm chứng bằng số thật, KHÁC với AGENT-BRIEF.md ở 2 chỗ:
1. Brief nói "chỉ 1 product". Thực tế key này thấy được 3 product_id: AAP874,
   APL389, AIP568 (3 app khác nhau của Apero) — PHẢI lọc theo product_id.
2. Brief kỳ vọng Google Ads có impressions=NULL, TikTok impressions luôn có giá
   trị. Thực tế: Google Ads impressions=0 (NULL bị ép về 0 ở pipeline, đúng như
   brief đã lường trước) — LOẠI Google Ads khỏi mọi tính CPM/CTR/CVR, chỉ dùng
   cho spend/installs/CPI. TikTok có ~37% dòng NULL impressions (brief KHÔNG hề
   lường trước điều này) — đang tạm loại các dòng NULL đó ra khỏi tính CPM/CTR
   (SUM() tự bỏ qua NULL), CHƯA có xác nhận cuối cùng từ user/team Data.
"""

from datetime import date, timedelta

from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT_ID = "apero-terasofts-dwh"
DATASET = "data_trs_pipeline"
VIEW_CAMPAIGN = f"`{PROJECT_ID}.{DATASET}.v_campaign_4c_daily`"
VIEW_ADMOB = f"`{PROJECT_ID}.{DATASET}.v_admob_ecpm_adunit_daily`"

# Đã query trực tiếp để xác nhận (không đoán) — xem ghi chú trên. Danh sách này
# có thể đổi nếu team Data thêm/bớt app; refresh_product_ids() dưới đây tự query
# lại nếu cần.
KNOWN_PRODUCT_IDS = ["AAP874", "APL389", "AIP568"]

DAYS_BACK_DEFAULT = 7


def get_client_from_info(sa_info: dict) -> bigquery.Client:
    """sa_info: dict nội dung file service account JSON (đọc từ Secrets hoặc file)."""
    creds = service_account.Credentials.from_service_account_info(sa_info)
    return bigquery.Client(credentials=creds, project=creds.project_id)


def get_client_from_file(path: str) -> bigquery.Client:
    creds = service_account.Credentials.from_service_account_file(path)
    return bigquery.Client(credentials=creds, project=creds.project_id)


def get_date_range(days_back: int = DAYS_BACK_DEFAULT):
    """Trả về (start_date, end_date) kiểu date — kết thúc HÔM QUA (brief nói rõ:
    'hôm nay' không bao giờ có trong 2 view này, ngày mới nhất luôn là hôm qua).
    """
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back - 1)
    return start, end


def refresh_product_ids(client: bigquery.Client) -> list:
    """Query lại danh sách product_id thật từ BigQuery (phòng khi team Data đổi).
    Chỉ nên gọi khi cần, không gọi mỗi lần tải trang (tốn quota/tiền dù rất nhỏ).
    """
    sql = f"""
        SELECT DISTINCT product_id FROM {VIEW_CAMPAIGN}
        UNION DISTINCT
        SELECT DISTINCT product_id FROM {VIEW_ADMOB}
        ORDER BY product_id
    """
    return client.query(sql).to_dataframe()["product_id"].tolist()


def fetch_campaign_by_channel(client: bigquery.Client, product_id: str, start: date, end: date):
    """Tổng hợp theo channel — ĐÃ tính đúng cách (cộng dồn tử/mẫu số rồi chia lại,
    không AVG() cột tỉ lệ — xem AGENT-BRIEF.md Rule 1). CPM/CTR/CVR loại trừ các
    dòng impressions/clicks NULL một cách tự nhiên (SUM() bỏ qua NULL) — với
    Google Ads, kết quả sẽ ra NULL cho cpm/ctr_pct vì impressions=0 toàn bộ.
    """
    sql = f"""
        SELECT
            channel,
            COUNT(*) AS n_rows,
            SUM(spend) AS spend,
            SUM(impressions) AS impressions,
            SUM(clicks) AS clicks,
            SUM(installs) AS installs,
            SAFE_DIVIDE(SUM(spend), NULLIF(SUM(impressions), 0)) * 1000 AS cpm,
            SAFE_DIVIDE(SUM(clicks), NULLIF(SUM(impressions), 0)) * 100 AS ctr_pct,
            SAFE_DIVIDE(SUM(installs), NULLIF(SUM(clicks), 0)) * 100 AS cvr_pct,
            SAFE_DIVIDE(SUM(spend), NULLIF(SUM(installs), 0)) AS cpi
        FROM {VIEW_CAMPAIGN}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        GROUP BY channel
        ORDER BY spend DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


def fetch_campaign_trend(client: bigquery.Client, product_id: str, start: date, end: date):
    """Xu hướng theo ngày — gộp mọi channel (chỉ spend/installs, KHÔNG tính CPM/CTR
    gộp kênh vì Google Ads sẽ làm sai số — xem AGENT-BRIEF.md Rule 2)."""
    sql = f"""
        SELECT day, SUM(spend) AS spend, SUM(installs) AS installs
        FROM {VIEW_CAMPAIGN}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        GROUP BY day
        ORDER BY day
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


def fetch_admob_by_adunit(client: bigquery.Client, product_id: str, start: date, end: date):
    """eCPM blended theo ad unit — weighted theo impressions (AGENT-BRIEF.md Rule 1,
    phần eCPM — earnings không lộ ra, phải suy ngược qua impressions)."""
    sql = f"""
        SELECT
            ad_unit,
            ad_format,
            SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(ecpm * impressions), NULLIF(SUM(impressions), 0)) AS ecpm_blended
        FROM {VIEW_ADMOB}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        GROUP BY ad_unit, ad_format
        ORDER BY impressions DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


def fetch_admob_by_country(client: bigquery.Client, product_id: str, start: date, end: date):
    """eCPM blended theo QUỐC GIA (thị trường) — weighted theo impressions, cùng
    công thức với fetch_admob_by_adunit. Cột country có sẵn trong view (brief §1.B)."""
    sql = f"""
        SELECT
            country,
            SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(ecpm * impressions), NULLIF(SUM(impressions), 0)) AS ecpm_blended
        FROM {VIEW_ADMOB}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        GROUP BY country
        ORDER BY impressions DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


# Dimension AdMob cho phép người dùng TỰ CHỌN để pivot (giống kiểu AdMob console,
# nhưng CHỈ trong phạm vi cột view này có — KHÔNG có ad_source/app_version/platform/
# earnings/match_rate/clicks/show_rate như console thật, vì view chỉ có 2 metric
# impressions+ecpm và 4 dimension country/ad_unit/ad_format/day).
ADMOB_DIMENSIONS = ["country", "ad_unit", "ad_format"]


def fetch_admob_flexible(
    client: bigquery.Client,
    product_id: str,
    start: date,
    end: date,
    dimensions: list,
    time_granularity: str | None = "day",
):
    """Query linh hoạt AdMob — tự chọn tổ hợp dimension + mốc thời gian.

    dimensions: tập con của ADMOB_DIMENSIONS (country/ad_unit/ad_format).
    time_granularity: "day" | "week" | "month" | None (None = gộp cả khoảng
    ngày thành 1 dòng, không chia theo thời gian).
    """
    for d in dimensions:
        if d not in ADMOB_DIMENSIONS:
            raise ValueError(f"Dimension không hợp lệ: {d}")

    select_cols = []
    group_cols = []
    if time_granularity == "day":
        select_cols.append("day")
        group_cols.append("day")
    elif time_granularity == "week":
        select_cols.append("DATE_TRUNC(day, WEEK(MONDAY)) AS week")
        group_cols.append("week")
    elif time_granularity == "month":
        select_cols.append("FORMAT_DATE('%Y-%m', day) AS month")
        group_cols.append("month")

    for d in dimensions:
        select_cols.append(d)
        group_cols.append(d)

    select_prefix = (",\n            ".join(select_cols) + ",\n            ") if select_cols else ""
    group_clause = f"GROUP BY {', '.join(group_cols)}" if group_cols else ""

    sql = f"""
        SELECT
            {select_prefix}SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(ecpm * impressions), NULLIF(SUM(impressions), 0)) AS ecpm_blended
        FROM {VIEW_ADMOB}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        {group_clause}
        ORDER BY impressions DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


def fetch_admob_trend(client: bigquery.Client, product_id: str, start: date, end: date):
    sql = f"""
        SELECT
            day,
            SUM(impressions) AS impressions,
            SAFE_DIVIDE(SUM(ecpm * impressions), NULLIF(SUM(impressions), 0)) AS ecpm_blended
        FROM {VIEW_ADMOB}
        WHERE product_id = @product_id AND day BETWEEN @start AND @end
        GROUP BY day
        ORDER BY day
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("product_id", "STRING", product_id),
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
        ]
    )
    return client.query(sql, job_config=job_config).to_dataframe()
