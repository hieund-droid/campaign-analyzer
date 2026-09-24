"""
Dashboard Streamlit — điều hướng bằng `st.navigation()` (API điều hướng GỐC của
Streamlit, không tự chế bằng radio nữa) — cho icon + nhóm danh mục kiểu 1 BI
tool nội bộ khác của Apero. Việc thu/mở cả sidebar là tính năng có sẵn của
Streamlit (không phải do code này), phần code cải thiện là icon + nhóm mục.

⚠️ ĐÃ BỎ HẲN BIGQUERY (22/09/2026) — user chỉ ra: BigQuery 2 view của dự án
chỉ cập nhật 1 lần/ngày, KHÔNG BAO GIỜ có dữ liệu "hôm nay" (đã kiểm chứng
nhiều lần bằng số thật) — vô dụng cho việc theo dõi/cảnh báo/chẩn đoán cần
tính thời gian thực. Đã xóa hẳn 3 trang từng dùng BigQuery: "Report Builder"
(pivot AdMob eCPM), "Market Board" (eCPM benchmark theo quốc gia), "Meta +
Adjust" (ghép BigQuery CPM/CTR/CVR + PL2 với Adjust) — cùng 2 file
`bq_client.py`/`meta_adjust_merge.py` (đã xóa khỏi project). PHÁT HIỆN QUAN
TRỌNG khi bỏ: Adjust Report Service TỰ CÓ `network_impressions`/
`network_clicks` (network tự báo cáo, cùng nguồn với `network_cost` đã dùng
từ đầu) — đủ để tự tính CPM/CTR/CVR, và PL2 vốn đã dùng thuần Adjust
(`ad_revenue − network_cost`) từ trước — nên KHÔNG mất tính năng gì đáng kể,
chỉ mất cách nhìn theo campaign_id/channel của riêng BigQuery. Xem
GHI_CHU_TIEN_DO.md mục "Bỏ BigQuery" để biết chi tiết.

⚠️ ĐÃ BỎ HẲN cơ chế "chụp snapshot" (22/09/2026, thay bằng dimension "hour"
của Adjust) — xem `intraday_alerts.py` để biết chi tiết + lý do đổi. Không còn
`campaign_snapshots.py`/`background_capture.py`, không còn tiến trình chạy
ngầm, không còn token dùng chung — mỗi lần bấm Apply gọi thẳng Adjust là đủ
dữ liệu để so bất kỳ mốc giờ nào trong ngày.

Giờ CHỈ CÒN 3 trang, TẤT CẢ đều 100% dữ liệu Adjust (không phân nhóm/danh mục
nữa vì không còn nguồn nào khác để tách):
- "Adjust": installs, CPI, ad revenue, ROAS D0/D7/D30, retention D1/D7, ARPU.
- "Cảnh báo": CHỈ CÒN phần "Trong ngày (thời gian thực)" (đã bỏ hẳn mục "xu
  hướng nhiều ngày" 22/09/2026 theo yêu cầu user: "tạm thời chỉ muốn build
  theo hướng realtime" — file `campaign_alerts.py` không còn dùng, đã xóa) —
  so với các mốc 1/2/3 tiếng trước, dùng `intraday_alerts.py` (kéo trực tiếp
  dimension "hour" của Adjust, không cần chụp/lưu trữ gì).
- "Xét nghiệm" (đổi tên từ "Chẩn đoán" 22/09/2026, tên cũ "Campaign Doctor"):
  chọn 1 campaign đang bị cảnh báo (đọc từ trang Cảnh báo) → tầng 1 (CPI đắt/
  User kém, so benchmark tự nhập) → tầng 2 (CPM/CTR/CVR so peer NẾU CPI đắt —
  giờ tính từ `network_impressions`/`network_clicks` của Adjust, KHÔNG còn
  BigQuery; Retention/LTV/ROAS nếu User kém) → gợi ý hành động → cắt lát theo
  quốc gia + creative — xem `campaign_doctor.py`.

MỖI NGƯỜI TỰ NHẬP API Token + App Token Adjust của mình (mỗi người dùng
account Adjust riêng, quản lý app riêng) — nhập 1 lần ở sidebar, dùng chung
cho cả 3 trang — không dùng chung Secrets, chỉ lưu tạm trong session (có thể
tick "Ghi nhớ" để lưu vào localStorage trình duyệt, xem sidebar).

Mọi trang đều KHÔNG tự gọi API khi vừa mở — chọn bộ lọc rồi bấm Apply mới gọi.
Theme màu ở `.streamlit/config.toml` (không chứa gì bí mật, được commit git).
"""

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import adjust_client as ac
import benchmarks as bm
import campaign_doctor as cdoc
import hourly_market_patterns as hmp_module
import intraday_alerts as ia
from streamlit_local_storage import LocalStorage

load_dotenv()  # đọc .env khi chạy local — dùng cho GOOGLE_APPLICATION_CREDENTIALS

st.set_page_config(page_title="Campaign Analyzer", page_icon="📊", layout="wide")

