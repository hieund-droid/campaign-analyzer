"""
Phần dùng CHUNG để gọi Adjust Report Service API — dùng bởi cả `adjust_test.py`
(xem nhanh, in ra màn hình) và `adjust_pull_and_cache.py` (chạy nền, lưu SQLite).

QUAN TRỌNG: đổi dimensions/metrics thì sửa Ở ĐÂY, không sửa riêng từng script,
để 2 script luôn đồng bộ. Xem GHI_CHU_TIEN_DO.md để biết lý do chọn từng metric.
"""

import sys
from datetime import date, timedelta

import requests

ENDPOINT = "https://automate.adjust.com/reports-service/report"

# "app" để phân biệt số liệu từng app khi kéo nhiều app; "country" để sau này
# dựng Bảng điểm thị trường (thị trường nào tốt/xấu).
DETAIL_DIMENSIONS = "app,day,campaign,country"
# KHÔNG có "country" — dùng cho trang Cảnh báo (22/09/2026, sửa timeout): trang
# đó KHÔNG cần grain quốc gia (build_campaign_daily gộp theo campaign+day, bỏ
# country ngay từ đầu) — bỏ country khỏi truy vấn giảm 93% số dòng, 65% thời
# gian (đã đo thật: 14 ngày app AAP874 từ 21.7s/39,856 dòng → 7.5s/2,638 dòng).
DETAIL_DIMENSIONS_NO_COUNTRY = "app,day,campaign"

# Xem GHI_CHU_TIEN_DO.md mục "Các quyết định quan trọng" để biết vì sao chọn
# từng metric (vd: ad_revenue thay vì revenue). CPI dùng ecpi_all (= network_cost
# ÷ installs, CÙNG cơ sở installs với mọi metric khác) — KHÔNG dùng network_ecpi
# (mẫu số là installs do network đếm, khác cơ sở, đã gây lệch ARPU trước đây).
# network_impressions/network_clicks: THÊM 22/09/2026 — đã kiểm chứng bằng số
# thật, Adjust CÓ SẴN 2 metric này (dữ liệu network tự báo cáo, cùng nguồn với
# network_cost) — đủ để tự tính CPM/CTR/CVR mà KHÔNG cần BigQuery/Meta merge
# nữa (trước đó dự án phải ghép riêng BigQuery vì tưởng Adjust không có).
METRICS = (
    "installs,network_cost,ecpi_all,ad_revenue,"
    "roas_ad_d0,roas_ad_d7,roas_ad_d30,"
    "retention_rate_d1,retention_rate_d7,"
    "network_impressions,network_clicks"
)
AD_SPEND_MODE = "network"
DAYS_BACK_DEFAULT = 7  # 7 ngày gần nhất

# QUAN TRỌNG: tài khoản Adjust của công ty set theo giờ Việt Nam (UTC+7) — đã xác
# nhận với user. Nếu KHÔNG truyền utc_offset, Adjust mặc định tính "ngày" theo giờ
# UTC, lệch 7 tiếng so với Datascape (đã kiểm chứng bằng số thật: lệch tới 70% cho
# dữ liệu "hôm nay" lúc chưa hết ngày). Mọi lệnh gọi PHẢI có tham số này.
UTC_OFFSET = "+07:00"

# Các cột là TỈ LỆ (không được cộng dồn/sum trực tiếp qua nhiều dòng — Adjust làm
# tròn 4 chữ số thập phân mỗi dòng, cộng dồn hàng nghìn dòng nhỏ lẻ sẽ tích lũy sai
# số vài %, đã kiểm chứng bằng số thật).
RATIO_COLS = [
    "ecpi_all",
    "roas_ad_d0",
    "roas_ad_d7",
    "roas_ad_d30",
    "retention_rate_d1",
    "retention_rate_d7",
]
SUMMABLE_COLS = ["installs", "network_cost", "ad_revenue", "network_impressions", "network_clicks"]


def get_date_range(days_back: int = DAYS_BACK_DEFAULT, include_today: bool = False) -> str:
    """Trả về chuỗi 'YYYY-MM-DD:YYYY-MM-DD' cho N ngày gần nhất.

    Mặc định kết thúc ở "hôm qua" — dùng làm mốc cuối vì số liệu Adjust của ngày
    hôm nay thường CHƯA CHỐT XONG (installs/revenue vẫn đang đổ về, tăng dần đến
    hết ngày). include_today=True để lấy cả hôm nay (số "đang chạy", không phải
    số cuối cùng — chỉ dùng khi cần xem tiến độ trong ngày, không dùng để báo cáo
    chính thức).
    """
    end = date.today() if include_today else date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back - 1)
    return f"{start.isoformat()}:{end.isoformat()}"


