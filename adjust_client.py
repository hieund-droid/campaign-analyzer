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

# Xem GHI_CHU_TIEN_DO.md mục "Các quyết định quan trọng" để biết vì sao chọn
# từng metric (vd: ad_revenue thay vì revenue, network_ecpi có mẫu số khác installs...).
METRICS = (
    "installs,network_cost,network_ecpi,ad_revenue,"
    "roas_ad_d0,roas_ad_d7,roas_ad_d30,"
    "retention_rate_d1,retention_rate_d7"
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
    "network_ecpi",
    "roas_ad_d0",
    "roas_ad_d7",
    "roas_ad_d30",
    "retention_rate_d1",
    "retention_rate_d7",
]
SUMMABLE_COLS = ["installs", "network_cost", "ad_revenue"]


def get_date_range(days_back: int = DAYS_BACK_DEFAULT) -> str:
    """Trả về chuỗi 'YYYY-MM-DD:YYYY-MM-DD' cho N ngày gần nhất, kết thúc là hôm qua.

    Dùng "hôm qua" làm mốc cuối vì số liệu Adjust của ngày hôm nay thường
    chưa chốt xong (installs/revenue vẫn đang đổ về).
    """
    end = date.today() - timedelta(days=1)
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
) -> dict:
    """Gọi Adjust Report Service API. Trả về dict JSON đã parse.

    exit_on_error=True: in lỗi rồi thoát chương trình (dùng cho script chạy tay,
    muốn thấy lỗi ngay). exit_on_error=False: raise exception thay vì thoát (dùng
    cho script chạy nền/lịch tự động, để phần gọi có thể tự xử lý/log lỗi).
    """
    headers = {"Authorization": f"Bearer {api_token}"}
    params = {
        "app_token__in": ",".join(app_tokens),
        "date_period": get_date_range(days_back),
        "dimensions": dimensions,
        "metrics": METRICS,
        "ad_spend_mode": AD_SPEND_MODE,
        "utc_offset": UTC_OFFSET,
    }

    response = requests.get(ENDPOINT, headers=headers, params=params, timeout=30)

    if not response.ok:
        msg = f"HTTP {response.status_code} (dimensions={dimensions}): {response.text}"
        if exit_on_error:
            print(f"\n❌ LỖI — {msg}")
            sys.exit(1)
        raise RuntimeError(msg)

    return response.json()


def fetch_detail(api_token: str, app_tokens: list, days_back: int = DAYS_BACK_DEFAULT, **kw) -> dict:
    """Bảng chi tiết: theo app + day + campaign + country."""
    return call_adjust(api_token, app_tokens, DETAIL_DIMENSIONS, days_back, **kw)


def fetch_app_totals(api_token: str, app_tokens: list, days_back: int = DAYS_BACK_DEFAULT, **kw) -> dict:
    """Gọi riêng, chỉ dimension='app' — để lấy đúng số TỔNG HỢP Adjust tự tính cho
    từng app (không tự cộng dồn từ bảng chi tiết, tránh sai số làm tròn tích lũy
    qua hàng nghìn dòng nhỏ lẻ — đã kiểm chứng bằng số thật, sai lệch ~3-4% nếu tự
    cộng dồn cột roas_ad_dN từ bảng chi tiết).
    """
    return call_adjust(api_token, app_tokens, "app", days_back, **kw)