# Streamlit KHÔNG có tuỳ chọn chính thức để chỉnh độ rộng/màu từng mục sidebar
# (đã tra set_page_config + toàn bộ config.py, không có) — đây là CSS không
# chính thức. Các data-testid dưới đây ĐÃ XÁC NHẬN THẬT bằng cách đọc trực tiếp
# file JS đã build của Streamlit (không đoán): stSidebarNavLink (mỗi mục),
# aria-current="page" (mục đang chọn — thuộc tính HTML chuẩn, Streamlit tự gắn),
# stNavSectionHeader (tiêu đề danh mục có mũi tên xổ xuống — mũi tên là Streamlit
# TỰ VẼ SẴN, không phải mình thêm). Vẫn có rủi ro: đây là data-testid NỘI BỘ,
# KHÔNG được Streamlit cam kết ổn định giữa các bản — có thể cần dò lại nếu 1
# bản Streamlit sau này đổi tên.
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { min-width: 190px; max-width: 190px; }

    /* Tiêu đề danh mục (mẹ, VD "BigQuery") — TO HƠN mục con, có mũi tên sẵn */
    [data-testid="stNavSectionHeader"] {
        color: #C9D6E3;
        font-size: 1rem;
        font-weight: 700;
    }

    /* Mục sidebar (con) — mặc định (chưa chọn): xanh nhạt, nhỏ hơn tiêu đề mẹ */
    [data-testid="stSidebarNavLink"] {
        color: #7FC4E8;
        font-size: 0.85rem;
        font-weight: 500;
        border-radius: 8px;
    }

    /* Mục đang chọn: nền cam nhạt bo góc + chữ cam, giống ảnh mẫu */
    [data-testid="stSidebarNavLink"][aria-current="page"] {
        background-color: rgba(245, 166, 35, 0.16);
        border-radius: 8px;
    }
    [data-testid="stSidebarNavLink"][aria-current="page"] span {
        color: #F5A623 !important;
        font-weight: 600;
    }

    /* Khi THU GỌN sidebar: Streamlit mặc định co về 0, ẩn hẳn (nhìn như lỗi,
    chỉ còn mũi tên nổi trên nền trắng). Ép giữ lại 1 dải hẹp CHỈ HIỆN ICON —
    aria-expanded="false" là thuộc tính THẬT Streamlit tự gắn khi thu gọn (xác
    nhận qua mã nguồn, không đoán). Cắt phần chữ bằng overflow (an toàn hơn
    nhắm vào class chữ nội bộ, vì class đó không có tên ổn định).
    ⚠️ Nút mở rộng lại (mũi tên) vẫn nằm ở vùng header phía trên, KHÔNG dời vào
    trong dải icon được — 2 vùng này tách biệt trong Streamlit, dời cần chèn
    JavaScript can thiệp DOM (rủi ro cao, không làm). */
    [data-testid="stSidebar"][aria-expanded="false"] {
        width: 60px !important;
        min-width: 60px !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] {
        overflow: hidden;
        white-space: nowrap;
        justify-content: center;
        padding-left: 0;
        padding-right: 0;
    }
    [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stNavSectionHeader"] {
        display: none;
    }
    [data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarHeader"] img {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════════════
# Sidebar CHUNG — token Adjust cá nhân. ĐẶT Ở NGOÀI mọi hàm trang (module-level,
# chạy trước pg.run()) — module-level nghĩa là CHẠY LẠI ở ĐẦU script mỗi lần
# rerun (kể cả khi chuyển trang trong st.navigation), nên hiện XUYÊN SUỐT mọi
# trang, KHÔNG nằm bên trong 1 trang cụ thể. Trước đây mỗi trang có form nhập
# token RIÊNG — tuy cùng chung 1 session_state key nên KHÔNG thật sự mất giá
# trị khi đổi trang, nhưng user vẫn phải thấy/gõ lại nhiều form giống nhau,
# gây cảm giác phải nhập lại (16/09/2026) — gộp về 1 chỗ duy nhất cho rõ ràng.
#
# Thêm streamlit-local-storage (cài theo yêu cầu user, đã xin phép trước khi
# cài — xem GHI_CHU_TIEN_DO.md) để nhớ token qua cả lần ĐÓNG/MỞ LẠI trình
# duyệt — lưu vào localStorage CỦA TRÌNH DUYỆT NGƯỜI DÙNG, không gửi lên
# GitHub/server dùng chung, không ai khác xem được (đúng tinh thần "mỗi người
# tự nhập, không dùng chung Secrets" đã chốt từ đầu dự án).
# ══════════════════════════════════════════════════════════════════════
local_storage = LocalStorage()

if "adjust_api_token" not in st.session_state:
    _saved_api_token = local_storage.getItem("adjust_api_token")
    if _saved_api_token:
        st.session_state["adjust_api_token"] = _saved_api_token
if "adjust_app_tokens" not in st.session_state:
    _saved_app_tokens = local_storage.getItem("adjust_app_tokens")
    if _saved_app_tokens:
        st.session_state["adjust_app_tokens"] = _saved_app_tokens

with st.sidebar:
    st.markdown("**🔑 Token Adjust cá nhân**")
    st.caption("Dùng chung cho mọi trang — không phải nhập lại khi chuyển trang.")
    if st.button("🔄 Tải token đã lưu (nếu tự động chưa điền)", key="reload_saved_token"):
        # Dự phòng: bước "hỏi trình duyệt" (localStorage) chạy ngầm qua 1 component
        # riêng, đôi khi cần thêm 1 nhịp rerun mới có kết quả ngay lần tải trang
        # đầu tiên — CHƯA test được bằng trình duyệt thật (môi trường code không
        # có trình duyệt), nên thêm nút này để người dùng tự bấm lại nếu ô token
        # không tự điền sau khi mở lại app.
        local_storage.refreshItems()
        _saved_api_token = local_storage.getItem("adjust_api_token")
        _saved_app_tokens = local_storage.getItem("adjust_app_tokens")
        if _saved_api_token:
            st.session_state["adjust_api_token"] = _saved_api_token
        if _saved_app_tokens:
            st.session_state["adjust_app_tokens"] = _saved_app_tokens
        if not _saved_api_token and not _saved_app_tokens:
            st.caption("Chưa có token nào được lưu trên trình duyệt này.")
    st.text_input(
        "API Token",
        type="password",
        help='Adjust → Settings góc dưới trái → Account settings → tab "My profile" → API Token',
        key="adjust_api_token",
    )
    st.text_input(
        "App Token (cách nhau bởi dấu phẩy nếu nhiều app)",
        help='Adjust → mở app → Cài đặt app → "App Token" (~12 ký tự)',
        key="adjust_app_tokens",
    )
    _remember = st.checkbox(
        "Ghi nhớ trên trình duyệt này (khỏi nhập lại lần sau)",
        value=bool(local_storage.getItem("adjust_api_token") or local_storage.getItem("adjust_app_tokens")),
        key="adjust_remember_browser",
    )
    if _remember:
        if st.session_state.get("adjust_api_token") and local_storage.getItem("adjust_api_token") != st.session_state["adjust_api_token"]:
            local_storage.setItem("adjust_api_token", st.session_state["adjust_api_token"], key="save_adjust_api_token")
        if st.session_state.get("adjust_app_tokens") and local_storage.getItem("adjust_app_tokens") != st.session_state["adjust_app_tokens"]:
            local_storage.setItem("adjust_app_tokens", st.session_state["adjust_app_tokens"], key="save_adjust_app_tokens")
    else:
        if local_storage.getItem("adjust_api_token"):
            local_storage.deleteItem("adjust_api_token", key="del_adjust_api_token")
        if local_storage.getItem("adjust_app_tokens"):
            local_storage.deleteItem("adjust_app_tokens", key="del_adjust_app_tokens")


# ══════════════════════════════════════════════════════════════════════
# Adjust — hàm dùng chung
# ══════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy dữ liệu từ Adjust...")
def load_adjust_data(
    days_back: int, app_tokens_raw: str, api_token: str, include_today: bool = False, include_country: bool = True
):
    # QUAN TRỌNG: api_token + app_tokens_raw PHẢI là tham số của hàm (không đọc
    # secret/session ngầm bên trong) — Streamlit chỉ cache dựa theo tham số truyền
    # vào. Nếu đọc ngầm bên trong hàm, đổi giá trị sẽ KHÔNG làm cache cũ mất hiệu
    # lực (đã gặp lỗi thật: thêm app thứ 2 vẫn chỉ thấy app cũ).
    # include_country=False (trang Cảnh báo, 22/09/2026 — sửa timeout): bỏ cột
    # "country" khỏi truy vấn giảm ~65% thời gian, ~93% số dòng (đã đo thật) —
    # Cảnh báo không cần grain quốc gia (build_campaign_daily gộp campaign+day).
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token.", None

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_detail(
            api_token, app_tokens, days_back=days_back, exit_on_error=False,
            include_today=include_today, include_country=include_country,
        )
    except Exception as e:  # noqa: BLE001
        return None, f"Lỗi gọi Adjust API: {e}", None

    warning_msg = ac.extract_warnings(data)

    rows = data.get("rows") or []
    if not rows:
        return pd.DataFrame(), None, warning_msg

    df = pd.DataFrame(rows)
    for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df, None, warning_msg


@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy dữ liệu creative từ Adjust...")
def load_creative_data(days_back: int, app_tokens_raw: str, api_token: str):
    """Dùng cho trang Xét nghiệm — cắt lát theo creative. Gọi RIÊNG (không chung
    với load_adjust_data) vì dimension khác (campaign,creative_network, KHÔNG
    có day/country) — xem adjust_client.fetch_creative_summary()."""
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token.", None

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_creative_summary(api_token, app_tokens, days_back=days_back, exit_on_error=False)
    except Exception as e:  # noqa: BLE001
        return None, f"Lỗi gọi Adjust API: {e}", None

    warning_msg = ac.extract_warnings(data)
    rows = data.get("rows") or []
    if not rows:
        return pd.DataFrame(), None, warning_msg

    df = pd.DataFrame(rows)
    for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df, None, warning_msg


@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy dữ liệu theo giờ × quốc gia (nhiều ngày)...")
def load_hourly_market_data(days_back: int, app_tokens_raw: str, api_token: str):
    """Dùng cho tab "Theo khung giờ" ở Xét nghiệm — kéo dimension
    "app,hour,country" cho NHIỀU NGÀY đã chốt (xem
    adjust_client.fetch_hourly_by_country()). KHÔNG lọc theo 1 campaign cụ
    thể — dữ liệu này TỔNG HỢP CẢ APP, vì quy luật "giờ nào tốt cho thị
    trường nào" là đặc điểm HÀNH VI NGƯỜI DÙNG theo múi giờ, áp dụng chung
    cho mọi campaign chạy market đó, không riêng 1 campaign — gộp cả app cho
    nhiều dữ liệu hơn, quy luật đáng tin hơn."""
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token."
    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_hourly_by_country(api_token, app_tokens, days_back=days_back, exit_on_error=False)
    except Exception as e:  # noqa: BLE001
        return None, f"Lỗi gọi Adjust API: {e}"
    warning_msg = ac.extract_warnings(data)
    rows = data.get("rows") or []
    if not rows:
        return pd.DataFrame(), warning_msg
    return pd.DataFrame(rows), warning_msg


@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy dữ liệu theo quốc gia...")
def load_campaign_country_data(campaign: str, days_back: int, app_tokens_raw: str, api_token: str):
    """Dùng cho trang Xét nghiệm — cắt lát theo quốc gia CHỈ cho 1 campaign
    (22/09/2026 — trang Cảnh báo đã bỏ cột "country" khỏi truy vấn chính để
    nhanh hơn, nên không còn raw_df có country để tái dùng; kéo riêng, lọc
    server-side bằng campaign__in, nhẹ hơn nhiều so với kéo hết rồi tự lọc —
    xem adjust_client.fetch_campaign_country_summary())."""
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token.", None

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_campaign_country_summary(
            api_token, app_tokens, campaign, days_back=days_back, exit_on_error=False
        )
    except Exception as e:  # noqa: BLE001
        return None, f"Lỗi gọi Adjust API: {e}", None

    warning_msg = ac.extract_warnings(data)
    rows = data.get("rows") or []
    if not rows:
        return pd.DataFrame(), None, warning_msg

    df = pd.DataFrame(rows)
    for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df, None, warning_msg


@st.cache_data(ttl=5 * 60, show_spinner="Đang lấy dữ liệu theo giờ hôm nay...")
def load_hourly_data(app_tokens_raw: str, api_token: str, date_str: str):
    """Dùng cho "Cảnh báo trong ngày" — kéo dimension "hour" của 1 NGÀY CỤ THỂ
    (date_str "YYYY-MM-DD", có thể là hôm nay HOẶC 1 ngày đã qua — xem
    adjust_client.fetch_hourly_for_date()). TTL ngắn hơn các loader khác (5
    phút thay vì 15). CHỈ dùng để tính LTV + installs theo giờ (23/09/2026 —
    đã bỏ hẳn CPI/ROAS theo giờ vì Adjust dồn TOÀN BỘ chi phí trong ngày vào
    ĐÚNG 1 giờ duy nhất, không có grain thật theo giờ — xem
    intraday_alerts.py). date_str LÀ THAM SỐ HÀM (không đọc ngầm) để cache tự
    làm mới đúng khi user đổi ngày."""
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token."
    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_hourly_for_date(api_token, app_tokens, date_str, exit_on_error=False)
    except Exception as e:  # noqa: BLE001
        return None, f"Lỗi gọi Adjust API: {e}"
    warning_msg = ac.extract_warnings(data)
    rows = data.get("rows") or []
    if not rows:
        return pd.DataFrame(), warning_msg
    return pd.DataFrame(rows), warning_msg


def weighted_kpis(df: pd.DataFrame) -> dict:
    """Tính KPI tổng hợp ĐÚNG CÁCH — không lấy trung bình/tổng trực tiếp các cột
    tỉ lệ (ecpi_all, roas_ad_dN, retention_rate_dN) vì sẽ sai (đã kiểm chứng
    bằng số thật, xem GHI_CHU_TIEN_DO.md). Thay vào đó: nhân ra số tuyệt đối mỗi
    dòng, cộng dồn, rồi chia lại.
    """
    installs = df["installs"].sum()
    cost = df["network_cost"].sum()
    ad_revenue = df["ad_revenue"].sum()

    kpis = {
        "installs": installs,
        "cost": cost,
        "ad_revenue": ad_revenue,
        "cpi": (cost / installs) if installs else None,
        "arpu": (ad_revenue / installs) if installs else None,
    }

    for label in ("d0", "d7", "d30"):
        roas_col = f"roas_ad_{label}"
        if roas_col in df.columns:
            revenue_dN = (df[roas_col] * df["network_cost"]).sum()
            kpis[f"roas_ad_{label}"] = (revenue_dN / cost) if cost else None
            kpis[f"arpu_{label}"] = (revenue_dN / installs) if installs else None

    for label in ("d1", "d7"):
        ret_col = f"retention_rate_{label}"
        if ret_col in df.columns:
            retained = (df[ret_col] * df["installs"]).sum()
            kpis[f"retention_rate_{label}"] = (retained / installs) if installs else None

    return kpis


def fmt_money(v):
    return f"${v:,.4f}" if v is not None else "N/A"


def fmt_percent(v):
    return f"{v * 100:.1f}%" if v is not None else "N/A"


# ══════════════════════════════════════════════════════════════════════
# Danh sách app (product_id) — LẤY TRỰC TIẾP TỪ ADJUST (KHÔNG còn BigQuery,
# đã bỏ hẳn 22/09/2026: user chỉ ra BigQuery không có dữ liệu realtime nên
# vô dụng cho Cảnh báo/Xét nghiệm — 2 trang này giờ CHỈ dùng Adjust. Danh
# sách app phụ thuộc TOKEN của TỪNG NGƯỜI (mỗi người chỉ thấy app mình có
# App Token, không còn danh sách CHUNG toàn team như khi lấy từ BigQuery).
# ══════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=15 * 60, show_spinner=False)
def get_known_product_ids(app_tokens_raw: str, api_token: str):
    """Trả về (list_product_id, error_message). Cần token đã nhập ở sidebar —
    nếu chưa có, trả về rỗng kèm hướng dẫn thay vì gọi API."""
    if not api_token or not app_tokens_raw:
        return [], "Nhập token Adjust ở sidebar bên trái để thấy danh sách app."
    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        ids = ac.list_known_app_prefixes(api_token, app_tokens, days_back=7, exit_on_error=False)
        return ids, None
    except Exception as e:  # noqa: BLE001
        return [], f"Lỗi lấy danh sách app từ Adjust: {e}"


# ══════════════════════════════════════════════════════════════════════
# TRANG — Benchmark (tách thành trang riêng 23/09/2026 — trước đó thử để ở
# sidebar theo yêu cầu "nhập 1 lần dùng cho mọi tính năng", nhưng user phản
# hồi để trong sidebar (thu gọn trong expander, cột hẹp) BẤT TIỆN — chuyển
# hẳn thành 1 trang ngang hàng Adjust/Cảnh báo/Xét nghiệm, nhiều chỗ hơn để
# nhập + đọc số, vẫn LÀ 1 kho benchmark DUY NHẤT dùng chung cho Tầng 1 và tab
# "Theo quốc gia" ở trang Xét nghiệm (không đổi gì ở benchmarks.py).
# ══════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy danh sách quốc gia...")
def load_known_countries(app_tokens_raw: str, api_token: str, product_id: str):
    """Danh sách quốc gia THẬT đã có install cho app này (30 ngày qua) — dùng
    cho trang Benchmark, tránh gõ tay sai chính tả/không khớp dữ liệu thật."""
    if not api_token or not app_tokens_raw:
        return [], "Thiếu API Token / App Token."
    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        countries = ac.list_known_countries(api_token, app_tokens, product_id, days_back=30, exit_on_error=False)
        return countries, None
    except Exception as e:  # noqa: BLE001
        return [], f"Lỗi lấy danh sách quốc gia từ Adjust: {e}"


def page_benchmark():
    st.title("Benchmark")
    st.caption(
        "Benchmark \"bình thường\" CPI + LTV (ARPU D0) cho TỪNG QUỐC GIA của "
        "từng app (campaign chạy GLOBAL thì CPI/LTV \"bình thường\" của mỗi "
        "nước khác nhau rất nhiều, benchmark chung cho cả app không có ý "
        "nghĩa). Dùng cho bảng \"Theo quốc gia\" ở trang Xét nghiệm — sửa "
        "trực tiếp trong bảng bên dưới rồi bấm Lưu."
    )
    api_token = st.session_state.get("adjust_api_token", "")
    app_tokens_raw = st.session_state.get("adjust_app_tokens", "")
    st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")

    product_ids, ids_err = get_known_product_ids(app_tokens_raw, api_token)
    if ids_err:
        st.info(f"👆 {ids_err}")
        return
    if not product_ids:
        st.warning("Không tìm thấy app nào cho token này trong 7 ngày qua — kiểm tra lại App Token ở sidebar.")
        return

    bench_app = st.selectbox("App", product_ids, key="page_bench_app")
    countries, countries_err = load_known_countries(app_tokens_raw, api_token, bench_app)
    if countries_err:
        st.error(f"❌ {countries_err}")
        return
    if not countries:
        st.warning(f"Không tìm thấy quốc gia nào cho app {bench_app} trong 30 ngày qua.")
        return

    saved = bm.get_all_country_benchmarks(bench_app)
    st.caption(f"Đã có benchmark cho {len(saved)}/{len(countries)} quốc gia của app **{bench_app}**.")

    table_rows = [
        {"Quốc gia": country, "CPI": vals.get("cpi"), "LTV (ARPU D0)": vals.get("arpu_d0")}
        for country, vals in sorted(saved.items())
    ]
    df_bench = pd.DataFrame(table_rows, columns=["Quốc gia", "CPI", "LTV (ARPU D0)"])

    st.caption(
        "Sửa trực tiếp trong bảng — bấm dòng trống cuối bảng để THÊM quốc gia "
        "mới (chọn từ danh sách), xoá dòng (chọn dòng → nhấn phím Delete) để "
        "BỎ benchmark của quốc gia đó. Nhớ bấm **💾 Lưu bảng** sau khi sửa."
    )
    edited = st.data_editor(
        df_bench, width="stretch", hide_index=True, num_rows="dynamic",
        key=f"bench_editor_{bench_app}",
        column_config={
            "Quốc gia": st.column_config.SelectboxColumn("Quốc gia", options=countries, required=True),
            "CPI": st.column_config.NumberColumn("CPI ($)", min_value=0.0, step=0.0001, format="%.4f"),
            "LTV (ARPU D0)": st.column_config.NumberColumn("LTV / ARPU D0 ($)", min_value=0.0, step=0.0001, format="%.4f"),
        },
    )

    if st.button("💾 Lưu bảng", type="primary", key=f"bench_save_{bench_app}"):
        entries = [
            {"country": row.get("Quốc gia"), "cpi": row.get("CPI"), "arpu_d0": row.get("LTV (ARPU D0)")}
            for row in edited.to_dict("records")
            if row.get("Quốc gia")
        ]
        bm.save_all_country_benchmarks(bench_app, entries)
        st.success(f"Đã lưu benchmark cho {len(entries)} quốc gia của {bench_app}.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# TRANG — Adjust
# ══════════════════════════════════════════════════════════════════════
def page_adjust():
    st.title("Adjust")
    st.caption("🔒 Nhập token ở sidebar bên trái (dùng chung cho mọi trang).")
    user_api_token = st.session_state.get("adjust_api_token", "")
    user_app_tokens_raw = st.session_state.get("adjust_app_tokens", "")

    col3, col4 = st.columns([3, 1])
    with col3:
        ADJUST_DATE_PRESETS = {
            "Hôm nay (đang chạy, chưa chốt)": (1, True),
            "Hôm qua": (1, False),
            "7 ngày qua": (7, False),
            "14 ngày qua": (14, False),
            "30 ngày qua": (30, False),
        }
        date_choice = st.selectbox("Khoảng ngày", list(ADJUST_DATE_PRESETS.keys()), index=2, key="adjust_date")
        days_back, include_today = ADJUST_DATE_PRESETS[date_choice]
    with col4:
        st.write("")
        st.write("")
        fetch_clicked = st.button("Apply", type="primary", key="adjust_fetch", width="stretch")

    if "adjust_df" not in st.session_state:
        st.session_state.adjust_df = None
        st.session_state.adjust_err = None
        st.session_state.adjust_warning = None
        st.session_state.adjust_date_choice = None
        st.session_state.adjust_include_today = None

    if fetch_clicked:
        (
            st.session_state.adjust_df,
            st.session_state.adjust_err,
            st.session_state.adjust_warning,
        ) = load_adjust_data(days_back, user_app_tokens_raw, user_api_token, include_today)
        st.session_state.adjust_date_choice = date_choice
        st.session_state.adjust_include_today = include_today

    df = st.session_state.adjust_df
    err = st.session_state.adjust_err
    warning_msg = st.session_state.adjust_warning

    if err:
        st.error(f"❌ {err}")
    elif warning_msg:
        st.warning(f"⚠️ Adjust cảnh báo: {warning_msg}")

    if df is None:
        st.info("👆 Nhập token, chọn khoảng ngày rồi bấm **Apply** để bắt đầu.")
    elif df.empty:
        st.warning("⚠️ Không có dữ liệu cho khoảng ngày này.")
    else:
        apps = sorted(df["app"].dropna().unique().tolist())
        countries = sorted(df["country"].dropna().unique().tolist())

        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            selected_apps = st.multiselect("App", apps, default=apps, key="adjust_apps")
        with fcol2:
            selected_countries = st.multiselect(
                "Quốc gia (để trống = tất cả)", countries, default=[], key="adjust_countries"
            )
        with fcol3:
            campaign_search = st.text_input("Tìm campaign (gõ 1 phần tên)", key="adjust_campaign_search")

        filtered = df[df["app"].isin(selected_apps)] if selected_apps else df.iloc[0:0]
        if selected_countries:
            filtered = filtered[filtered["country"].isin(selected_countries)]
        if campaign_search:
            filtered = filtered[filtered["campaign"].str.contains(campaign_search, case=False, na=False)]

        st.caption(f"📅 {st.session_state.adjust_date_choice} · giờ VN. Đổi bộ lọc bên dưới không tốn API.")
        if st.session_state.adjust_include_today:
            st.warning(
                "⏱️ Đang bao gồm HÔM NAY — số liệu ngày hôm nay là số ĐANG CHẠY, chưa "
                "chốt xong, sẽ còn tăng đến hết ngày. Không dùng số hôm nay để báo cáo "
                "chính thức."
            )

        if filtered.empty:
            st.warning("Không có dòng nào khớp bộ lọc hiện tại.")
        else:
            kpis = weighted_kpis(filtered)

            row1 = st.columns(4)
            row1[0].metric("Installs", f"{kpis['installs']:,.0f}")
            row1[1].metric("Chi phí", f"${kpis['cost']:,.2f}")
            row1[2].metric("Ad Revenue", f"${kpis['ad_revenue']:,.2f}")
            row1[3].metric("CPI (= ecpi_all)", fmt_money(kpis["cpi"]))

            row2 = st.columns(4)
            row2[0].metric("ARPU D0", fmt_money(kpis.get("arpu_d0")))
            row2[1].metric("ROAS D0", fmt_percent(kpis.get("roas_ad_d0")))
            row2[2].metric("ROAS D7", fmt_percent(kpis.get("roas_ad_d7")))
            row2[3].metric("ROAS D30", fmt_percent(kpis.get("roas_ad_d30")))

            row3 = st.columns(4)
            row3[0].metric("Retention D1", fmt_percent(kpis.get("retention_rate_d1")))
            row3[1].metric("Retention D7", fmt_percent(kpis.get("retention_rate_d7")))

            if st.session_state.adjust_include_today:
                st.info(
                    "📍 Muốn xem CPI/ROAS/LTV biến động THẾ NÀO trong ngày hôm nay (so "
                    "với 1/2/3 tiếng trước)? Qua trang **Cảnh báo** — đã có sẵn tính năng "
                    "này, dùng chung dữ liệu Adjust, không cần fetch lại ở đây."
                )

            st.subheader("Xu hướng theo ngày")
            trend = (
                filtered.groupby("day")[["installs", "network_cost", "ad_revenue"]]
                .sum()
                .reset_index()
                .sort_values("day")
                .set_index("day")
            )
            if len(trend) < 2:
                # Không vẽ biểu đồ với đúng 1 điểm — cả line_chart lẫn bar_chart
                # (Vega-Lite kéo giãn cột sai hình khi 1 category) đều hiển thị sai.
                st.info("Chỉ có 1 ngày dữ liệu — chọn thêm ngày để xem xu hướng dạng biểu đồ.")
                st.dataframe(trend, width="stretch")
            else:
                # Tách 2 biểu đồ RIÊNG — installs (hàng nghìn) và chi phí/doanh thu
                # (thường vài chục/trăm đô) chênh lệch quá xa về đơn vị/độ lớn, để
                # chung 1 biểu đồ sẽ làm 2 đường chi phí/doanh thu bẹp dí sát 0,
                # không đọc được (user phản ánh thật khi xem trên Cloud).
                tcol1, tcol2 = st.columns(2)
                with tcol1:
                    st.caption("Installs")
                    st.line_chart(trend[["installs"]])
                with tcol2:
                    st.caption("Chi phí vs Ad Revenue ($)")
                    st.line_chart(trend[["network_cost", "ad_revenue"]].rename(
                        columns={"network_cost": "Chi phí", "ad_revenue": "Ad Revenue"}
                    ))

            st.subheader("Dữ liệu chi tiết theo campaign")
            st.caption(
                "Mỗi campaign 1 dòng (đã gộp mọi quốc gia, tính đúng cách — không "
                "trung bình cộng trực tiếp cột %). Muốn xem theo quốc gia, chọn 1 "
                "campaign ở dropdown bên dưới bảng."
            )

            campaign_rows = []
            for campaign_name, g in filtered.groupby("campaign"):
                k = weighted_kpis(g)
                campaign_rows.append({
                    "Campaign": campaign_name,
                    "Installs": k["installs"],
                    "Chi phí": k["cost"],
                    "Ad Revenue": k["ad_revenue"],
                    "CPI": k["cpi"],
                    "ARPU D0": k.get("arpu_d0"),
                    "ROAS D0": k.get("roas_ad_d0"),
                    "ROAS D7": k.get("roas_ad_d7"),
                    "ROAS D30": k.get("roas_ad_d30"),
                    "Retention D1": k.get("retention_rate_d1"),
                    "Retention D7": k.get("retention_rate_d7"),
                })
            campaign_summary = pd.DataFrame(campaign_rows).sort_values("Chi phí", ascending=False).reset_index(drop=True)

            st.dataframe(
                campaign_summary, width="stretch", hide_index=True,
                column_config={
                    "Chi phí": st.column_config.NumberColumn(format="$%.2f"),
                    "Ad Revenue": st.column_config.NumberColumn(format="$%.2f"),
                    "CPI": st.column_config.NumberColumn(format="$%.4f"),
                    "ARPU D0": st.column_config.NumberColumn(format="$%.4f"),
                    "ROAS D0": st.column_config.NumberColumn(format="percent"),
                    "ROAS D7": st.column_config.NumberColumn(format="percent"),
                    "ROAS D30": st.column_config.NumberColumn(format="percent"),
                    "Retention D1": st.column_config.NumberColumn(format="percent"),
                    "Retention D7": st.column_config.NumberColumn(format="percent"),
                },
            )

            drilldown_campaign = st.selectbox(
                "Xem chi tiết theo quốc gia cho campaign nào?",
                ["(không chọn)"] + campaign_summary["Campaign"].tolist(),
                key="adjust_drilldown_campaign",
            )
            if drilldown_campaign != "(không chọn)":
                by_country_rows = []
                campaign_df = filtered[filtered["campaign"] == drilldown_campaign]
                for country_name, g in campaign_df.groupby("country"):
                    k = weighted_kpis(g)
                    by_country_rows.append({
                        "Quốc gia": country_name,
                        "Installs": k["installs"],
                        "Chi phí": k["cost"],
                        "Ad Revenue": k["ad_revenue"],
                        "CPI": k["cpi"],
                        "ARPU D0": k.get("arpu_d0"),
                        "ROAS D0": k.get("roas_ad_d0"),
                        "Retention D1": k.get("retention_rate_d1"),
                    })
                by_country_df = (
                    pd.DataFrame(by_country_rows).sort_values("Chi phí", ascending=False).reset_index(drop=True)
                )
                st.dataframe(
                    by_country_df, width="stretch", hide_index=True,
                    column_config={
                        "Chi phí": st.column_config.NumberColumn(format="$%.2f"),
                        "Ad Revenue": st.column_config.NumberColumn(format="$%.2f"),
                        "CPI": st.column_config.NumberColumn(format="$%.4f"),
                        "ARPU D0": st.column_config.NumberColumn(format="$%.4f"),
                        "ROAS D0": st.column_config.NumberColumn(format="percent"),
                        "Retention D1": st.column_config.NumberColumn(format="percent"),
                    },
                )


# ══════════════════════════════════════════════════════════════════════
# TRANG — Cảnh báo (THỜI GIAN THỰC, trong ngày — CPI/LTV/ROAS D0 theo campaign)
# ══════════════════════════════════════════════════════════════════════
# ĐÃ BỎ HẲN phần "xu hướng nhiều ngày" (so sánh giữa các ngày đã chốt) —
# 22/09/2026, theo yêu cầu user: "tạm thời chỉ muốn build theo hướng realtime,
# trả lời được câu hỏi tại sao ROAS tụt TRONG NGÀY". Module `campaign_alerts.py`
# (spike/decline theo ngày) không còn dùng ở đâu trong app.py nữa — ĐÃ XÓA file.
def page_alerts():
    st.title("Cảnh báo")
    st.caption(
        "Phát hiện CPI tăng / LTV (ARPU D0) giảm / ROAS D0 tụt NGAY TRONG NGÀY "
        "theo TỪNG CAMPAIGN — so với các mốc 1/2/3 tiếng trước, để biết ROAS "
        "biến động là do chi phí đắt lên hay do giá trị user tụt xuống."
    )

    al_api_token = st.session_state.get("adjust_api_token", "")
    al_app_tokens_raw = st.session_state.get("adjust_app_tokens", "")
    st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")

    known_product_ids, product_ids_err = get_known_product_ids(al_app_tokens_raw, al_api_token)
    if product_ids_err:
        st.info(f"👆 {product_ids_err}")
        return
    if not known_product_ids:
        st.warning("Không tìm thấy app nào cho token này trong 7 ngày qua — kiểm tra lại App Token ở sidebar.")
        return

    col1, col2 = st.columns(2)
    with col1:
        al_product_id = st.selectbox("App (product_id)", known_product_ids, key="al_product")
    with col2:
        # Khoảng ngày này KHÔNG dùng để phát hiện xu hướng nữa (đã bỏ) — chỉ
        # còn dùng làm nguồn dữ liệu cho trang "Xét nghiệm" (tầng 1/tầng 2 so
        # benchmark + peer average, tính trên cả khoảng ngày này).
        AL_DATE_PRESETS = {
            "3 ngày qua": 3, "7 ngày qua": 7, "14 ngày qua": 14,
            "21 ngày qua": 21, "28 ngày qua": 28, "30 ngày qua": 30,
        }
        al_date_choice = st.selectbox(
            "Khoảng ngày kéo (dùng cho trang Xét nghiệm)",
            list(AL_DATE_PRESETS.keys()), index=2, key="al_date",
        )
        al_days_back = AL_DATE_PRESETS[al_date_choice]

    # THÊM 23/09/2026 (theo yêu cầu user — tạm dùng số ngày hôm trước trong
    # lúc chờ Meta API): mặc định NGÀY HÔM QUA (đã chốt, chi phí đáng tin hơn
    # "hôm nay" — xem GHI_CHU_TIEN_DO.md), nhưng vẫn cho chọn "Hôm nay" hoặc
    # bất kỳ ngày nào khác trong quá khứ để xem lại diễn biến trong ngày đó.
    al_view_date = st.date_input(
        "Xem diễn biến TRONG NGÀY của ngày nào?",
        value=date.today() - timedelta(days=1),
        max_value=date.today(),
        key="al_view_date",
        help="Mặc định hôm qua — ngày ĐÃ CHỐT thì chi phí đáng tin hơn \"hôm "
        "nay\" (Adjust chỉ pull lại chi phí Facebook 1 lần/ngày, hôm nay có "
        "thể chưa pull kịp). Chọn \"hôm nay\" nếu vẫn muốn xem số đang chạy.",
    )
    al_fetch_clicked = st.button("Apply", type="primary", key="al_fetch")

    al_min_installs = st.number_input(
        "Install tối thiểu để tính vào cảnh báo",
        min_value=0, value=30, step=10, key="al_min_installs",
        help="Campaign có ít install hơn mức này sẽ bị bỏ qua — quá ít dữ liệu "
        "dễ báo động giả (VD 1-2 install cũng đủ làm số nhảy vọt vô nghĩa).",
    )

    if "al_raw_df" not in st.session_state:
        st.session_state.al_raw_df = None
        st.session_state.al_product_used = None
        st.session_state.al_days_back_used = None
        st.session_state.al_err = None
        st.session_state.al_warning = None
        st.session_state.al_hourly_df = None
        st.session_state.al_hourly_err = None
        st.session_state.al_campaign_channel_map = {}
        st.session_state.al_view_date_used = None

    if al_fetch_clicked:
        # Phần ngày ĐÃ CHỐT (không lấy hôm nay) — dùng cho trang "Xét nghiệm"
        # (tầng 1/tầng 2 so benchmark + peer average). Phần "trong ngày" giờ
        # kéo RIÊNG bằng dimension "hour" (xem intraday_alerts.py — thay thế
        # hẳn cơ chế "chụp snapshot" cũ, KHÔNG cần lưu trữ/chạy ngầm gì nữa).
        adjust_df, adjust_err, adjust_warning = load_adjust_data(
            al_days_back, al_app_tokens_raw, al_api_token, include_today=False, include_country=False
        )
        st.session_state.al_warning = adjust_warning
        if adjust_err:
            st.session_state.al_err = adjust_err
            st.session_state.al_raw_df = None
        else:
            st.session_state.al_err = None
            st.session_state.al_raw_df = adjust_df
            st.session_state.al_product_used = al_product_id
            st.session_state.al_days_back_used = al_days_back

        al_view_date_str = al_view_date.isoformat()
        hourly_df, hourly_err = load_hourly_data(al_app_tokens_raw, al_api_token, al_view_date_str)
        st.session_state.al_hourly_df = hourly_df
        st.session_state.al_hourly_err = hourly_err
        st.session_state.al_view_date_used = al_view_date_str

        # Bản đồ campaign → network (channel) — để user tự biết campaign đang
        # bị "đứng chi phí" có phải Meta/Facebook không, TRƯỚC KHI cân nhắc nối
        # thẳng Meta Marketing API (chỉ đáng làm nếu ĐA SỐ campaign là Meta).
        try:
            app_tokens_list = ac.parse_app_tokens(al_app_tokens_raw)
            channel_data = ac.fetch_campaign_channel_map(al_api_token, app_tokens_list, exit_on_error=False)
            channel_rows = channel_data.get("rows") or []
            st.session_state.al_campaign_channel_map = {
                r.get("campaign"): r.get("channel") for r in channel_rows if r.get("campaign")
            }
        except Exception:  # noqa: BLE001 — chỉ là thông tin phụ, không được chặn cả trang
            st.session_state.al_campaign_channel_map = {}

    if st.session_state.al_err:
        st.error(f"❌ {st.session_state.al_err}")
    if st.session_state.al_warning:
        st.warning(f"⚠️ Adjust cảnh báo: {st.session_state.al_warning}")

    if st.session_state.al_raw_df is None:
        st.info("👆 Chọn app + khoảng ngày, nhập token Adjust rồi bấm **Apply** để bắt đầu.")
        return

    if st.session_state.al_hourly_err:
        st.error(f"❌ Không lấy được dữ liệu theo giờ: {st.session_state.al_hourly_err}")

    _view_date_iso = st.session_state.get("al_view_date_used")
    _is_today_view = _view_date_iso == date.today().isoformat()
    _date_label = "hôm nay" if _is_today_view else (
        f"ngày {date.fromisoformat(_view_date_iso).strftime('%d/%m/%Y')}" if _view_date_iso else "ngày đã chọn"
    )
    _now_or_end_label = "Bây giờ" if _is_today_view else "Cuối ngày"

    st.subheader(f"⚡ Cảnh báo trong ngày — {_date_label}")
    st.caption(
        f"So với các mốc ~1/2/3/6 tiếng trước TRONG {_date_label.upper()} — lấy "
        "TRỰC TIẾP lịch sử theo GIỜ từ Adjust. **CHỈ dùng LTV** (doanh thu ads "
        "÷ installs, đổi 23/09/2026) — đã BỎ HẲN CPI/ROAS theo giờ: kiểm chứng "
        "bằng số thật (nhiều ngày) cho thấy Adjust dồn TOÀN BỘ chi phí của CẢ "
        "NGÀY vào ĐÚNG 1 GIỜ DUY NHẤT (thường 00:00), 23 giờ còn lại luôn $0 — "
        "nên CPI/ROAS theo giờ VÔ NGHĨA ở bất kỳ khung nào. `ad_revenue` (dùng "
        "để tính LTV) thì khác — đến từ SDK Adjust trong app, có thật theo "
        "từng giờ (đã kiểm chứng khớp chính xác với tổng theo ngày). Xem "
        "GHI_CHU_TIEN_DO.md để biết chi tiết."
    )
    al_realtime_pct = st.number_input(
        "Mức LTV thay đổi cần báo động (%)",
        min_value=5, value=20, step=5, key="al_realtime_pct",
        help="Mỗi campaign tự so với giờ nào trong ngày cho LTV đổi NHIỀU "
        "NHẤT (không ép chung 1 mốc cho mọi campaign) — bắt CẢ 2 CHIỀU: LTV "
        "tăng HOẶC giảm từ mức này trở lên đều hiện cảnh báo, để vừa phát "
        "hiện vấn đề vừa phát hiện cơ hội tăng ngân sách.",
    )

    hourly_df = st.session_state.al_hourly_df
    if hourly_df is None or hourly_df.empty:
        st.info(f"Chưa có dữ liệu theo giờ cho {_date_label} với token này — bấm Apply để tải.")
        st.session_state.al_realtime_flagged = []
        return

    cum_df = ia.build_cumulative_by_hour(hourly_df)
    # Chỉ xét app đang chọn (product_id) — field "app" thật của Adjust có dạng
    # "AAP874-Face Warp Prank", product_id là phần trước dấu "-".
    cum_df_scope = cum_df[cum_df["app"].str.startswith(al_product_id)]

    # LTV theo giờ dùng số PHÁT SINH TRONG giờ đó (KHÔNG cộng dồn) — khác cách
    # tính LTV dùng để gắn cờ cảnh báo bên dưới (vốn CỘNG DỒN từ đầu ngày).
    # Sum-then-divide đúng cách (cộng installs + ad_revenue riêng theo giờ,
    # rồi mới chia — KHÔNG lấy trung bình cộng qua các campaign). Chỉ đáng
    # tin khi xem NGÀY ĐÃ QUA khá lâu (mọi giờ trong ngày đó đã "chín" gần
    # bằng nhau) — xem "hôm nay" sẽ THẤY GIẢM DẦN GIẢ (giờ càng gần hiện tại,
    # doanh thu càng chưa kịp phát sinh, không phải chất lượng user tệ hơn).
    _hourly_totals = cum_df_scope.groupby("hour")[["installs", "ad_revenue"]].sum().sort_index()
    _hourly_totals["ltv"] = _hourly_totals["ad_revenue"] / _hourly_totals["installs"].replace(0, pd.NA)
    _hourly_totals.index = [h[11:16] for h in _hourly_totals.index]

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.caption("Installs theo giờ (cả app, mọi campaign cộng lại):")
        if not _hourly_totals.empty:
            st.bar_chart(_hourly_totals[["installs"]])
    with chart_col2:
        st.caption("LTV theo giờ (= doanh thu ads ÷ installs phát sinh trong giờ đó):")
        if _is_today_view:
            st.caption(
                "⚠️ Đang xem HÔM NAY — biểu đồ này sẽ tự nhiên giảm dần về cuối "
                "ngày (installs mới chưa kịp sinh doanh thu), KHÔNG phản ánh chất "
                "lượng user tệ đi. Chỉ đáng tin khi xem 1 ngày ĐÃ QUA khá lâu."
            )
        if not _hourly_totals.empty:
            st.line_chart(_hourly_totals[["ltv"]])

    all_flagged_today = ia.list_flagged_best_swing(
        cum_df_scope, threshold_pct=float(al_realtime_pct), min_installs=int(al_min_installs)
    )
    # Lưu lại để trang "Xét nghiệm" đọc danh sách campaign đang bị cảnh báo.
    st.session_state.al_realtime_flagged = all_flagged_today

    # Chẩn đoán khi không campaign nào bị flag — đếm riêng từng nguyên nhân
    # để báo ĐÚNG chỗ tắc: (1) app không có dòng nào, (2) campaign chưa đủ 2
    # giờ khác nhau, (3) đủ giờ nhưng dưới ngưỡng Install tối thiểu, (4) đủ
    # điều kiện nhưng LTV không đổi quá ngưỡng %.
    _diag_total_campaigns = cum_df_scope["campaign"].nunique() if not cum_df_scope.empty else 0
    _diag_too_few_hours = 0
    _diag_below_min_installs = 0
    if not cum_df_scope.empty:
        _hours_per_campaign = cum_df_scope.groupby("campaign")["hour"].nunique()
        _enough_hours_campaigns = _hours_per_campaign[_hours_per_campaign >= 2].index
        _diag_too_few_hours = _diag_total_campaigns - len(_enough_hours_campaigns)
        if len(_enough_hours_campaigns):
            _last_per_campaign = (
                cum_df_scope[cum_df_scope["campaign"].isin(_enough_hours_campaigns)]
                .sort_values("hour").groupby("campaign").tail(1)
            )
            _diag_below_min_installs = int((_last_per_campaign["installs_cum"] < al_min_installs).sum())

    _channel_map = st.session_state.get("al_campaign_channel_map", {})

    # Tô màu chữ cột "LTV % đổi" — xanh nếu tăng, đỏ nếu giảm (dễ nhìn hơn chỉ
    # dấu +/-). Định nghĩa ở NGOÀI cả 2 khối if/else bên dưới (bảng 1/2/3/6
    # tiếng VÀ bảng tự chọn giờ đều dùng) — tránh lỗi "chưa định nghĩa" nếu 1
    # trong 2 bảng không có dòng nào để hiện.
    def _color_pct(val):
        if val is None or pd.isna(val):
            return ""
        return "color: #1a8a3c" if val > 0 else ("color: #d1332e" if val < 0 else "")

    if not all_flagged_today:
        if _diag_total_campaigns == 0:
            st.warning(
                f"App **{al_product_id}** không có dòng dữ liệu campaign nào cho "
                f"{_date_label} — kiểm tra lại App Token/App đang chọn có đúng "
                "không, hoặc app này không chạy campaign nào hôm đó."
            )
        else:
            _diag_parts = [f"Tổng {_diag_total_campaigns} campaign có dữ liệu {_date_label}."]
            if _diag_too_few_hours:
                _diag_parts.append(f"{_diag_too_few_hours} campaign chưa đủ 2 giờ khác nhau (VD chỉ chạy đúng 1 giờ).")
            _diag_enough = _diag_total_campaigns - _diag_too_few_hours
            if _diag_enough:
                if _diag_below_min_installs == _diag_enough:
                    _diag_parts.append(
                        f"CẢ {_diag_enough} campaign đủ giờ đều có installs cuối ngày DƯỚI "
                        f"ngưỡng \"Install tối thiểu\" ({int(al_min_installs)}) nên bị loại hết "
                        "— thử giảm ngưỡng này nếu muốn xem."
                    )
                else:
                    if _diag_below_min_installs:
                        _diag_parts.append(
                            f"{_diag_below_min_installs}/{_diag_enough} campaign đủ giờ bị loại vì "
                            f"installs cuối ngày dưới ngưỡng \"Install tối thiểu\" ({int(al_min_installs)})."
                        )
                    _diag_qualifying_n = _diag_enough - _diag_below_min_installs
                    if _diag_qualifying_n > 0:
                        _diag_parts.append(
                            f"{_diag_qualifying_n} campaign đủ điều kiện — KHÔNG campaign nào trong "
                            f"số này LTV đổi (tăng hoặc giảm) quá {int(al_realtime_pct)}% dù đã tự so "
                            "với mọi giờ khác trong ngày (đã quét toàn bộ, không chỉ vài mốc cố định)."
                        )
            st.info(" ".join(_diag_parts))
    else:
        # ĐỔI 24/09/2026 (user chỉ ra): mọi dữ liệu ở đây đều là LỊCH SỬ (kể cả
        # khi "Bây giờ" = đang xem hôm nay) — cột "Installs bây giờ"/"LTV bây
        # giờ" từng bị HARDCODE cứng chữ "bây giờ" dù đang xem ngày quá khứ rất
        # xa (lẽ ra phải là "Installs cuối ngày"/"LTV cuối ngày" như cột giờ đã
        # tự đổi đúng) — sửa dùng chung 1 biến để nhất quán.
        _end_word = _now_or_end_label.lower()
        realtime_rows = [
            {
                "Campaign": f["campaign"],
                "Nguồn": _channel_map.get(f["campaign"], "?"),
                "Chiều": "📈 Tăng" if f["direction"] == "tang" else "📉 Giảm",
                "Khoảng cách (tự chọn)": f"{f['actual_hours_gap']:.1f}h",
                "Lúc đó": f["baseline_ts"][11:16],
                _now_or_end_label: f["latest_ts"][11:16],
                "Installs lúc đó": f["baseline"].get("installs_cum"),
                f"Installs {_end_word}": f["latest"].get("installs_cum"),
                "LTV lúc đó": f["baseline"].get("arpu"),
                f"LTV {_end_word}": f["latest"].get("arpu"),
                "LTV % đổi": f["arpu_pct_change"],
            }
            for f in all_flagged_today
        ]
        _realtime_df = pd.DataFrame(realtime_rows)
        st.dataframe(
            _realtime_df.style.map(_color_pct, subset=["LTV % đổi"]),
            width="stretch", hide_index=True,
            column_config={
                "LTV lúc đó": st.column_config.NumberColumn(format="$%.4f"),
                f"LTV {_end_word}": st.column_config.NumberColumn(format="$%.4f"),
                "LTV % đổi": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            "Mỗi campaign TỰ quét toàn bộ giờ nó có dữ liệu trong ngày để tìm "
            "cặp giờ cho LTV đổi NHIỀU NHẤT (không ép cùng 1 mốc cho mọi "
            "campaign nữa — đổi 24/09/2026) — cột \"Khoảng cách (tự chọn)\" "
            "cho biết campaign đó cách nhau bao nhiêu tiếng. Cột \"Chiều\" cho "
            "biết đang là cơ hội (📈 tăng) hay vấn đề (📉 giảm). Vào trang "
            "**Xét nghiệm** để xem gợi ý hành động tương ứng."
        )

    st.divider()
    since_col1, since_col2 = st.columns([1, 3])
    with since_col1:
        al_since_hour = st.number_input(
            f"So với giờ nào của {_date_label}?", min_value=0, max_value=23, value=8, step=1,
            key="al_since_hour",
            help="VD 8 = so với ~8h sáng. Mặc định 0h (nửa đêm) không hữu ích "
            "vì gần như chưa có hoạt động gì để so sánh.",
        )
    with since_col2:
        st.write("")
        st.caption(f"Xem thêm: so với ~{int(al_since_hour):02d}h00 của {_date_label} (tự chọn giờ ở ô bên trái).")

    all_flagged_since_hour = ia.list_flagged_since_hour(
        cum_df_scope, baseline_hour_of_day=int(al_since_hour),
        threshold_pct=float(al_realtime_pct), min_installs=int(al_min_installs),
    )
    if not all_flagged_since_hour:
        st.caption(f"Chưa có gì vượt ngưỡng so với ~{int(al_since_hour):02d}h00 của {_date_label}.")
    else:
        _end_word = _now_or_end_label.lower()
        since_hour_rows = [
            {
                "Campaign": f["campaign"],
                "Nguồn": _channel_map.get(f["campaign"], "?"),
                "Chiều": "📈 Tăng" if f["direction"] == "tang" else "📉 Giảm",
                f"Lúc ~{int(al_since_hour):02d}h": f["baseline_ts"][11:16],
                _now_or_end_label: f["latest_ts"][11:16],
                "Installs lúc đó": f["baseline"].get("installs_cum"),
                f"Installs {_end_word}": f["latest"].get("installs_cum"),
                "LTV lúc đó": f["baseline"].get("arpu"),
                f"LTV {_end_word}": f["latest"].get("arpu"),
                "LTV % đổi": f["arpu_pct_change"],
            }
            for f in all_flagged_since_hour
        ]
        _since_hour_df = pd.DataFrame(since_hour_rows)
        st.dataframe(
            _since_hour_df.style.map(_color_pct, subset=["LTV % đổi"]),
            width="stretch", hide_index=True,
            column_config={
                "LTV lúc đó": st.column_config.NumberColumn(format="$%.4f"),
                f"LTV {_end_word}": st.column_config.NumberColumn(format="$%.4f"),
                "LTV % đổi": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )



# ══════════════════════════════════════════════════════════════════════
# TRANG — Xét nghiệm (Campaign Doctor): tầng 1 (CPI đắt vs User kém) + tầng 2
# (nguyên nhân sâu) + gợi ý hành động + cắt lát theo quốc gia/creative
# ══════════════════════════════════════════════════════════════════════
def page_campaign_doctor():
    st.title("Xét nghiệm")
    st.caption(
        "Xét nghiệm 1 campaign đang bị cảnh báo: CPI đắt hay User kém? Vì sao? "
        "Nên làm gì? Quốc gia/creative nào đang kéo xuống?"
    )

    # Nguồn danh sách campaign đang bị cảnh báo: ĐỔI sang danh sách REALTIME
    # (22/09/2026, sau khi bỏ "xu hướng nhiều ngày" khỏi trang Cảnh báo) — xem
    # `al_realtime_flagged` (list dict từ ia.list_flagged_best_swing(), tự
    # flex theo từng campaign — đổi 24/09/2026), lưu bởi page_alerts().
    if st.session_state.get("al_realtime_flagged") is None or st.session_state.get("al_raw_df") is None:
        st.info(
            "👆 Vào trang **Cảnh báo** trước — chọn app + khoảng ngày, nhập token "
            "Adjust, bấm **Apply** — rồi quay lại đây để chọn campaign cần xét nghiệm."
        )
        return

    realtime_flagged = st.session_state.al_realtime_flagged
    product_id = st.session_state.al_product_used
    raw_df = st.session_state.al_raw_df
    days_back_used = st.session_state.al_days_back_used

    if not realtime_flagged:
        st.success(f"✅ App {product_id} hiện không có campaign nào bị cảnh báo trong ngày — chưa cần xét nghiệm.")
        return

    campaign_options = [f["campaign"] for f in realtime_flagged]

    def _flags_label(f: dict) -> str:
        # ĐỔI 24/09/2026: Cảnh báo trong ngày giờ bắt CẢ 2 CHIỀU LTV tăng/giảm
        # (xem intraday_alerts.py) — nhãn phản ánh đúng chiều.
        return "📈 LTV tăng" if f.get("direction") == "tang" else "📉 LTV giảm"

    label_map = {f["campaign"]: _flags_label(f) for f in realtime_flagged}
    flag_by_campaign = {f["campaign"]: f for f in realtime_flagged}
    selected_campaign = st.selectbox(
        f"Chọn campaign cần xét nghiệm (app {product_id}, {len(campaign_options)} campaign đang bị cảnh báo trong ngày)",
        campaign_options,
        format_func=lambda c: f"[{label_map[c]}] {c[:70]}{'...' if len(c) > 70 else ''}",
        key="doc_selected_campaign",
    )

    # THÊM 24/09/2026 (theo yêu cầu user): gợi ý HÀNH ĐỘNG dựa trên CHIỀU của
    # tín hiệu realtime đưa campaign này vào đây — tách biệt với Tầng 1 (vốn
    # so benchmark theo NGÀY/QUỐC GIA, không liên quan tín hiệu trong ngày).
    #
    # SỬA 24/09/2026 (user chỉ ra): trang Cảnh báo mặc định xem NGÀY ĐÃ QUA
    # (không phải "hôm nay") — gợi ý kiểu "tăng ngân sách NGAY TRONG NGÀY" vô
    # nghĩa với dữ liệu quá khứ (ngày đó đã qua rồi, không "hành động ngay"
    # được nữa). Phân biệt rõ 2 trường hợp: đang xem "hôm nay" (số vẫn đang
    # chạy, HÀNH ĐỘNG NGAY được) vs xem NGÀY QUÁ KHỨ (chỉ là 1 QUAN SÁT, cần
    # coi đây là gợi ý về QUY LUẬT khung giờ để áp dụng cho NGÀY SAU, không
    # phải hành động tức thời — và chỉ dựa trên 1 ngày nên CHƯA CHẮC là quy
    # luật thật, cần xem nhiều ngày mới kết luận chắc).
    _flag = flag_by_campaign[selected_campaign]
    _pct = _flag.get("arpu_pct_change") or 0
    _gap = _flag.get("actual_hours_gap")
    _view_date_iso2 = st.session_state.get("al_view_date_used")
    _is_today_view2 = _view_date_iso2 == date.today().isoformat()
    _baseline_hhmm = _flag["baseline_ts"][11:16]
    _latest_hhmm = _flag["latest_ts"][11:16]

    if _flag.get("direction") == "tang":
        st.success(
            f"📈 **LTV đang TĂNG {_pct:.1f}%** trong khoảng ~{_gap:.1f} tiếng qua "
            f"({_baseline_hhmm} → {_latest_hhmm}) — tín hiệu TỐT."
        )
        if _is_today_view2:
            st.markdown(
                "**Gợi ý hành động (đang xem HÔM NAY — hành động NGAY được):**\n"
                "- Cân nhắc **tăng ngân sách ngay bây giờ** để tận dụng thời điểm "
                "LTV cao — chờ đến hôm sau có thể lỡ mất giai đoạn tốt.\n"
                "- Xem **cắt lát quốc gia/creative** bên dưới để biết ĐÚNG nước/"
                "creative nào đang kéo LTV lên — ưu tiên nhân rộng đúng chỗ đó "
                "thay vì tăng ngân sách dàn trải cho cả campaign."
            )
        else:
            st.markdown(
                f"**Gợi ý (đang xem NGÀY ĐÃ QUA, {_baseline_hhmm}-{_latest_hhmm} "
                f"của ngày đó — không còn \"hành động ngay\" được nữa, đây là 1 "
                "QUAN SÁT để tham khảo):**\n"
                f"- Khung giờ **{_baseline_hhmm}-{_latest_hhmm}** có vẻ là lúc LTV "
                "tốt cho campaign này — nếu khung giờ này LẶP LẠI ở nhiều ngày "
                "khác (chưa chắc chắn chỉ với 1 ngày), có thể cân nhắc tăng ngân "
                "sách vào ĐÚNG khung giờ này ở các ngày TỚI.\n"
                "- Xem **cắt lát quốc gia/creative** bên dưới để biết nước/creative "
                "nào đang kéo LTV lên trong khung giờ đó."
            )
    else:
        st.warning(
            f"📉 **LTV đang GIẢM {_pct:.1f}%** trong khoảng ~{_gap:.1f} tiếng qua "
            f"({_baseline_hhmm} → {_latest_hhmm}) — cần theo dõi sát."
        )
        if _is_today_view2:
            st.markdown(
                "**Gợi ý hành động (đang xem HÔM NAY — hành động NGAY được):**\n"
                "- Cân nhắc **tạm giảm ngân sách** hoặc theo dõi thêm 1-2 mốc giờ "
                "nữa trước khi cắt hẳn — LTV cuối ngày có thể tạm thấp chỉ vì "
                "installs mới chưa kịp sinh doanh thu (không phải chất lượng "
                "user tệ thật), xem lại với ngày đã qua lâu hơn để chắc chắn "
                "trước khi quyết định.\n"
                "- Xem **cắt lát quốc gia/creative** bên dưới để biết ĐÚNG nước/"
                "creative nào đang kéo xuống trước khi quyết định cắt cả campaign."
            )
        else:
            st.markdown(
                f"**Gợi ý (đang xem NGÀY ĐÃ QUA, {_baseline_hhmm}-{_latest_hhmm} "
                f"của ngày đó — không còn \"hành động ngay\" được nữa, đây là 1 "
                "QUAN SÁT để tham khảo):**\n"
                f"- Khung giờ **{_baseline_hhmm}-{_latest_hhmm}** có vẻ là lúc LTV "
                "kém cho campaign này — nếu khung giờ này LẶP LẠI ở nhiều ngày "
                "khác (chưa chắc chắn chỉ với 1 ngày), có thể cân nhắc giảm ngân "
                "sách/dời budget sang khung giờ khác vào các ngày TỚI, thay vì "
                "cắt cả campaign.\n"
                "- Xem **cắt lát quốc gia/creative** bên dưới để biết nước/creative "
                "nào đang kéo xuống trong khung giờ đó."
            )

    # Benchmark ĐỔI sang nhập THEO QUỐC GIA (23/09/2026, trang "Benchmark") —
    # Tầng 1 (đánh giá CẢ campaign, gộp mọi quốc gia) KHÔNG còn 1 benchmark
    # app-level để so nữa. Việc so benchmark có ý nghĩa giờ nằm ở TỪNG QUỐC
    # GIA (mỗi dòng dùng benchmark của ĐÚNG quốc gia đó) — xem Tầng 2 bên dưới.
    doc_threshold = 20.0

    # SỬA 24/09/2026 (user chỉ ra 2 vấn đề): (1) thông báo cũ "nhập benchmark ở
    # trên" trỏ SAI CHỖ — trang này không còn ô nhập benchmark nào nữa (đã
    # chuyển hẳn sang trang "Benchmark" từ 23/09/2026); (2) số CPI/LTV/ROAS D0/
    # Retention D1 gộp CẢ CAMPAIGN chỉ có ý nghĩa nếu campaign chạy 1 THỊ
    # TRƯỜNG RIÊNG (tên có tên nước, VD "Mexico"/"US") — nếu campaign chạy
    # GLOBAL (tên có chữ "GLOBAL", gộp nhiều nước), số này bị PHA LOÃNG qua
    # nhiều nước nên không phản ánh đúng nước nào cả, dễ hiểu lầm là "ổn". Phát
    # hiện GLOBAL bằng cách tìm chữ "global" (không phân biệt hoa/thường) trong
    # tên campaign — theo đúng quy ước đặt tên UA team đang dùng.
    _is_global_campaign = "global" in selected_campaign.lower()
    if _is_global_campaign:
        st.warning(
            "⚠️ Campaign này chạy **GLOBAL** (gộp nhiều quốc gia) — số CPI/LTV/"
            "ROAS D0/Retention D1 ở Tầng 1 bên dưới là số TRUNG BÌNH của TẤT CẢ "
            "thị trường cộng lại nên bị PHA LOÃNG, không phản ánh đúng thị "
            "trường cụ thể nào (dễ trông \"ổn\" dù có 1 vài nước đang tệ). Xem "
            "**Tầng 2** ngay bên dưới để đánh giá đúng theo từng thị trường."
        )
    else:
        st.info(
            "ℹ️ Campaign này chạy 1 thị trường riêng nên số Tầng 1 bên dưới khá "
            "sát với thị trường đó. Xem **Tầng 2** ngay bên dưới để so trực tiếp "
            "với benchmark của đúng thị trường này (benchmark nhập ở trang "
            "**Benchmark**)."
        )

    stats = cdoc.period_stats_for_campaign(raw_df, product_id, selected_campaign)
    if stats is None:
        st.warning("Không tìm thấy dữ liệu Adjust cho campaign này (có thể do đổi bộ lọc).")
        return

    st.divider()
    st.subheader("Tầng 1 — CPI đắt hay User kém?")
    tcol1, tcol2, tcol3, tcol4 = st.columns(4)
    tcol1.metric("CPI thực tế", fmt_money(stats["cpi"]))
    tcol2.metric("LTV (ARPU D0) thực tế", fmt_money(stats.get("arpu_d0")))
    tcol3.metric("ROAS D0 thực tế", fmt_percent(stats["roas_d0"]))
    tcol4.metric("Retention D1 thực tế", fmt_percent(stats["retention_d1"]))

    suggestions = []

    # TẦNG 2 — HỒI SINH 24/09/2026 với thiết kế MỚI (xem docstring
    # cdoc.top_markets_slice()/cdoc.detect_phantom_revenue() trong
    # campaign_doctor.py). Bản CŨ dùng benchmark gộp cả campaign
    # (`tier1["cpi_dat"]`/`tier1["user_kem"]`) — từ 23/09/2026 benchmark đó
    # LUÔN rỗng nên 2 cờ LUÔN False, Tầng 2 ÂM THẦM không hiện ra nữa, user
    # phát hiện lại. Bản mới TỰ ĐỘNG lấy dữ liệu quốc gia của CHÍNH campaign
    # này (không cần bấm nút — cache 15 phút, không tốn thêm lệnh gọi API nếu
    # đã tải trong 15 phút qua, dùng lại đúng loader đã có ở tab "Theo quốc
    # gia"), xét CPI/LTV cho TOP 3 thị trường TIÊU NHIỀU NHẤT — chạy đúng cho
    # CẢ GLOBAL (top 3 thị trường quan trọng) LẪN campaign lẻ 1 thị trường
    # (top 3 tự nhiên co về đúng 1 dòng).
    benchmark_by_country = bm.get_all_country_benchmarks(product_id)
    country_raw, country_err, country_warning = load_campaign_country_data(
        selected_campaign, days_back_used,
        st.session_state.get("adjust_app_tokens", ""),
        st.session_state.get("adjust_api_token", ""),
    )
    st.session_state.doc_country_raw = country_raw
    st.session_state.doc_country_err = country_err
    st.session_state.doc_country_campaign = selected_campaign

    st.divider()
    st.subheader("Tầng 2 — Thị trường nào đang quyết định kết quả campaign?")
    if country_err:
        st.error(f"❌ {country_err}")
    elif country_raw is None or country_raw.empty:
        st.caption("Chưa có dữ liệu theo quốc gia cho campaign này trong khoảng ngày đã kéo.")
    else:
        top_df = cdoc.top_markets_slice(country_raw, benchmark_by_country=benchmark_by_country, top_n=3)
        if top_df.empty:
            st.caption("Không có thị trường nào đủ install tối thiểu (≥5) để xét.")
        else:
            st.caption(
                f"Top {len(top_df)} thị trường TIÊU NHIỀU NHẤT (network_cost) trong "
                "campaign này — campaign chạy lẻ 1 thị trường sẽ tự nhiên chỉ còn 1 "
                "dòng (các nước khác quá ít install bị lọc bớt)."
            )
            st.dataframe(
                top_df, width="stretch", hide_index=True,
                column_config={
                    "Chi tiêu": st.column_config.NumberColumn(format="$%.2f"),
                    "Doanh thu": st.column_config.NumberColumn(format="$%.2f"),
                    "CPI": st.column_config.NumberColumn(format="$%.4f"),
                    "LTV (ARPU D0)": st.column_config.NumberColumn(format="$%.4f"),
                    "ROAS D0": st.column_config.NumberColumn(format="percent"),
                    "Retention D1": st.column_config.NumberColumn(format="percent"),
                    "CPI so benchmark": st.column_config.NumberColumn(format="%.1f%%"),
                    "LTV so benchmark": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            _canh_bao_col = top_df.get("Cảnh báo", pd.Series(dtype=str)).fillna("")
            any_cpi_dat = _canh_bao_col.str.contains("CPI đắt").any()
            any_ltv_kem = _canh_bao_col.str.contains("LTV thấp").any()

            # THÊM 24/09/2026 (theo yêu cầu user): phát hiện doanh thu từ quốc
            # gia KHÔNG có install nào trong campaign này — giải thích vì sao
            # ROAS D0 gộp cả campaign vẫn ổn dù thị trường chính ở trên tệ.
            phantom_df = cdoc.detect_phantom_revenue(country_raw)
            if not phantom_df.empty:
                # Escape "\$" — 2+ dấu "$" trong CÙNG 1 lần gọi st.warning()/
                # st.caption() (khi có ≥2 quốc gia phantom) bị Streamlit hiểu
                # nhầm thành ranh giới công thức LaTeX, nuốt mất chữ ở giữa
                # (xem lỗi tương tự đã sửa ở hourly_market_patterns.py).
                _phantom_list = ", ".join(
                    f"{r['Quốc gia']} (\\${r['Doanh thu (không có install)']:.2f})"
                    for _, r in phantom_df.iterrows()
                )
                if any_cpi_dat or any_ltv_kem:
                    st.warning(
                        f"⚠️ Phát hiện doanh thu ads từ quốc gia KHÔNG có install nào "
                        f"trong campaign này: {_phantom_list}. Đây có thể là lý do ROAS "
                        f"D0 GỘP CẢ CAMPAIGN ({fmt_percent(stats['roas_d0'])}) vẫn trông "
                        "ổn dù thị trường chính ở trên đang có vấn đề — doanh thu \"lạ\" "
                        "ngoài thị trường mục tiêu (user đổi vị trí sau khi cài, hoặc "
                        "Adjust gán quốc gia theo nơi PHÁT SINH sự kiện thay vì nơi cài) "
                        "đang bù vào, KHÔNG PHẢI vì thị trường chính đang tốt thật. Các "
                        "quốc gia này KHÔNG có install nên KHÔNG được đưa vào bảng/chẩn "
                        "đoán/gợi ý ở trên — chỉ đánh giá + suggest theo đúng thị trường "
                        "có install."
                    )
                else:
                    st.caption(
                        f"ℹ️ Ghi nhận thêm: có doanh thu từ quốc gia không có install "
                        f"nào ({_phantom_list}) — các quốc gia này KHÔNG được đưa vào "
                        "bảng/chẩn đoán ở trên (không có install để tính CPI/LTV), không "
                        "ảnh hưởng tới kết luận."
                    )

            # THÊM 24/09/2026 (user chỉ ra giải thích/gợi ý cũ "quá chung
            # chung, không mang lại giá trị gì"): thay câu canned dùng chung
            # ("LTV thấp hơn benchmark ở (các) thị trường chính...") bằng chẩn
            # đoán CỤ THỂ cho TỪNG thị trường — nêu tên, số thực tế/% lệch
            # benchmark, thị trường đó chiếm bao nhiêu % ngân sách/install của
            # cả campaign để biết nên xử lý RIÊNG thị trường đó hay phải xem
            # lại CẢ campaign (xem docstring cdoc.build_top_market_findings()).
            market_findings = cdoc.build_top_market_findings(
                top_df, stats["installs"], stats["network_cost"]
            )
            if market_findings:
                st.divider()
                st.subheader("Chi tiết theo từng thị trường có vấn đề")
                for f in market_findings:
                    _finding_text = cdoc.describe_market_finding(f)
                    st.markdown(f"- 🔴 {_finding_text}")
                    suggestions.append(_finding_text)

            if any_cpi_dat:
                st.divider()
                st.subheader("Đào sâu CPI đắt: so CPM/CTR/CVR với các campaign khác cùng app")
                st.caption(
                    "CPM/CTR/CVR tính từ network_impressions/network_clicks của Adjust "
                    "(network tự báo cáo, cùng nguồn với network_cost) — không cần BigQuery."
                )
                this_stats = cdoc.aggregate_adjust_funnel(raw_df, product_id, campaign=selected_campaign)
                peer_stats = cdoc.aggregate_adjust_funnel(raw_df, product_id, exclude_campaign=selected_campaign)
                if not this_stats["installs"]:
                    st.warning("Không có đủ dữ liệu impressions/clicks cho campaign này để mổ xẻ CPM/CTR/CVR.")
                else:
                    pcol1, pcol2, pcol3 = st.columns(3)
                    pcol1.metric(
                        "CPM campaign này", f"${this_stats['cpm']:.2f}" if this_stats["cpm"] else "N/A",
                        delta=f"peer TB: ${peer_stats['cpm']:.2f}" if peer_stats["cpm"] else None,
                    )
                    pcol2.metric(
                        "CTR campaign này", f"{this_stats['ctr_pct']:.2f}%" if this_stats["ctr_pct"] else "N/A",
                        delta=f"peer TB: {peer_stats['ctr_pct']:.2f}%" if peer_stats["ctr_pct"] else None,
                    )
                    pcol3.metric(
                        "CVR campaign này", f"{this_stats['cvr_pct']:.2f}%" if this_stats["cvr_pct"] else "N/A",
                        delta=f"peer TB: {peer_stats['cvr_pct']:.2f}%" if peer_stats["cvr_pct"] else None,
                    )
                    tier2_cpi = cdoc.diagnose_tier2_cpi(this_stats, peer_stats, threshold_pct=doc_threshold)
                    if tier2_cpi["findings"]:
                        for label, pct in tier2_cpi["findings"]:
                            st.markdown(f"- **{label}** ({pct:+.1f}%)")
                            suggestions.append(cdoc.SUGGESTION_TEXT[label])
                    else:
                        st.caption("CPM/CTR/CVR không lệch rõ rệt so với các campaign khác — CPI đắt có thể do nguyên nhân khác (VD cạnh tranh chung toàn thị trường).")

    if suggestions:
        st.divider()
        st.subheader("Gợi ý hành động")
        for s in suggestions:
            st.markdown(f"- {s}")

    st.divider()
    st.subheader("Cắt lát khoanh vùng")
    slice_tab1, slice_tab2 = st.tabs(["Theo quốc gia", "Theo creative"])

    with slice_tab1:
        # ĐÃ BỎ nút "Tải dữ liệu theo quốc gia" (24/09/2026) — Tầng 2 ở trên
        # giờ TỰ ĐỘNG tải `country_raw`/`benchmark_by_country` rồi (cache 15
        # phút), tái dùng thẳng ở đây, không cần bấm thêm lần nữa.
        if country_err:
            st.error(f"❌ {country_err}")
        elif country_raw is None or country_raw.empty:
            st.caption("Chưa có dữ liệu theo quốc gia cho campaign này.")
        else:
            # Benchmark giờ nhập THEO QUỐC GIA (trang "Benchmark") — mỗi dòng
            # quốc gia trong bảng dưới đây so với ĐÚNG benchmark của chính nó
            # (khác app-level benchmark chung dùng trước 23/09/2026 — xem
            # docstring cdoc.country_slice() + benchmarks.get_all_country_benchmarks()).
            country_df = cdoc.country_slice(country_raw, benchmark_by_country=benchmark_by_country)
            if country_df.empty:
                st.warning("Không có dữ liệu theo quốc gia cho campaign này trong khoảng ngày đã kéo.")
            else:
                st.dataframe(
                    country_df, width="stretch", hide_index=True,
                    column_config={
                        "Chi tiêu": st.column_config.NumberColumn(format="$%.2f"),
                        "Doanh thu": st.column_config.NumberColumn(format="$%.2f"),
                        "CPI": st.column_config.NumberColumn(format="$%.4f"),
                        "LTV (ARPU D0)": st.column_config.NumberColumn(format="$%.4f"),
                        "ROAS D0": st.column_config.NumberColumn(format="percent"),
                        "Retention D1": st.column_config.NumberColumn(format="percent"),
                        "CPI so benchmark": st.column_config.NumberColumn(format="%.1f%%"),
                        "LTV so benchmark": st.column_config.NumberColumn(format="%.1f%%"),
                    },
                )
                st.caption(
                    "ROAS D0 thấp nhất lên đầu — nghi phạm chính. Đã bỏ quốc gia <5 "
                    "installs (quá ít để có ý nghĩa). Cột \"CPI/LTV so benchmark\" "
                    "và \"Cảnh báo\" dùng benchmark ĐÃ NHẬP CHO ĐÚNG QUỐC GIA ĐÓ ở "
                    "trang Benchmark — quốc gia nào chưa nhập benchmark, 2 cột này "
                    "sẽ trống."
                )

    with slice_tab2:
        st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")
        creative_fetch_clicked = st.button("Tải dữ liệu creative", key="doc_creative_fetch")

        if creative_fetch_clicked:
            creative_raw, creative_err, creative_warning = load_creative_data(
                days_back_used,
                st.session_state.get("adjust_app_tokens", ""),
                st.session_state.get("adjust_api_token", ""),
            )
            st.session_state.doc_creative_raw = creative_raw
            st.session_state.doc_creative_err = creative_err

        creative_raw = st.session_state.get("doc_creative_raw")
        if st.session_state.get("doc_creative_err"):
            st.error(f"❌ {st.session_state.doc_creative_err}")
        elif creative_raw is None:
            st.info("👆 Bấm **Tải dữ liệu creative** để xem creative nào đang kéo campaign này xuống.")
        else:
            creative_view = cdoc.creative_slice(creative_raw, selected_campaign)
            if creative_view.empty:
                st.warning("Không có dữ liệu creative cho campaign này trong khoảng ngày đã kéo.")
            else:
                st.dataframe(
                    creative_view, width="stretch", hide_index=True,
                    column_config={
                        "CPI": st.column_config.NumberColumn(format="$%.4f"),
                        "ROAS D0": st.column_config.NumberColumn(format="percent"),
                        "Retention D1": st.column_config.NumberColumn(format="percent"),
                    },
                )
                st.caption("ROAS D0 thấp nhất lên đầu — nghi phạm chính.")


# ══════════════════════════════════════════════════════════════════════
# TRANG — Xét nghiệm › Tổng quan thị trường (TÁCH RIÊNG 24/09/2026 — trước đó
# là tab "Theo khung giờ" nằm trong "Cắt lát khoanh vùng" của trang Xét
# nghiệm/Theo campaign, user yêu cầu tách hẳn thành 1 tính năng con riêng vì
# đây là phân tích TỔNG QUAN nhiều ngày/nhiều thị trường, không gắn với 1
# campaign cụ thể đang xét nghiệm nào — không cần vào Cảnh báo trước như
# "Theo campaign", tự chọn App trực tiếp (giống trang Benchmark)).
# ══════════════════════════════════════════════════════════════════════
def page_market_overview():
    st.title("Tổng quan thị trường")
    st.caption(
        "Tìm QUY LUẬT LTV theo GIỜ TRONG NGÀY cho từng thị trường, gộp qua "
        "NHIỀU NGÀY đã chốt — để biết khung giờ nào nên tăng/giảm ngân sách "
        "cho từng thị trường (không phải nhiễu ngẫu nhiên của 1 ngày). Dữ liệu "
        "TỔNG HỢP CẢ APP (mọi campaign chạy market đó) — quy luật giờ theo thị "
        "trường là hành vi người dùng theo múi giờ, áp dụng chung cho mọi "
        "campaign, không riêng 1 campaign cụ thể. **CHỈ dùng LTV** — không có "
        "CPI/ROAS theo giờ (chi phí không có grain thật theo giờ, xem "
        "GHI_CHU_TIEN_DO.md)."
    )
    api_token = st.session_state.get("adjust_api_token", "")
    app_tokens_raw = st.session_state.get("adjust_app_tokens", "")
    st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")

    product_ids, ids_err = get_known_product_ids(app_tokens_raw, api_token)
    if ids_err:
        st.info(f"👆 {ids_err}")
        return
    if not product_ids:
        st.warning("Không tìm thấy app nào cho token này trong 7 ngày qua — kiểm tra lại App Token ở sidebar.")
        return

    product_id = st.selectbox("App", product_ids, key="hmp_page_app")

    hmp_days_back = st.number_input(
        "Số ngày gộp lại để tìm quy luật", min_value=7, max_value=30, value=14, step=7,
        key="hmp_days_back",
        help="Nhiều ngày hơn → quy luật đáng tin hơn nhưng tải lâu hơn (đã "
        "đo thật: 14 ngày mất ~14 giây).",
    )
    hmp_fetch_clicked = st.button("Tải dữ liệu theo giờ × quốc gia", key="hmp_fetch")

    if hmp_fetch_clicked:
        hmp_raw, hmp_err = load_hourly_market_data(int(hmp_days_back), app_tokens_raw, api_token)
        st.session_state.hmp_raw = hmp_raw
        st.session_state.hmp_err = hmp_err
        st.session_state.hmp_product_used = product_id

    hmp_raw = st.session_state.get("hmp_raw")
    hmp_stale = st.session_state.get("hmp_product_used") != product_id
    if st.session_state.get("hmp_err"):
        st.error(f"❌ {st.session_state.hmp_err}")
    elif hmp_raw is None or hmp_stale:
        st.info("👆 Bấm **Tải dữ liệu theo giờ × quốc gia** để xem quy luật.")
    elif hmp_raw.empty:
        st.warning("Không có dữ liệu cho app này trong khoảng ngày đã chọn.")
    else:
        hmp_scope = hmp_raw[hmp_raw["app"].str.startswith(product_id)]
        patterns = hmp_module.build_hourly_market_patterns(hmp_scope)
        if patterns.empty:
            st.warning(
                "Không đủ dữ liệu để tìm quy luật (quá ít install theo từng "
                "giờ/quốc gia — thử tăng số ngày gộp lại)."
            )
        else:
            summary = hmp_module.summarize_peak_and_low_hours(patterns)
            if summary.empty:
                st.warning(
                    "Chưa đủ giờ có dữ liệu ở các thị trường để so sánh giờ "
                    "vàng/giờ đáy — thử tăng số ngày gộp lại."
                )
            else:
                st.dataframe(
                    summary, width="stretch", hide_index=True,
                    column_config={
                        "LTV giờ vàng (TB)": st.column_config.NumberColumn(format="$%.4f"),
                        "LTV giờ đáy (TB)": st.column_config.NumberColumn(format="$%.4f"),
                        "Chênh lệch (%)": st.column_config.NumberColumn(format="percent"),
                    },
                )
                st.caption("Chênh lệch cao nhất lên đầu — thị trường có khác biệt rõ rệt giữa giờ tốt/xấu nhất, đáng cân nhắc điều chỉnh ngân sách theo khung giờ trước.")

                # THÊM 24/09/2026 (theo yêu cầu user — "bảng ... hãy có cả
                # suggest ở dưới ... theo đầu thị trường"): gợi ý CỤ THỂ cho
                # TỪNG thị trường (không chỉ 1 câu chung chung như trước).
                st.markdown("**Gợi ý hành động theo từng thị trường:**")
                for s in hmp_module.build_market_suggestions(summary):
                    st.markdown(f"- **{s['Quốc gia']}**: {s['Gợi ý']}")

                # SỬA 24/09/2026 (theo yêu cầu user — bảng dump hết mọi thị
                # trường/giờ "không thuận lợi cho việc xem data"): thay bằng
                # chọn ĐÚNG 1 thị trường + vẽ biểu đồ trend LTV theo giờ cho
                # thị trường đó, dễ nhìn tổng quan hơn nhiều so với bảng dài.
                st.divider()
                st.subheader("Xem trend LTV theo giờ — chọn 1 thị trường")
                market_options = sorted(patterns["Quốc gia"].unique())
                selected_market = st.selectbox("Thị trường", market_options, key="hmp_selected_market")
                market_detail = patterns[patterns["Quốc gia"] == selected_market].sort_values("Giờ")
                st.line_chart(market_detail.set_index("Giờ")[["LTV"]])
                st.dataframe(
                    market_detail[["Giờ", "Installs", "LTV"]], width="stretch", hide_index=True,
                    column_config={"LTV": st.column_config.NumberColumn(format="$%.4f")},
                )


# ══════════════════════════════════════════════════════════════════════
# Điều hướng — API GỐC của Streamlit (st.navigation), có icon + nhóm danh mục
# ══════════════════════════════════════════════════════════════════════
# Đã bỏ HẲN mọi trang liên quan BigQuery/eCPM (22/09/2026 — user chỉ ra
# BigQuery không có dữ liệu realtime nên vô dụng cho việc theo dõi/chẩn đoán):
# "Report Builder", "Market Board", "Meta + Adjust" — xem GHI_CHU_TIEN_DO.md.
# THÊM trang "Benchmark" (23/09/2026) — tách riêng khỏi trang Xét nghiệm (và
# trước đó thử để ở sidebar, user phản hồi bất tiện) để có đủ chỗ nhập +
# nhìn benchmark, dùng chung cho Tầng 1 lẫn tab "Theo quốc gia" ở Xét nghiệm.
# TÁCH "Xét nghiệm" thành NHÓM có 2 tính năng con (24/09/2026, theo yêu cầu
# user): "Theo campaign" (bản cũ — Tầng 1/Tầng 2/cắt lát cho 1 campaign cụ
# thể đang bị cảnh báo) và "Tổng quan thị trường" (tách từ tab "Theo khung
# giờ" cũ — phân tích TỔNG QUAN nhiều ngày để tìm quy luật giờ vàng/giờ đáy
# LTV theo thị trường, không gắn với 1 campaign cụ thể). Dùng dict thay vì
# list để `st.navigation()` tự vẽ dropdown/nhóm trong sidebar — các trang còn
# lại giữ nguyên KHÔNG nhóm (key rỗng "" không hiện tiêu đề nhóm).
pg = st.navigation(
    {
        "": [
            st.Page(page_adjust, title="Adjust", icon=":material/monitoring:", default=True),
            st.Page(page_alerts, title="Cảnh báo", icon=":material/warning:"),
            st.Page(page_benchmark, title="Benchmark", icon=":material/rule:"),
        ],
        "Xét nghiệm": [
            st.Page(page_campaign_doctor, title="Theo campaign", icon=":material/stethoscope:"),
            st.Page(page_market_overview, title="Tổng quan thị trường", icon=":material/public:"),
        ],
    },
    expanded=True,
)
pg.run()