def parse_app_tokens(raw: str) -> list:
    """ADJUST_APP_TOKENS trong .env là danh sách token cách nhau bởi dấu phẩy.
    Ví dụ: ADJUST_APP_TOKENS=abc123def456,xyz789uvw012
    """
    return [t.strip() for t in raw.split(",") if t.strip()]


def call_adjust(
    api_token: str,
    app_tokens: list,
    dimensions: str,
    days_back: int = DAYS_BACK_DEFAULT,
    exit_on_error: bool = True,
    include_today: bool = False,
    extra_params: dict | None = None,
) -> dict:
    """Gọi Adjust Report Service API. Trả về dict JSON đã parse.

    exit_on_error=True: in lỗi rồi thoát chương trình (dùng cho script chạy tay,
    muốn thấy lỗi ngay). exit_on_error=False: raise exception thay vì thoát (dùng
    cho script chạy nền/lịch tự động, để phần gọi có thể tự xử lý/log lỗi).
    include_today: xem docstring get_date_range().
    extra_params: filter thêm ngoài app_token__in — VD {"campaign__in": "..."}
    để lọc SERVER-SIDE về đúng 1 campaign (đã kiểm chứng bằng số thật 22/09/2026:
    lọc đúng, không lẫn campaign khác — dùng để kéo dữ liệu quốc gia CHỈ của 1
    campaign đang xét ở "Xét nghiệm", nhẹ hơn nhiều so với kéo hết rồi tự lọc).
    """
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {
        "app_token__in": ",".join(app_tokens),
        "date_period": get_date_range(days_back, include_today),
        "dimensions": dimensions,
        "metrics": METRICS,
        "ad_spend_mode": AD_SPEND_MODE,
        "utc_offset": UTC_OFFSET,
    }
    if extra_params:
        params.update(extra_params)

    # timeout 60s TỪNG GÂY LỖI THẬT (22/09/2026): app nhiều dữ liệu (VD APL567)
    # kéo detail 30 ngày (app,day,campaign,country) có thể mất >60s — đã đo
    # thử app AAP874 (ít dữ liệu hơn nhiều): 30 ngày mất 35.7s cho 126,851 dòng,
    # sát ngưỡng 60s. Tăng lên 180s cho app nhiều dữ liệu hơn vẫn kịp.
    response = requests.get(ENDPOINT, headers=headers, params=params, timeout=180)

    if not response.ok:
        msg = f"HTTP {response.status_code} (dimensions={dimensions}): {response.text}"
        if exit_on_error:
            print(f"\n❌ LỖI — {msg}")
            sys.exit(1)
        raise RuntimeError(msg)

    return response.json()


def extract_warnings(data: dict) -> str | None:
    """Adjust KHÔNG báo lỗi (vẫn HTTP 200) nếu 1 trong nhiều app_token bị sai/không
    tồn tại — nó âm thầm bỏ qua, chỉ trả về app hợp lệ, và giấu thông tin này
    trong field "data_warnings". Đã gặp thật (07/09/2026): thêm app thứ 2 bị gõ
    sai token, không có lỗi nào, chỉ thấy thiếu app trên dashboard. PHẢI gọi hàm
    này sau mỗi lần call_adjust() và hiện cảnh báo ra, không được im lặng bỏ qua.
    """
    warnings = data.get("data_warnings") or []
    if not warnings:
        return None
    return " | ".join(w.get("body", w.get("title", str(w))) for w in warnings)


def fetch_detail(
    api_token: str, app_tokens: list, days_back: int = DAYS_BACK_DEFAULT, include_country: bool = True, **kw
) -> dict:
    """Bảng chi tiết: theo app + day + campaign (+ country nếu include_country=True).

    include_country=False: dùng cho trang Cảnh báo (không cần grain quốc gia,
    nhẹ hơn nhiều — xem DETAIL_DIMENSIONS_NO_COUNTRY). Trang Adjust vẫn dùng
    include_country=True (mặc định) vì có bộ lọc + drill-down theo quốc gia.
    """
    dims = DETAIL_DIMENSIONS if include_country else DETAIL_DIMENSIONS_NO_COUNTRY
    return call_adjust(api_token, app_tokens, dims, days_back, **kw)


def fetch_app_totals(api_token: str, app_tokens: list, days_back: int = DAYS_BACK_DEFAULT, **kw) -> dict:
    """Gọi riêng, chỉ dimension='app' — để lấy đúng số TỔNG HỢP Adjust tự tính cho
    từng app (không tự cộng dồn từ bảng chi tiết, tránh sai số làm tròn tích lũy
    qua hàng nghìn dòng nhỏ lẻ — đã kiểm chứng bằng số thật, sai lệch ~3-4% nếu tự
    cộng dồn cột roas_ad_dN từ bảng chi tiết).
    """
    return call_adjust(api_token, app_tokens, "app", days_back, **kw)


