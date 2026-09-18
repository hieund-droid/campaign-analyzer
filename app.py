"""
Dashboard Streamlit — điều hướng bằng `st.navigation()` (API điều hướng GỐC của
Streamlit, không tự chế bằng radio nữa) — cho icon + nhóm danh mục kiểu 1 BI
tool nội bộ khác của Apero. Việc thu/mở cả sidebar là tính năng có sẵn của
Streamlit (không phải do code này), phần code cải thiện là icon + nhóm mục.

4 trang, nhóm theo 2 danh mục:
- Mục lẻ (không thuộc danh mục nào):
  - "Adjust" (đổi tên từ "Dashboard" 16/09/2026 — user chỉ ra tên cũ quá
    chung chung, không nói rõ đây là nguồn Adjust, trong khi các trang khác
    đều đặt tên theo nguồn/chức năng): installs, CPI, ad revenue, ROAS
    D0/D7/D30, retention D1/D7, ARPU. MỖI NGƯỜI TỰ NHẬP API Token + App Token
    của mình (mỗi người dùng account Adjust riêng) — không dùng chung
    Secrets, chỉ lưu tạm trong session của họ.
  - "Meta + Adjust": ghép dữ liệu Meta (BigQuery, channel="Facebook") với
    Adjust theo campaign + ngày + quốc gia — xem `meta_adjust_merge.py` để
    biết cách ghép (đã kiểm chứng khớp 100% campaign_id bằng số thật). Vẫn
    cần token Adjust cá nhân (dùng chung ô nhớ với trang Adjust). Có thêm
    PL2 (lãi marketing = ad_revenue − spend, đã chốt công thức với user).
  - "Cảnh báo": 2 phần — (1) "Trong ngày (thời gian thực)": so lần chụp đầu
    hôm nay với lần mới nhất, dùng `campaign_snapshots.py` (chia sẻ kho
    snapshot với trang Adjust) — trả lời đúng nỗi đau "sáng rẻ, chiều tăng
    vọt" (user phản ánh 16/09/2026); (2) "Theo xu hướng nhiều ngày": phát
    hiện đột biến/giảm dần CPI/ROAS D0 giữa các NGÀY ĐÃ CHỐT — xem
    `campaign_alerts.py`. Cả 2 chỉ dùng Adjust (không cần ghép BigQuery, áp
    dụng mọi channel).
  - "Chẩn đoán" (Campaign Doctor): chọn 1 campaign đang bị cảnh báo (đọc từ
    trang Cảnh báo) → chẩn đoán tầng 1 (CPI đắt/User kém, so benchmark tự
    nhập) → tầng 2 (CPM/CTR/CVR so peer nếu CPI đắt; Retention/ROAS nếu User
    kém) → gợi ý hành động → cắt lát theo quốc gia + creative — xem
    `campaign_doctor.py`.
- "BigQuery" (danh mục, 2 trang con — cả 2 đều lấy dữ liệu từ BigQuery):
  - "Report Builder": pivot AdMob linh hoạt kiểu AdMob console (tự chọn
    dimension: quốc gia/ad unit/định dạng + mốc thời gian), giới hạn trong 2
    metric + 3 dimension mà view BigQuery có. Đã bỏ trang "Tổng quan" cũ
    (Meta/TikTok/Google Ads theo channel) theo yêu cầu user — phần channel
    Meta/CPM/CTR/CVR giờ nằm ở trang "Meta + Adjust" thay vì trang riêng.
  - "Market Board": eCPM từng quốc gia so với benchmark tự nhập cho từng app
    (màu 🟢/🔴) + sparkline xu hướng — xem `benchmarks.py`.
  Dùng 1 service account key CHUNG cho cả team (đọc từ Secrets khi deploy, hoặc
  GOOGLE_APPLICATION_CREDENTIALS trong .env khi chạy local) — xem
  AGENT-BRIEF.md (không commit git) và GHI_CHU_TIEN_DO.md.

Mọi trang đều KHÔNG tự gọi API khi vừa mở — chọn bộ lọc rồi bấm Apply mới gọi.
Theme màu ở `.streamlit/config.toml` (không chứa gì bí mật, được commit git).
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import adjust_client as ac
import bq_client as bq
import benchmarks as bm
import country_meta as cmeta
import meta_adjust_merge as mam
import campaign_alerts as calerts
import campaign_doctor as cdoc
import campaign_snapshots as csnap
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
def load_adjust_data(days_back: int, app_tokens_raw: str, api_token: str, include_today: bool = False):
    # QUAN TRỌNG: api_token + app_tokens_raw PHẢI là tham số của hàm (không đọc
    # secret/session ngầm bên trong) — Streamlit chỉ cache dựa theo tham số truyền
    # vào. Nếu đọc ngầm bên trong hàm, đổi giá trị sẽ KHÔNG làm cache cũ mất hiệu
    # lực (đã gặp lỗi thật: thêm app thứ 2 vẫn chỉ thấy app cũ).
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / App Token.", None

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_detail(
            api_token, app_tokens, days_back=days_back, exit_on_error=False, include_today=include_today
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
    """Dùng cho trang Chẩn đoán — cắt lát theo creative. Gọi RIÊNG (không chung
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
# BigQuery — hàm dùng chung
# ══════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def get_bq_client():
    """1 key dùng CHUNG cho cả team (không phải cá nhân như Adjust) — đọc từ
    Secrets khi deploy (mục [gcp_service_account]), hoặc từ file local qua
    GOOGLE_APPLICATION_CREDENTIALS khi chạy `streamlit run app.py` ở máy.
    """
    try:
        if "gcp_service_account" in st.secrets:
            return bq.get_client_from_info(dict(st.secrets["gcp_service_account"])), None
    except Exception:
        pass
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        return bq.get_client_from_file(path), None
    return None, "Thiếu cấu hình BigQuery (Secrets [gcp_service_account] hoặc GOOGLE_APPLICATION_CREDENTIALS)."


@st.cache_data(ttl=60 * 60, show_spinner=False)
def get_known_product_ids():
    """Danh sách app THẬT lấy trực tiếp từ BigQuery (bq.refresh_product_ids())
    — KHÔNG dùng list gõ cứng bq.KNOWN_PRODUCT_IDS nữa (đã gặp đúng vấn đề
    user chỉ ra 18/09/2026: list cứng không tự cập nhật khi team Data thêm app
    mới). Cache 1 tiếng — đủ mới, không query lại mỗi lần rerun trang (tốn
    quota dù rất nhỏ). Rớt về list cứng nếu query lỗi (VD thiếu credentials),
    để app còn dùng được thay vì crash."""
    client, cerr = get_bq_client()
    if cerr:
        return bq.KNOWN_PRODUCT_IDS, cerr
    try:
        ids = bq.refresh_product_ids(client)
        return (ids or bq.KNOWN_PRODUCT_IDS), None
    except Exception as e:  # noqa: BLE001
        return bq.KNOWN_PRODUCT_IDS, f"Không lấy được danh sách app mới nhất từ BigQuery: {e}"


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
                st.divider()
                st.subheader("Theo dõi trong ngày (sáng vs hiện tại)")
                st.caption(
                    "Tự động lưu lại CPI/ROAS D0/ARPU D0 mỗi lần bạn xem \"Hôm nay\" (cách "
                    f"nhau tối thiểu {csnap.MIN_INTERVAL_HOURS} tiếng) — để so sánh sau này "
                    "không cần nhớ số buổi sáng. ⚠️ Có thể mất nếu app ngủ/redeploy giữa các lần xem."
                )

                snapshot_rows = 0
                for app_name, g_app in filtered.groupby("app"):
                    campaign_stats = {}
                    for campaign_name, g in g_app.groupby("campaign"):
                        k = weighted_kpis(g)
                        campaign_stats[campaign_name] = {
                            "installs": k["installs"],
                            "cpi": k["cpi"],
                            "roas_d0": k.get("roas_ad_d0"),
                            "arpu_d0": k.get("arpu_d0"),
                        }
                    snapshot_rows += csnap.maybe_capture_snapshots(app_name, campaign_stats)
                if snapshot_rows:
                    st.caption(f"📸 Vừa chụp thêm {snapshot_rows} campaign mới.")

                compare_rows = []
                for app_name, g_app in filtered.groupby("app"):
                    for campaign_name in g_app["campaign"].unique():
                        cmp = csnap.compare_today(app_name, campaign_name)
                        if cmp:
                            compare_rows.append({
                                "Campaign": campaign_name,
                                "Lần đầu hôm nay": cmp["first_ts"][11:16],
                                "Lần gần nhất": cmp["last_ts"][11:16],
                                "CPI đầu": cmp["first"].get("cpi"),
                                "CPI hiện tại": cmp["last"].get("cpi"),
                                "CPI % đổi": cmp["cpi_pct_change"],
                                "ROAS D0 đầu": cmp["first"].get("roas_d0"),
                                "ROAS D0 hiện tại": cmp["last"].get("roas_d0"),
                                "ROAS D0 % đổi": cmp["roas_d0_pct_change"],
                                "ARPU D0 đầu": cmp["first"].get("arpu_d0"),
                                "ARPU D0 hiện tại": cmp["last"].get("arpu_d0"),
                            })

                if not compare_rows:
                    st.info(
                        "Chưa đủ 2 lần chụp trong hôm nay để so sánh — quay lại xem sau "
                        f"(cách lần trước ≥{csnap.MIN_INTERVAL_HOURS} tiếng) để thấy bảng so sánh."
                    )
                else:
                    compare_df = pd.DataFrame(compare_rows).sort_values("ROAS D0 % đổi").reset_index(drop=True)
                    st.dataframe(
                        compare_df, width="stretch", hide_index=True,
                        column_config={
                            "CPI đầu": st.column_config.NumberColumn(format="$%.4f"),
                            "CPI hiện tại": st.column_config.NumberColumn(format="$%.4f"),
                            "CPI % đổi": st.column_config.NumberColumn(format="%.1f%%"),
                            "ROAS D0 đầu": st.column_config.NumberColumn(format="percent"),
                            "ROAS D0 hiện tại": st.column_config.NumberColumn(format="percent"),
                            "ROAS D0 % đổi": st.column_config.NumberColumn(format="%.1f%%"),
                            "ARPU D0 đầu": st.column_config.NumberColumn(format="$%.4f"),
                            "ARPU D0 hiện tại": st.column_config.NumberColumn(format="$%.4f"),
                        },
                    )
                    st.caption("ROAS D0 tụt nhiều nhất (so với lần chụp đầu hôm nay) lên đầu.")

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
# TRANG — Report Builder (tự chọn dimension AdMob, kiểu AdMob console)
# ══════════════════════════════════════════════════════════════════════
def page_report_builder():
    st.title("Report Builder")
    st.caption("🔑 Key dùng chung team. Chỉ có Impressions + eCPM theo Quốc gia/Ad unit/Định dạng.")

    known_product_ids, product_ids_err = get_known_product_ids()
    if product_ids_err:
        st.caption(f"⚠️ {product_ids_err} — đang dùng danh sách app cũ đã lưu sẵn.")

    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        flex_product_id = st.selectbox("App (product_id)", known_product_ids, key="bq_flex_product")
    with fcol2:
        FLEX_DATE_PRESETS = {"Hôm qua": 1, "7 ngày qua": 7, "14 ngày qua": 14, "30 ngày qua": 30}
        flex_date_choice = st.selectbox(
            "Khoảng ngày", list(FLEX_DATE_PRESETS.keys()), index=1, key="bq_flex_date"
        )
        flex_days_back = FLEX_DATE_PRESETS[flex_date_choice]
    with fcol3:
        st.write("")
        st.write("")

    st.markdown("**Dimensions** (bấm chọn, chọn được nhiều)")
    DIMENSION_LABELS = {"country": "Quốc gia", "ad_unit": "Ad unit", "ad_format": "Định dạng"}
    flex_dims_labels = st.pills(
        "Dimensions", list(DIMENSION_LABELS.values()), selection_mode="multi",
        key="bq_flex_dims", label_visibility="collapsed",
    )
    flex_dims = [k for k, v in DIMENSION_LABELS.items() if v in (flex_dims_labels or [])]

    st.markdown("**Mốc thời gian** (chọn 1)")
    TIME_LABELS = {"Theo ngày": "day", "Theo tuần": "week", "Theo tháng": "month", "Gộp cả khoảng": None}
    flex_time_label = st.pills(
        "Mốc thời gian", list(TIME_LABELS.keys()), selection_mode="single",
        default="Theo ngày", key="bq_flex_time", label_visibility="collapsed",
    )
    flex_time = TIME_LABELS.get(flex_time_label, "day")

    flex_fetch_clicked = st.button("Apply", type="primary", key="bq_flex_fetch")

    if "bq_flex_df" not in st.session_state:
        st.session_state.bq_flex_df = None
        st.session_state.bq_flex_err = None

    if flex_fetch_clicked:
        client, cerr = get_bq_client()
        if cerr:
            st.session_state.bq_flex_df, st.session_state.bq_flex_err = None, cerr
        else:
            start, end = bq.get_date_range(flex_days_back)
            try:
                st.session_state.bq_flex_df = bq.fetch_admob_flexible(
                    client, flex_product_id, start, end, flex_dims, flex_time
                )
                st.session_state.bq_flex_err = None
            except Exception as e:  # noqa: BLE001
                st.session_state.bq_flex_df, st.session_state.bq_flex_err = None, f"Lỗi query: {e}"

    if st.session_state.bq_flex_err:
        st.error(f"❌ {st.session_state.bq_flex_err}")
    elif st.session_state.bq_flex_df is None:
        st.info("👆 Chọn dimension + mốc thời gian rồi bấm **Apply** để bắt đầu.")
    elif st.session_state.bq_flex_df.empty:
        st.warning("Không có dữ liệu cho tổ hợp này.")
    else:
        st.dataframe(st.session_state.bq_flex_df, width="stretch", hide_index=True)


# ══════════════════════════════════════════════════════════════════════
# TRANG — Market Board (eCPM vs benchmark theo quốc gia)
# ══════════════════════════════════════════════════════════════════════
def page_market_board():
    st.title("Market Board")
    st.caption("eCPM từng quốc gia so với benchmark riêng của nước đó · 🟢 đạt · 🔴 dưới benchmark.")
    st.warning("⚠️ Benchmark có thể mất khi app khởi động lại — chưa lưu bền vững.")

    known_product_ids, product_ids_err = get_known_product_ids()
    if product_ids_err:
        st.caption(f"⚠️ {product_ids_err} — đang dùng danh sách app cũ đã lưu sẵn.")

    mcol1, mcol2, mcol3 = st.columns(3)
    with mcol1:
        mkt_product_id = st.selectbox("App (product_id)", known_product_ids, key="mkt_product")
    with mcol2:
        # Mặc định 30 ngày — đúng khoảng dùng để tính "top theo doanh thu" mặc
        # định (xem bên dưới), nếu đổi sang 14/60 ngày thì top-N cũng tính lại
        # theo đúng khoảng đang chọn (không cố định cứng ở 30 ngày).
        MKT_DATE_PRESETS = {"14 ngày qua": 14, "30 ngày qua": 30, "60 ngày qua": 60}
        mkt_date_choice = st.selectbox(
            "Khoảng ngày", list(MKT_DATE_PRESETS.keys()), index=1, key="mkt_date"
        )
        mkt_days_back = MKT_DATE_PRESETS[mkt_date_choice]
    with mcol3:
        mkt_top_n = st.number_input(
            "Số thị trường mặc định (nếu không tự chọn quốc gia)",
            min_value=5, max_value=100, value=20, step=5, key="mkt_top_n",
            help="Chỉ áp dụng khi KHÔNG chọn quốc gia cụ thể ở dưới — mặc định "
            "lấy top N theo DOANH THU cao nhất trong khoảng ngày đã chọn.",
        )

    mkt_fetch_clicked = st.button("Apply", type="primary", key="mkt_fetch")

    if "mkt_raw" not in st.session_state:
        st.session_state.mkt_raw = None
        st.session_state.mkt_err = None
        st.session_state.mkt_product_shown = None

    if mkt_fetch_clicked:
        client, cerr = get_bq_client()
        if cerr:
            st.session_state.mkt_raw, st.session_state.mkt_err = None, cerr
        else:
            start, end = bq.get_date_range(mkt_days_back)
            try:
                st.session_state.mkt_raw = bq.fetch_admob_flexible(
                    client, mkt_product_id, start, end, ["country"], "day"
                )
                st.session_state.mkt_err = None
            except Exception as e:  # noqa: BLE001
                st.session_state.mkt_raw, st.session_state.mkt_err = None, f"Lỗi query: {e}"
        st.session_state.mkt_product_shown = mkt_product_id

    if st.session_state.mkt_err:
        st.error(f"❌ {st.session_state.mkt_err}")
    elif st.session_state.mkt_raw is None:
        st.info("👆 Chọn app + khoảng ngày rồi bấm **Apply** để bắt đầu.")
    elif st.session_state.mkt_raw.empty:
        st.warning("Không có dữ liệu cho app/khoảng ngày này.")
    else:
        raw = st.session_state.mkt_raw
        shown_product_id = st.session_state.mkt_product_shown

        # Tính eCPM hiện tại (TB 7 ngày gần nhất, weighted impressions) + doanh
        # thu suy ra (revenue_implied, cả khoảng ngày) + xu hướng cho từng quốc
        # gia — CHƯA áp benchmark (benchmark giờ theo từng quốc gia, người dùng
        # chỉnh ở bảng ngay dưới đây). Tính 1 LẦN cho TẤT CẢ quốc gia — lọc
        # Vùng/Tier/chọn tay bên dưới chạy ngay trên kết quả này, KHÔNG cần bấm
        # Apply lại (không tốn thêm query BigQuery).
        country_rows = []
        for country, g in raw.groupby("country"):
            g = g.sort_values("day")
            total_impr = g["impressions"].sum()
            if not total_impr:
                continue
            last7 = g.tail(7)
            last7_impr = last7["impressions"].sum()
            current_ecpm = (
                (last7["ecpm_blended"].fillna(0) * last7["impressions"]).sum() / last7_impr
                if last7_impr else None
            )
            country_rows.append({
                "country": country,
                "impressions": int(total_impr),
                "revenue_implied": g["revenue_implied"].fillna(0).sum(),
                "current_ecpm": current_ecpm,
                "trend": g["ecpm_blended"].fillna(0).tolist(),
            })

        if not country_rows:
            st.warning("Không có quốc gia nào có dữ liệu trong khoảng ngày này.")
            return

        st.markdown("**Lọc/chọn quốc gia** (để trống ô chọn quốc gia = dùng mặc định top theo doanh thu)")
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            mkt_regions = st.multiselect("Vùng", cmeta.ALL_REGIONS, key="mkt_regions")
        with fcol2:
            mkt_tiers = st.multiselect("Tier", cmeta.ALL_TIERS, key="mkt_tiers")

        filtered_rows = country_rows
        if mkt_regions:
            filtered_rows = [r for r in filtered_rows if cmeta.get_region(r["country"]) in mkt_regions]
        if mkt_tiers:
            filtered_rows = [r for r in filtered_rows if cmeta.get_tier(r["country"]) in mkt_tiers]

        with fcol3:
            # Danh sách sắp theo IMPRESSIONS giảm dần — proxy cho "lượng
            # user" (nguồn AdMob này không có số user thực, impressions là
            # số gần nhất đang có sẵn) — để chọn lẻ từng nước dễ hơn thay vì
            # danh sách xếp theo bảng chữ cái.
            candidates_sorted = sorted(filtered_rows, key=lambda r: r["impressions"], reverse=True)
            mkt_countries_picked = st.multiselect(
                "Quốc gia cụ thể (sắp theo lượng impressions — proxy lượng "
                "user — nhiều nhất lên đầu)",
                [r["country"] for r in candidates_sorted],
                key="mkt_countries",
            )

        if not filtered_rows:
            st.warning("Không có quốc gia nào trong bộ lọc Vùng/Tier này.")
            return
        elif mkt_countries_picked:
            # Đã tự chọn quốc gia cụ thể → hiện ĐÚNG các nước đó theo ĐÚNG
            # thứ tự đã chọn (không giới hạn top N).
            by_country = {r["country"]: r for r in filtered_rows}
            top_countries = [by_country[c] for c in mkt_countries_picked if c in by_country]
        else:
            # Mặc định: top N theo DOANH THU cao nhất (không phải impressions).
            top_countries = sorted(
                filtered_rows, key=lambda r: r["revenue_implied"], reverse=True
            )[: int(mkt_top_n)]

        if not top_countries:
            return

        saved = bm.get_product_benchmarks(shown_product_id)
        # Key đổi theo ĐÚNG tập quốc gia đang hiện — đổi vùng/tier/chọn tay
        # sẽ tự build lại bảng benchmark đúng danh sách mới, không giữ bảng cũ.
        countries_signature = ",".join(sorted(r["country"] for r in top_countries))
        editor_key = f"mkt_bench_editor_{shown_product_id}_{hash(countries_signature)}"
        if editor_key not in st.session_state:
            bench_rows = [
                {
                    "Quốc gia": r["country"],
                    "Impressions": r["impressions"],
                    "eCPM hiện tại": round(r["current_ecpm"], 4) if r["current_ecpm"] is not None else None,
                    # Chưa lưu benchmark cho nước này lần nào → mặc định = eCPM
                    # hiện tại (ra 0% lệch ban đầu), tự sửa lại theo mức muốn.
                    "Benchmark ($)": round(saved.get(r["country"], r["current_ecpm"] or 0.0), 4),
                }
                for r in top_countries
            ]
            st.session_state[editor_key] = pd.DataFrame(bench_rows)

        st.markdown("**Benchmark từng quốc gia** (mặc định = eCPM hiện tại, sửa rồi bấm Lưu)")
        edited = st.data_editor(
            st.session_state[editor_key],
            key=f"{editor_key}_widget",
            hide_index=True,
            width="stretch",
            disabled=["Quốc gia", "Impressions", "eCPM hiện tại"],
            column_config={
                "eCPM hiện tại": st.column_config.NumberColumn(format="$%.4f"),
                "Benchmark ($)": st.column_config.NumberColumn(format="$%.4f", min_value=0.0, step=0.01),
            },
        )
        st.session_state[editor_key] = edited

        if st.button("💾 Lưu benchmark cho từng quốc gia", key="mkt_save_benchmark"):
            new_map = dict(zip(edited["Quốc gia"], edited["Benchmark ($)"]))
            bm.save_product_benchmarks(shown_product_id, new_map)
            st.success(f"Đã lưu benchmark cho {len(new_map)} quốc gia của {shown_product_id}.")

        # Dùng benchmark ĐANG HIỆN trên bảng sửa (kể cả chưa bấm Lưu) để tính
        # bảng điểm bên dưới — cho xem thử trước khi quyết định lưu lại.
        benchmark_lookup = dict(zip(edited["Quốc gia"], edited["Benchmark ($)"]))

        scorecard_rows = []
        for r in top_countries:
            country = r["country"]
            current_ecpm = r["current_ecpm"]
            benchmark_val = benchmark_lookup.get(country)
            pct_vs_bench = (
                (current_ecpm - benchmark_val) / benchmark_val * 100
                if current_ecpm is not None and benchmark_val else None
            )
            scorecard_rows.append({
                "Quốc gia": country,
                "Vùng": cmeta.get_region(country),
                "Tier": cmeta.get_tier(country),
                "Impressions": r["impressions"],
                "eCPM (7 ngày)": round(current_ecpm, 4) if current_ecpm is not None else None,
                "Benchmark": round(benchmark_val, 4) if benchmark_val is not None else None,
                "% so với benchmark": round(pct_vs_bench, 1) if pct_vs_bench is not None else None,
                "Trạng thái": (
                    ("🟢" if current_ecpm >= benchmark_val else "🔴")
                    if current_ecpm is not None and benchmark_val is not None else "⚪"
                ),
                "Xu hướng eCPM": r["trend"],
            })

        summary_df = (
            pd.DataFrame(scorecard_rows)
            .sort_values("% so với benchmark")  # thị trường tệ nhất (so với benchmark của chính nó) lên đầu
            .reset_index(drop=True)
        )

        st.divider()
        st.subheader("Market Board")
        _selection_desc = (
            f"{len(top_countries)} quốc gia tự chọn"
            if mkt_countries_picked
            else f"top {len(summary_df)} theo doanh thu"
        )
        st.caption(f"{shown_product_id} · {_selection_desc} · thấp hơn benchmark nhiều nhất lên đầu.")
        st.dataframe(
            summary_df,
            width="stretch",
            hide_index=True,
            column_config={
                "eCPM (7 ngày)": st.column_config.NumberColumn(format="$%.4f"),
                "Benchmark": st.column_config.NumberColumn(format="$%.4f"),
                "% so với benchmark": st.column_config.NumberColumn(format="%.1f%%"),
                "Xu hướng eCPM": st.column_config.LineChartColumn(
                    "Xu hướng eCPM", help="eCPM blended theo từng ngày trong khoảng đã chọn"
                ),
            },
        )
        st.caption("eCPM (7 ngày) = blended theo impressions, không phải trung bình đơn giản.")


# ══════════════════════════════════════════════════════════════════════
# TRANG — Meta + Adjust (kênh Facebook: CPM/CTR/CVR, ghép Adjust theo
# campaign/day/country — xem meta_adjust_merge.py để biết cách ghép)
# ══════════════════════════════════════════════════════════════════════
def page_meta_adjust():
    st.title("Meta + Adjust")
    st.caption(
        "BigQuery cho biết phễu quảng cáo Meta (CPM/CTR/CVR) · Adjust cho biết "
        "kết quả cuối (CPI/ARPU/ROAS/Retention) · Ghép theo campaign + ngày + quốc gia."
    )

    known_product_ids, product_ids_err = get_known_product_ids()
    if product_ids_err:
        st.caption(f"⚠️ {product_ids_err} — đang dùng danh sách app cũ đã lưu sẵn.")

    fcol1, fcol2 = st.columns(2)
    with fcol1:
        ma_product_id = st.selectbox("App (product_id)", known_product_ids, key="ma_product")
    with fcol2:
        MA_DATE_PRESETS = {"7 ngày qua": 7, "14 ngày qua": 14, "30 ngày qua": 30}
        ma_date_choice = st.selectbox("Khoảng ngày", list(MA_DATE_PRESETS.keys()), index=1, key="ma_date")
        ma_days_back = MA_DATE_PRESETS[ma_date_choice]

    ma_api_token = st.session_state.get("adjust_api_token", "")
    ma_app_tokens_raw = st.session_state.get("adjust_app_tokens", "")
    st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")
    ma_fetch_clicked = st.button("Apply", type="primary", key="ma_fetch")

    if "ma_bq_df" not in st.session_state:
        st.session_state.ma_bq_df = None
        st.session_state.ma_channel_df = None
        st.session_state.ma_trend_df = None
        st.session_state.ma_merged = None
        st.session_state.ma_err = None
        st.session_state.ma_warning = None

    if ma_fetch_clicked:
        client, cerr = get_bq_client()
        if cerr:
            st.session_state.ma_err = cerr
        else:
            start, end = bq.get_date_range(ma_days_back)
            try:
                st.session_state.ma_bq_df = bq.fetch_campaign_detail(
                    client, ma_product_id, start, end, channel="Facebook"
                )
                st.session_state.ma_channel_df = bq.fetch_campaign_by_channel(client, ma_product_id, start, end)
                st.session_state.ma_trend_df = bq.fetch_campaign_trend(client, ma_product_id, start, end)
            except Exception as e:  # noqa: BLE001
                st.session_state.ma_err = f"Lỗi query BigQuery: {e}"
                st.session_state.ma_bq_df = None

            adjust_df, adjust_err, adjust_warning = load_adjust_data(
                ma_days_back, ma_app_tokens_raw, ma_api_token, include_today=False
            )
            st.session_state.ma_warning = adjust_warning
            if adjust_err:
                st.session_state.ma_err = (st.session_state.ma_err + " | " if st.session_state.ma_err else "") + adjust_err
                st.session_state.ma_merged = None
            elif st.session_state.ma_bq_df is not None:
                adjust_prepared = mam.prepare_adjust_for_merge(
                    adjust_df if adjust_df is not None else pd.DataFrame(), ma_product_id
                )
                st.session_state.ma_merged = mam.merge_meta_adjust(st.session_state.ma_bq_df, adjust_prepared)

    if st.session_state.ma_err:
        st.error(f"❌ {st.session_state.ma_err}")
    if st.session_state.ma_warning:
        st.warning(f"⚠️ Adjust cảnh báo: {st.session_state.ma_warning}")

    if st.session_state.ma_channel_df is None:
        st.info("👆 Chọn app + khoảng ngày, nhập token Adjust rồi bấm **Apply** để bắt đầu.")
        return

    st.subheader("Tổng quan theo kênh (BigQuery)")
    channel_df = st.session_state.ma_channel_df
    if channel_df.empty:
        st.warning("Không có dữ liệu kênh nào trong khoảng ngày này.")
    else:
        st.dataframe(
            channel_df, width="stretch", hide_index=True,
            column_config={
                "cpm": st.column_config.NumberColumn("CPM", format="$%.2f"),
                "ctr_pct": st.column_config.NumberColumn("CTR %", format="%.2f%%"),
                "cvr_pct": st.column_config.NumberColumn("CVR %", format="%.2f%%"),
                "cpi": st.column_config.NumberColumn("CPI", format="$%.4f"),
            },
        )
        trend_df = st.session_state.ma_trend_df
        if trend_df is not None and not trend_df.empty:
            st.caption("Xu hướng spend/installs theo ngày (gộp mọi kênh).")
            trend_indexed = trend_df.set_index("day")
            # spend VÀ installs đều là cột NUMERIC từ BigQuery → pandas đọc thành
            # Decimal (dtype "object"), Altair/Vega-Lite (dùng trong st.line_chart)
            # vẽ SAI HẲN trục khi gặp cột kiểu Decimal (đã gặp lỗi thật: trục Y ra
            # toàn số vô nghĩa như "6758000000000") — ép cả 2 về float trước khi vẽ.
            trend_indexed["spend"] = pd.to_numeric(trend_indexed["spend"], errors="coerce")
            trend_indexed["installs"] = pd.to_numeric(trend_indexed["installs"], errors="coerce")
            if len(trend_indexed) < 2:
                st.dataframe(trend_indexed, width="stretch")
            else:
                # Tách riêng installs và spend — 2 cái lệch quá xa về độ lớn (installs
                # hàng chục nghìn, spend vài nghìn đô), chung 1 biểu đồ sẽ bẹp 1 đường
                # (giống lỗi đã sửa ở trang Adjust).
                tcol1, tcol2 = st.columns(2)
                with tcol1:
                    st.caption("Installs")
                    st.line_chart(trend_indexed[["installs"]])
                with tcol2:
                    st.caption("Spend ($)")
                    st.line_chart(trend_indexed[["spend"]])

    st.divider()
    st.subheader("Ghép Meta (Facebook) + Adjust theo campaign/ngày/quốc gia")

    merged = st.session_state.ma_merged
    if merged is None or merged.empty:
        st.warning("Chưa có dữ liệu ghép — kiểm tra token Adjust hoặc khoảng ngày đã chọn.")
        return

    status_counts = merged["Trạng thái ghép"].value_counts()
    scol1, scol2, scol3 = st.columns(3)
    scol1.metric("Khớp cả 2 nguồn", int(status_counts.get("Khớp cả 2 nguồn", 0)))
    scol2.metric("Chỉ có ở BigQuery (Meta)", int(status_counts.get("Chỉ có ở BigQuery (Meta)", 0)))
    scol3.metric("Chỉ có ở Adjust", int(status_counts.get("Chỉ có ở Adjust", 0)))
    st.caption(
        "\"Chỉ có ở BigQuery\" thường là campaign quá mới/ít traffic Adjust chưa "
        "kịp ghi nhận trong khoảng ngày này. \"Chỉ có ở Adjust\" có thể là campaign "
        "đã dừng bên Meta nhưng vẫn còn install trả về (attribution trễ)."
    )

    # PL2 TỔNG — cộng dồn TOÀN BỘ spend (BigQuery) và TOÀN BỘ ad_revenue (Adjust)
    # ĐỘC LẬP với nhau (fillna 0), KHÔNG chỉ tính trên phần "Khớp cả 2 nguồn".
    # Vì spend/ad_revenue là số CỘNG DỒN được (không phải tỉ lệ), tổng đúng theo
    # cách này dù match rate < 100% — khác với PL2 ở TỪNG DÒNG bên dưới (cột đó
    # chỉ ra số ở đúng dòng khớp cả 2 nguồn, để soi campaign/ngày/quốc gia cụ thể).
    # spend là cột NUMERIC từ BigQuery → pandas đọc thành Decimal, phải ép về
    # float trước khi trừ với ad_revenue (float, từ Adjust) — tránh TypeError
    # Decimal - float (đã gặp lỗi thật khi test).
    total_spend = pd.to_numeric(merged["spend"], errors="coerce").fillna(0).sum()
    total_ad_revenue = pd.to_numeric(merged["ad_revenue"], errors="coerce").fillna(0).sum()
    total_pl2 = total_ad_revenue - total_spend
    pcol1, pcol2, pcol3 = st.columns(3)
    pcol1.metric("Tổng chi phí (BigQuery)", f"${total_spend:,.2f}")
    pcol2.metric("Tổng doanh thu ads (Adjust)", f"${total_ad_revenue:,.2f}")
    pcol3.metric("Lãi marketing tổng (PL2)", f"${total_pl2:,.2f}")
    st.caption(
        "PL2 tổng = TOÀN BỘ doanh thu ads − TOÀN BỘ chi phí trong khoảng ngày đã "
        "chọn (không phụ thuộc tỉ lệ khớp ghép ở trên) · chưa gồm doanh thu IAP "
        "(đã loại vì tracking sai trước đó, xem GHI_CHU_TIEN_DO.md)."
    )

    fstatus_col, fsearch_col = st.columns([1, 2])
    with fstatus_col:
        status_filter = st.multiselect(
            "Trạng thái ghép", merged["Trạng thái ghép"].unique().tolist(), key="ma_status_filter"
        )
    with fsearch_col:
        ma_campaign_search = st.text_input("Tìm campaign_id hoặc tên campaign", key="ma_campaign_search")

    view = merged
    if status_filter:
        view = view[view["Trạng thái ghép"].isin(status_filter)]
    if ma_campaign_search:
        mask = view["campaign_id"].astype(str).str.contains(ma_campaign_search, case=False, na=False)
        if "campaign_name" in view.columns:
            mask = mask | view["campaign_name"].astype(str).str.contains(ma_campaign_search, case=False, na=False)
        view = view[mask]

    display_cols = [
        c for c in [
            "day", "country", "campaign_id", "campaign_name",
            "spend", "impressions", "clicks", "cpm", "ctr_pct", "cvr_pct",
            "installs", "installs_adjust", "cpi", "cpi_adjust",
            "arpu_d0", "roas_ad_d0", "roas_ad_d7", "roas_ad_d30",
            "retention_rate_d1", "retention_rate_d7", "ad_revenue",
            "Lãi marketing (PL2)", "Trạng thái ghép",
        ] if c in view.columns
    ]
    st.dataframe(
        view[display_cols], width="stretch", hide_index=True,
        column_config={
            "cpm": st.column_config.NumberColumn("CPM (Meta)", format="$%.2f"),
            "ctr_pct": st.column_config.NumberColumn("CTR % (Meta)", format="%.2f%%"),
            "cvr_pct": st.column_config.NumberColumn("CVR % (Meta)", format="%.2f%%"),
            "installs": st.column_config.NumberColumn("Installs (Meta/BQ)"),
            "installs_adjust": st.column_config.NumberColumn("Installs (Adjust)"),
            "cpi": st.column_config.NumberColumn("CPI (Meta/BQ)", format="$%.4f"),
            "cpi_adjust": st.column_config.NumberColumn("CPI (Adjust)", format="$%.4f"),
            "arpu_d0": st.column_config.NumberColumn("ARPU D0", format="$%.4f"),
            "roas_ad_d0": st.column_config.NumberColumn("ROAS D0", format="percent"),
            "roas_ad_d7": st.column_config.NumberColumn("ROAS D7", format="percent"),
            "roas_ad_d30": st.column_config.NumberColumn("ROAS D30", format="percent"),
            "retention_rate_d1": st.column_config.NumberColumn("Retention D1", format="percent"),
            "retention_rate_d7": st.column_config.NumberColumn("Retention D7", format="percent"),
            "ad_revenue": st.column_config.NumberColumn("Ad Revenue (Adjust)", format="$%.2f"),
            "Lãi marketing (PL2)": st.column_config.NumberColumn("Lãi marketing (PL2)", format="$%.2f"),
        },
    )
    st.caption(
        "Cột \"Lãi marketing (PL2)\" ở TỪNG DÒNG chỉ tính được khi \"Trạng thái "
        "ghép\" = Khớp cả 2 nguồn (để trống nếu thiếu 1 trong 2 vế) — muốn xem "
        "PL2 CỘNG DỒN đúng (không phụ thuộc match rate), xem 3 ô KPI phía trên."
    )
    st.caption(
        "Installs/CPI \"(Meta/BQ)\" là số Meta tự báo cáo (network-reported). "
        "Installs/CPI \"(Adjust)\" là số MMP đo được (thường chính xác hơn cho "
        "attribution) — 2 số có thể lệch nhau, đây là bình thường."
    )


# ══════════════════════════════════════════════════════════════════════
# TRANG — Cảnh báo (đột biến / giảm dần CPI + ROAS D0 theo từng campaign)
# ══════════════════════════════════════════════════════════════════════
def page_alerts():
    st.title("Cảnh báo")
    st.caption(
        "Phát hiện CPI tăng bất thường / ROAS D0 tụt bất thường theo TỪNG CAMPAIGN — "
        "dùng riêng dữ liệu Adjust, áp dụng cho MỌI channel (không chỉ Meta)."
    )

    known_product_ids, product_ids_err = get_known_product_ids()
    if product_ids_err:
        st.caption(f"⚠️ {product_ids_err} — đang dùng danh sách app cũ đã lưu sẵn.")

    col1, col2 = st.columns(2)
    with col1:
        al_product_id = st.selectbox("App (product_id)", known_product_ids, key="al_product")
    with col2:
        AL_DATE_PRESETS = {"30 ngày qua": 30, "60 ngày qua": 60}
        al_date_choice = st.selectbox(
            "Khoảng ngày kéo (cần đủ dài để có mốc so sánh)",
            list(AL_DATE_PRESETS.keys()), key="al_date",
        )
        al_days_back = AL_DATE_PRESETS[al_date_choice]

    al_api_token = st.session_state.get("adjust_api_token", "")
    al_app_tokens_raw = st.session_state.get("adjust_app_tokens", "")
    st.caption("🔒 Cần token Adjust cá nhân — nhập ở sidebar bên trái.")
    al_fetch_clicked = st.button("Apply", type="primary", key="al_fetch")

    st.markdown("**Ngưỡng cảnh báo** (chỉnh ngay không cần bấm Apply lại — không tốn thêm API)")
    tcol1, tcol2, tcol3, tcol4 = st.columns(4)
    with tcol1:
        al_min_installs = st.number_input(
            "Installs tối thiểu để xét (lọc campaign quá nhỏ)",
            min_value=0, value=30, step=10, key="al_min_installs",
        )
    with tcol2:
        al_spike_pct = st.number_input(
            "Ngưỡng \"đột biến\" (% lệch vs TB 7 ngày trước)",
            min_value=5, value=30, step=5, key="al_spike_pct",
        )
    with tcol3:
        al_decline_pct = st.number_input(
            "Ngưỡng \"giảm dần\" (% đổi giữa 2 tuần liền kề)",
            min_value=5, value=20, step=5, key="al_decline_pct",
        )
    with tcol4:
        al_realtime_pct = st.number_input(
            "Ngưỡng cảnh báo TRONG NGÀY (% so với lần chụp đầu hôm nay)",
            min_value=5, value=20, step=5, key="al_realtime_pct",
        )

    if "al_daily_df" not in st.session_state:
        st.session_state.al_daily_df = None
        st.session_state.al_raw_df = None
        st.session_state.al_product_used = None
        st.session_state.al_days_back_used = None
        st.session_state.al_err = None
        st.session_state.al_warning = None

    if al_fetch_clicked:
        # LUÔN kéo kèm "hôm nay" (include_today=True) — không chỉ để phân tích
        # xu hướng nhiều ngày đã chốt, mà còn để CHỤP SNAPSHOT trong ngày (xem
        # campaign_snapshots.py) phục vụ mục "Cảnh báo TRONG NGÀY" bên dưới —
        # user phản ánh (16/09/2026): chọn 30 ngày không giúp biết CPI/ROAS D0
        # thay đổi NGAY TRONG NGÀY (VD sáng rẻ, chiều tăng vọt) để action kịp.
        adjust_df, adjust_err, adjust_warning = load_adjust_data(
            al_days_back, al_app_tokens_raw, al_api_token, include_today=True
        )
        st.session_state.al_warning = adjust_warning
        if adjust_err:
            st.session_state.al_err = adjust_err
            st.session_state.al_daily_df = None
        else:
            st.session_state.al_err = None
            today_str = csnap.today_str_vn()
            # Tách "hôm nay" ra khỏi phần phân tích xu hướng nhiều ngày (day-over-
            # day) — số hôm nay CHƯA CHỐT, lẫn vào sẽ làm sai lệch so sánh ngày/
            # tuần (đã chốt quy tắc này từ đầu dự án, xem adjust_client.py).
            historical_df = adjust_df[adjust_df["day"] != today_str] if adjust_df is not None and not adjust_df.empty else adjust_df
            today_df = adjust_df[adjust_df["day"] == today_str] if adjust_df is not None and not adjust_df.empty else adjust_df

            st.session_state.al_daily_df = calerts.build_campaign_daily(historical_df, al_product_id)
            # Lưu lại df thô (chưa gộp, còn đủ country/retention_rate_d1) + product_id/
            # khoảng ngày đang dùng — trang "Chẩn đoán" tái sử dụng, KHÔNG gọi lại
            # Adjust API và query BigQuery ĐÚNG CÙNG khoảng ngày này.
            st.session_state.al_raw_df = historical_df
            st.session_state.al_product_used = al_product_id
            st.session_state.al_days_back_used = al_days_back

            # Chụp snapshot TỪ DÒNG HÔM NAY — dùng field "app" THẬT của Adjust
            # làm namespace (giống trang Adjust) để "Cảnh báo trong ngày" và
            # "Theo dõi trong ngày" (trang Adjust) CHIA SẺ cùng 1 kho snapshot.
            if today_df is not None and not today_df.empty:
                for app_name, g_app in today_df.groupby("app"):
                    campaign_stats = {}
                    for campaign_name, g in g_app.groupby("campaign"):
                        k = weighted_kpis(g)
                        campaign_stats[campaign_name] = {
                            "installs": k["installs"],
                            "cpi": k["cpi"],
                            "roas_d0": k.get("roas_ad_d0"),
                            "arpu_d0": k.get("arpu_d0"),
                        }
                    csnap.maybe_capture_snapshots(app_name, campaign_stats)

    if st.session_state.al_err:
        st.error(f"❌ {st.session_state.al_err}")
    if st.session_state.al_warning:
        st.warning(f"⚠️ Adjust cảnh báo: {st.session_state.al_warning}")

    if st.session_state.al_daily_df is None:
        st.info("👆 Chọn app + khoảng ngày, nhập token Adjust rồi bấm **Apply** để bắt đầu.")
        return

    # ── Cảnh báo TRONG NGÀY (thời gian thực) — hiện TRƯỚC phần xu hướng nhiều
    # ngày, vì đây là phần cần action NGAY. Dùng snapshot đã chụp ở app này lẫn
    # ở trang Adjust (chia sẻ chung kho snapshot theo field "app" Adjust) — nên
    # nếu chưa ai chụp lần 2 hôm nay (cách nhau ≥3 tiếng) thì chưa có gì để so.
    if st.session_state.al_raw_df is not None and not st.session_state.al_raw_df.empty:
        apps_in_scope = st.session_state.al_raw_df["app"].dropna().unique().tolist()
    else:
        apps_in_scope = []
    # Adjust "app" field không nhất thiết có mặt trong historical_df nếu hôm nay
    # là ngày DUY NHẤT có data — lấy trực tiếp từ app_tokens đã lọc thay vì chỉ
    # dựa vào historical_df để không bỏ sót.
    all_flagged_today = []
    for app_name in (apps_in_scope or [a for a in csnap.load_snapshot_app_keys() if a.startswith(al_product_id)]):
        all_flagged_today.extend(csnap.list_flagged_today(app_name, threshold_pct=float(al_realtime_pct)))

    st.subheader("⚡ Cảnh báo trong ngày (thời gian thực)")
    st.caption(
        "So lần chụp ĐẦU TIÊN hôm nay (thường = sáng) với lần MỚI NHẤT (thường = "
        "bây giờ) — tự động chụp mỗi khi ai đó xem trang này hoặc trang Adjust với "
        f"\"Hôm nay\" (cách nhau ≥{csnap.MIN_INTERVAL_HOURS} tiếng). Theo dõi CẢ 3: "
        "CPI (chi phí), LTV/ARPU D0 (giá trị user), ROAS D0 (= LTV ÷ CPI) — để "
        "biết ROAS biến động là do chi phí đắt lên hay do giá trị user tụt xuống."
    )
    if not all_flagged_today:
        st.info(
            "Chưa đủ 2 lần chụp trong hôm nay để so sánh, hoặc chưa campaign nào "
            "vượt ngưỡng — quay lại xem sau (cách lần chụp trước ≥"
            f"{csnap.MIN_INTERVAL_HOURS} tiếng)."
        )
    else:
        realtime_rows = []
        for f in all_flagged_today:
            flags = []
            if f["cpi_bad"]:
                flags.append("🔴 CPI tăng")
            if f["roas_bad"]:
                flags.append("🔴 ROAS D0 giảm")
            if f["arpu_bad"]:
                flags.append("🔴 LTV (ARPU D0) giảm")
            realtime_rows.append({
                "Campaign": f["campaign"],
                "Lần đầu hôm nay": f["first_ts"][11:16],
                "Lần gần nhất": f["last_ts"][11:16],
                "CPI % đổi": f["cpi_pct_change"],
                "LTV (ARPU D0) % đổi": f["arpu_d0_pct_change"],
                "ROAS D0 % đổi": f["roas_d0_pct_change"],
                "Cảnh báo": " · ".join(flags),
            })
        st.dataframe(
            pd.DataFrame(realtime_rows), width="stretch", hide_index=True,
            column_config={
                "CPI % đổi": st.column_config.NumberColumn(format="%.1f%%"),
                "LTV (ARPU D0) % đổi": st.column_config.NumberColumn(format="%.1f%%"),
                "ROAS D0 % đổi": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

    st.divider()
    st.subheader("Cảnh báo theo xu hướng nhiều ngày (dữ liệu đã chốt)")
    st.caption(
        "Khác với mục trên — đây so sánh giữa các NGÀY ĐÃ CHỐT (không gồm hôm "
        "nay), dùng để phát hiện xu hướng kéo dài nhiều ngày, không phải biến "
        "động trong 1 ngày."
    )

    if st.session_state.al_daily_df.empty:
        st.warning("Không có dữ liệu campaign nào cho app/khoảng ngày này.")
        return

    analysis = calerts.analyze_campaigns(
        st.session_state.al_daily_df,
        min_installs=int(al_min_installs),
        spike_threshold_pct=float(al_spike_pct),
        decline_threshold_pct=float(al_decline_pct),
    )
    # Lưu lại để trang "Chẩn đoán" đọc danh sách campaign đang bị cảnh báo,
    # không phải tính lại từ đầu.
    st.session_state.al_analysis_df = analysis

    if analysis.empty:
        st.warning(
            "Không có campaign nào đủ installs tối thiểu để xét — thử giảm "
            "\"Installs tối thiểu\" hoặc kéo khoảng ngày dài hơn."
        )
        return

    n_alert = (analysis["Cảnh báo"] != "Bình thường").sum()
    kcol1, kcol2 = st.columns(2)
    kcol1.metric("Campaign đang xét", len(analysis))
    kcol2.metric("Có cảnh báo", int(n_alert))

    st.dataframe(
        analysis, width="stretch", hide_index=True,
        column_config={
            "CPI gần nhất": st.column_config.NumberColumn(format="$%.4f"),
            "CPI % lệch vs TB 7 ngày trước": st.column_config.NumberColumn(format="%.1f%%"),
            "LTV (ARPU D0) gần nhất": st.column_config.NumberColumn(format="$%.4f"),
            "LTV % lệch vs TB 7 ngày trước": st.column_config.NumberColumn(format="%.1f%%"),
            "ROAS D0 gần nhất": st.column_config.NumberColumn(format="percent"),
            "ROAS D0 % lệch vs TB 7 ngày trước": st.column_config.NumberColumn(format="%.1f%%"),
            "CPI % đổi (7 ngày vs 7 ngày trước đó)": st.column_config.NumberColumn(format="%.1f%%"),
            "LTV % đổi (7 ngày vs 7 ngày trước đó)": st.column_config.NumberColumn(format="%.1f%%"),
            "ROAS D0 % đổi (7 ngày vs 7 ngày trước đó)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "LTV = ARPU D0 (doanh thu/install tính tới D0) — tách riêng khỏi ROAS D0 "
        "để biết ROAS biến động là do CPI (chi phí) hay do LTV (giá trị user) — "
        "ROAS D0 = LTV ÷ CPI, 1 mình ROAS không tách được 2 nguyên nhân này. "
        "🔴 = xấu rõ rệt (CPI tăng vọt / LTV hoặc ROAS D0 tụt vọt) · 🟢 = tốt bất "
        "thường (nên kiểm tra lại không phải lỗi tracking) · 🟠 = xu hướng xấu "
        "kéo dài nhiều ngày (không phải giật cục 1 ngày). Cột trống = chưa đủ "
        "dữ liệu lịch sử để so sánh (cần kéo khoảng ngày dài hơn)."
    )


# ══════════════════════════════════════════════════════════════════════
# TRANG — Chẩn đoán (Campaign Doctor): tầng 1 (CPI đắt vs User kém) + tầng 2
# (nguyên nhân sâu) + gợi ý hành động + cắt lát theo quốc gia/creative
# ══════════════════════════════════════════════════════════════════════
def page_campaign_doctor():
    st.title("Chẩn đoán")
    st.caption(
        "Chẩn đoán 1 campaign đang bị cảnh báo: CPI đắt hay User kém? Vì sao? "
        "Nên làm gì? Quốc gia/creative nào đang kéo xuống?"
    )

    if st.session_state.get("al_analysis_df") is None or st.session_state.get("al_raw_df") is None:
        st.info(
            "👆 Vào trang **Cảnh báo** trước — chọn app + khoảng ngày, nhập token "
            "Adjust, bấm **Apply** — rồi quay lại đây để chọn campaign cần chẩn đoán."
        )
        return

    analysis_df = st.session_state.al_analysis_df
    product_id = st.session_state.al_product_used
    raw_df = st.session_state.al_raw_df
    days_back_used = st.session_state.al_days_back_used

    flagged = analysis_df[analysis_df["Cảnh báo"] != "Bình thường"]
    if flagged.empty:
        st.success(f"✅ App {product_id} hiện không có campaign nào bị cảnh báo — chưa cần chẩn đoán.")
        return

    campaign_options = flagged["Campaign"].tolist()
    label_map = dict(zip(flagged["Campaign"], flagged["Cảnh báo"]))
    selected_campaign = st.selectbox(
        f"Chọn campaign cần chẩn đoán (app {product_id}, {len(campaign_options)} campaign đang bị cảnh báo)",
        campaign_options,
        format_func=lambda c: f"[{label_map[c]}] {c[:70]}{'...' if len(c) > 70 else ''}",
        key="doc_selected_campaign",
    )

    st.markdown("**Benchmark \"bình thường\" cho app này** (tự nhập tay, dùng để so tầng 1)")
    st.caption(
        "Tách riêng ARPU D0 (LTV) khỏi ROAS D0 — ROAS D0 = LTV ÷ CPI, 1 mình ROAS "
        "không biết được ROAS xấu là do CPI đắt lên hay do LTV tụt xuống."
    )
    saved_bench = bm.get_doctor_benchmarks(product_id)
    bcol1, bcol2, bcol3, bcol4, bcol5 = st.columns(5)
    with bcol1:
        bench_cpi = st.number_input(
            "CPI bình thường ($)", min_value=0.0, value=float(saved_bench.get("cpi") or 0.0),
            step=0.001, format="%.4f", key="doc_bench_cpi",
        )
    with bcol2:
        bench_arpu = st.number_input(
            "LTV (ARPU D0) bình thường ($)", min_value=0.0, value=float(saved_bench.get("arpu_d0") or 0.0),
            step=0.001, format="%.4f", key="doc_bench_arpu",
        )
    with bcol3:
        bench_roas = st.number_input(
            "ROAS D0 bình thường (%, VD 15 = 15%)", min_value=0.0,
            value=float((saved_bench.get("roas_d0") or 0.0) * 100), step=1.0, key="doc_bench_roas",
        )
    with bcol4:
        bench_retention = st.number_input(
            "Retention D1 bình thường (%, VD 25 = 25%)", min_value=0.0,
            value=float((saved_bench.get("retention_d1") or 0.0) * 100), step=1.0, key="doc_bench_retention",
        )
    with bcol5:
        doc_threshold = st.number_input(
            "Ngưỡng lệch coi là có vấn đề (%)", min_value=5.0, value=20.0, step=5.0, key="doc_threshold"
        )

    if st.button("💾 Lưu benchmark cho app này", key="doc_save_bench"):
        bm.save_doctor_benchmarks(
            product_id,
            {
                "cpi": bench_cpi,
                "arpu_d0": bench_arpu,
                "roas_d0": bench_roas / 100,
                "retention_d1": bench_retention / 100,
            },
        )
        st.success(f"Đã lưu benchmark chẩn đoán cho {product_id}.")

    benchmark = {
        "cpi": bench_cpi or None,
        "arpu_d0": bench_arpu or None,
        "roas_d0": (bench_roas / 100) or None,
        "retention_d1": (bench_retention / 100) or None,
    }

    stats = cdoc.period_stats_for_campaign(raw_df, product_id, selected_campaign)
    if stats is None:
        st.warning("Không tìm thấy dữ liệu Adjust cho campaign này (có thể do đổi bộ lọc).")
        return

    tier1 = cdoc.diagnose_tier1(stats, benchmark, threshold_pct=doc_threshold)

    st.divider()
    st.subheader("Tầng 1 — CPI đắt hay User kém?")
    tcol1, tcol2, tcol3, tcol4 = st.columns(4)
    tcol1.metric(
        "CPI thực tế", fmt_money(stats["cpi"]),
        delta=f"{tier1['cpi_pct_vs_bench']:.1f}% vs benchmark" if tier1["cpi_pct_vs_bench"] is not None else None,
        delta_color="inverse",
    )
    tcol2.metric(
        "LTV (ARPU D0) thực tế", fmt_money(stats.get("arpu_d0")),
        delta=f"{tier1['arpu_pct_vs_bench']:.1f}% vs benchmark" if tier1["arpu_pct_vs_bench"] is not None else None,
    )
    tcol3.metric(
        "ROAS D0 thực tế", fmt_percent(stats["roas_d0"]),
        delta=f"{tier1['roas_pct_vs_bench']:.1f}% vs benchmark" if tier1["roas_pct_vs_bench"] is not None else None,
    )
    tcol4.metric(
        "Retention D1 thực tế", fmt_percent(stats["retention_d1"]),
        delta=f"{tier1['retention_pct_vs_bench']:.1f}% vs benchmark" if tier1["retention_pct_vs_bench"] is not None else None,
    )

    verdicts = []
    if tier1["cpi_dat"]:
        verdicts.append("🔴 **CPI đắt** — cao hơn benchmark quá ngưỡng.")
    if tier1["user_kem"]:
        kem_parts = []
        if tier1["arpu_kem"]:
            kem_parts.append("LTV (ARPU D0)")
        if tier1["retention_kem"]:
            kem_parts.append("Retention D1")
        if tier1["roas_kem"]:
            kem_parts.append("ROAS D0")
        verdicts.append(f"🔴 **User kém** — {', '.join(kem_parts)} thấp hơn benchmark quá ngưỡng.")
    if not verdicts:
        st.info(
            "Chưa phát hiện vấn đề rõ rệt so với benchmark đã nhập (hoặc benchmark "
            "đang để trống — nhập benchmark ở trên để chẩn đoán chính xác hơn)."
        )
    else:
        for v in verdicts:
            st.markdown(v)

    suggestions = []

    if tier1["cpi_dat"]:
        st.divider()
        st.subheader("Tầng 2 — Vì sao CPI đắt? (so với các campaign khác cùng app)")
        campaign_id = mam.extract_campaign_id(selected_campaign)
        if not campaign_id:
            st.warning(
                "Không trích được campaign_id từ tên campaign này (có thể không thuộc "
                "Meta/Facebook) — không mổ xẻ được CPM/CTR/CVR."
            )
        else:
            client, cerr = get_bq_client()
            if cerr:
                st.error(f"❌ {cerr}")
            else:
                start, end = bq.get_date_range(days_back_used)
                try:
                    bq_detail = bq.fetch_campaign_detail(client, product_id, start, end, channel="Facebook")
                except Exception as e:  # noqa: BLE001
                    bq_detail = None
                    st.error(f"❌ Lỗi query BigQuery: {e}")

                if bq_detail is not None and not bq_detail.empty:
                    this_campaign_bq = bq_detail[bq_detail["campaign_id"].astype(str) == str(campaign_id)]
                    peer_bq = bq_detail[bq_detail["campaign_id"].astype(str) != str(campaign_id)]
                    if this_campaign_bq.empty:
                        st.warning(
                            "Không tìm thấy dữ liệu Meta cho campaign_id này trong khoảng "
                            "ngày đã chọn — có thể campaign quá mới hoặc đã dừng từ trước."
                        )
                    else:
                        this_stats = cdoc.aggregate_bq_rows(this_campaign_bq)
                        peer_stats = cdoc.aggregate_bq_rows(peer_bq)
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

    if tier1["user_kem"]:
        st.divider()
        st.subheader("Tầng 2 — Vì sao User kém? (giữ chân hay giá trị/LTV?)")
        if tier1["retention_kem"]:
            st.markdown("- 🔴 **Retention D1 thấp** — vấn đề GIỮ CHÂN (user cài xong rồi bỏ sớm).")
            suggestions.append(cdoc.SUGGESTION_TEXT["retention_kem"])
        if tier1["arpu_kem"]:
            st.markdown("- 🔴 **LTV (ARPU D0) thấp** — vấn đề GIÁ TRỊ NGƯỜI DÙNG (ở lại nhưng không tạo đủ giá trị).")
            suggestions.append(cdoc.SUGGESTION_TEXT["arpu_kem"])
        if tier1["roas_kem"] and not tier1["retention_kem"] and not tier1["arpu_kem"]:
            st.markdown("- 🔴 **ROAS D0 thấp** — nhưng LTV và Retention riêng lẻ đều chưa rõ nguyên nhân.")
            suggestions.append(cdoc.SUGGESTION_TEXT["roas_kem"])

    if suggestions:
        st.divider()
        st.subheader("Gợi ý hành động")
        for s in suggestions:
            st.markdown(f"- {s}")

    st.divider()
    st.subheader("Cắt lát khoanh vùng")
    slice_tab1, slice_tab2 = st.tabs(["Theo quốc gia", "Theo creative"])

    with slice_tab1:
        country_df = cdoc.country_slice(raw_df, product_id, selected_campaign)
        if country_df.empty:
            st.info("Không có dữ liệu theo quốc gia cho campaign này.")
        else:
            st.dataframe(
                country_df, width="stretch", hide_index=True,
                column_config={
                    "CPI": st.column_config.NumberColumn(format="$%.4f"),
                    "ROAS D0": st.column_config.NumberColumn(format="percent"),
                    "Retention D1": st.column_config.NumberColumn(format="percent"),
                },
            )
            st.caption("ROAS D0 thấp nhất lên đầu — nghi phạm chính. Đã bỏ quốc gia <5 installs (quá ít để có ý nghĩa).")

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
# Điều hướng — API GỐC của Streamlit (st.navigation), có icon + nhóm danh mục
# ══════════════════════════════════════════════════════════════════════
pg = st.navigation(
    {
        # Key rỗng "" = mục lẻ, KHÔNG thuộc danh mục nào — Streamlit hiện phẳng,
        # không có mũi tên dropdown (giống "Intraday Report" trong ảnh mẫu).
        # Key có tên (VD "BigQuery") = danh mục thật, Streamlit TỰ thêm mũi tên
        # xổ xuống (đã xác nhận trong mã nguồn: data-testid="stNavSectionHeader",
        # tự có sẵn, không cần tự vẽ thêm).
        #
        # "Market Board" và "Report Builder" đều lấy dữ liệu từ BigQuery — xếp
        # chung nhóm BigQuery cho ĐÚNG nguồn dữ liệu. "Dashboard" (Adjust) và
        # "Meta + Adjust" (ghép cả 2 nguồn) không thuộc riêng BigQuery nên để
        # ở mục lẻ, cùng 1 danh sách "" (KHÔNG được lặp key "" 2 lần — dict
        # Python sẽ ghi đè mất mục đầu, đã gặp lỗi này khi thêm trang mới).
        #
        # Icon dùng Material Symbols (nét viền tối giản) — theo đúng phong cách
        # ảnh mẫu user gửi.
        "": [
            st.Page(page_adjust, title="Adjust", icon=":material/monitoring:", default=True),
            st.Page(page_meta_adjust, title="Meta + Adjust", icon=":material/join_inner:"),
            st.Page(page_alerts, title="Cảnh báo", icon=":material/warning:"),
            st.Page(page_campaign_doctor, title="Chẩn đoán", icon=":material/stethoscope:"),
        ],
        "BigQuery": [
            st.Page(page_report_builder, title="Report Builder", icon=":material/tune:"),
            st.Page(page_market_board, title="Market Board", icon=":material/leaderboard:"),
        ],
    },
    expanded=True,
)
pg.run()