# Dùng cho "Chẩn đoán" (Campaign Doctor) — cắt lát theo CREATIVE. Đã kiểm chứng
# trực tiếp (15/09/2026): "creative_network" là dimension THẬT, trả về đúng tên
# file creative (VD "remix_19_456s2+458s1+459s1.mp4"), không phải giá trị rỗng/
# "unknown" toàn bộ như lo ngại ban đầu. KHÔNG có "day" trong dimension này —
# CỐ Ý, để Adjust tự tổng hợp đúng cho CẢ khoảng ngày (giống cách fetch_app_totals
# dùng dimension="app" — không tự cộng dồn cột tỉ lệ từ bảng chi tiết).
CREATIVE_DIMENSIONS = "app,campaign,creative_network"


def fetch_creative_summary(api_token: str, app_tokens: list, days_back: int = DAYS_BACK_DEFAULT, **kw) -> dict:
    """Tổng hợp theo creative (cho 1 hoặc nhiều campaign) — dùng để "cắt lát
    khoanh vùng" xem creative nào đang kéo campaign xuống."""
    return call_adjust(api_token, app_tokens, CREATIVE_DIMENSIONS, days_back, **kw)


# THÊM 22/09/2026 — THAY THẾ HẲN cơ chế "chụp snapshot" cũ (campaign_snapshots.py
# + background_capture.py, đã xóa): đã kiểm chứng bằng số thật (app AAP874, hôm
# qua), cộng dồn 24 dòng theo dimension "hour" = 47 installs, KHỚP 100% với tổng
# theo "app,day" cũng ra 47 — nghĩa là Adjust TỰ LƯU SẴN lịch sử theo giờ, hỏi
# lúc nào cũng ra đúng số "tính đến giờ X" (bằng cách tự cộng dồn), KHÔNG cần ai
# mở app đúng lúc để ghi lại số như cơ chế snapshot cũ nữa.
DETAIL_DIMENSIONS_HOURLY = "app,hour,campaign"


def fetch_hourly_today(api_token: str, app_tokens: list, **kw) -> dict:
    """Kéo dữ liệu THEO GIỜ của HÔM NAY. Mỗi dòng trả về là số PHÁT SINH TRONG
    giờ đó (KHÔNG PHẢI cộng dồn) — muốn biết "tính đến giờ X" phải tự cộng dồn
    (xem intraday_alerts.build_cumulative_by_hour()). Luôn ép days_back=1 +
    include_today=True vì mục đích DUY NHẤT là xem trong ngày hôm nay."""
    return call_adjust(
        api_token, app_tokens, DETAIL_DIMENSIONS_HOURLY, days_back=1,
        include_today=True, **kw
    )


def fetch_campaign_country_summary(
    api_token: str, app_tokens: list, campaign: str, days_back: int = DAYS_BACK_DEFAULT, **kw
) -> dict:
    """Tổng hợp theo QUỐC GIA cho ĐÚNG 1 campaign, gộp cả khoảng ngày (KHÔNG có
    "day" trong dimension — để Adjust tự tính đúng CPI/ROAS D0/Retention D1 cho
    từng quốc gia, giống cách fetch_app_totals()/fetch_creative_summary() đã
    làm — không tự cộng dồn tay). Lọc SERVER-SIDE bằng campaign__in (đã kiểm
    chứng đúng, xem docstring call_adjust()) — dùng cho "Xét nghiệm" cắt lát
    theo quốc gia, thay vì phải kéo full app,day,campaign,country rồi tự lọc
    (22/09/2026 — user báo trang Cảnh báo load chậm, đã đo: cách cũ 21.7s cho
    39,856 dòng chỉ để dùng lại đúng 1 campaign; cách này lọc thẳng, nhẹ hơn
    nhiều lần)."""
    return call_adjust(
        api_token, app_tokens, "app,campaign,country", days_back,
        extra_params={"campaign__in": campaign}, **kw
    )


def list_known_app_prefixes(api_token: str, app_tokens: list, days_back: int = 7, **kw) -> list:
    """Lấy danh sách "product_id" (tiền tố trước dấu "-" trong field "app" thật
    của Adjust, VD "AAP874" từ "AAP874-Face Warp Prank") — THAY THẾ hoàn toàn
    bq.refresh_product_ids() (22/09/2026, đã bỏ BigQuery khỏi Cảnh báo/Xét
    nghiệm). Gọi RIÊNG dimension="app" (giống fetch_app_totals) — rẻ, không
    kéo cả bảng chi tiết chỉ để lấy tên app."""
    data = call_adjust(api_token, app_tokens, "app", days_back, **kw)
    rows = data.get("rows") or []
    prefixes = set()
    for row in rows:
        app_name = row.get("app")
        if app_name:
            prefixes.add(app_name.split("-")[0].strip())
    return sorted(prefixes)
