"""
Dashboard Streamlit — điều hướng bằng `st.navigation()` (API điều hướng GỐC của
Streamlit, không tự chế bằng radio nữa) — cho icon + nhóm danh mục kiểu 1 BI
tool nội bộ khác của Apero. Việc thu/mở cả sidebar là tính năng có sẵn của
Streamlit (không phải do code này), phần code cải thiện là icon + nhóm mục.

4 trang, nhóm theo 2 danh mục:
- "Adjust": installs, CPI, ad revenue, ROAS D0/D7/D30, retention D1/D7, ARPU.
  MỖI NGƯỜI TỰ NHẬP API Token + App Token của mình (mỗi người dùng account
  Adjust riêng) — không dùng chung Secrets, chỉ lưu tạm trong session của họ.
- "BigQuery": Tổng quan (Meta/TikTok/Google Ads theo channel + AdMob theo ad
  unit/quốc gia) + Tự chọn dimension (pivot AdMob linh hoạt kiểu AdMob console,
  giới hạn trong 2 metric + 3 dimension mà view BigQuery có). Dùng 1 service
  account key CHUNG cho cả team (đọc từ Secrets khi deploy, hoặc
  GOOGLE_APPLICATION_CREDENTIALS trong .env khi chạy local) — xem
  AGENT-BRIEF.md (không commit git) và GHI_CHU_TIEN_DO.md.
- "Thị trường": Bảng điểm thị trường — eCPM từng quốc gia so với benchmark tự
  nhập cho từng app (màu 🟢/🔴) + sparkline xu hướng — xem `benchmarks.py`.

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

    /* Tiêu đề danh mục (VD "BigQuery") — chữ nhỏ, xám nhạt, có mũi tên sẵn */
    [data-testid="stNavSectionHeader"] {
        color: #8CA3C0;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }

    /* Mục sidebar — mặc định (chưa chọn): xanh nhạt, giống ảnh mẫu */
    [data-testid="stSidebarNavLink"] {
        color: #7FC4E8;
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
    </style>
    """,
    unsafe_allow_html=True,
)


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


@st.cache_data(ttl=15 * 60, show_spinner="Đang query BigQuery...")
def load_bq_data(product_id: str, days_back: int):
    client, err = get_bq_client()
    if err:
        return None, None, None, None, None, err

    start, end = bq.get_date_range(days_back)
    try:
        by_channel = bq.fetch_campaign_by_channel(client, product_id, start, end)
        campaign_trend = bq.fetch_campaign_trend(client, product_id, start, end)
        by_adunit = bq.fetch_admob_by_adunit(client, product_id, start, end)
        by_country = bq.fetch_admob_by_country(client, product_id, start, end)
        admob_trend = bq.fetch_admob_trend(client, product_id, start, end)
    except Exception as e:  # noqa: BLE001
        return None, None, None, None, None, f"Lỗi query BigQuery: {e}"

    return by_channel, campaign_trend, by_adunit, by_country, admob_trend, None


# ══════════════════════════════════════════════════════════════════════
# TRANG — Adjust
# ══════════════════════════════════════════════════════════════════════
def page_adjust():
    st.title("Adjust")
    st.caption("🔒 Token chỉ lưu trong phiên của bạn — mỗi người tự nhập.")
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
    with col1:
        user_api_token = st.text_input(
            "API Token cá nhân (Adjust)",
            type="password",
            help='Adjust → Settings góc dưới trái → Account settings → tab "My profile" → API Token',
            key="adjust_api_token",
        )
    with col2:
        user_app_tokens_raw = st.text_input(
            "App Token (cách nhau bởi dấu phẩy nếu nhiều app)",
            help='Adjust → mở app → Cài đặt app → "App Token" (~12 ký tự)',
            key="adjust_app_tokens",
        )
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
                st.line_chart(trend)

            st.subheader("Dữ liệu chi tiết")
            st.caption("ℹ️ Các cột % ở đây là theo từng dòng, không cộng dồn được (KPI trên đã tính đúng).")
            st.dataframe(filtered, width="stretch", hide_index=True)


# ══════════════════════════════════════════════════════════════════════
# TRANG — BigQuery Tổng quan
# ══════════════════════════════════════════════════════════════════════
def page_bq_overview():
    st.title("BigQuery — Tổng quan")
    st.caption("🔑 Key dùng chung cho cả team — không cần nhập gì thêm.")

    bcol1, bcol2, bcol3 = st.columns([2, 2, 1])
    with bcol1:
        product_id = st.selectbox("App (product_id)", bq.KNOWN_PRODUCT_IDS, key="bq_product")
    with bcol2:
        BQ_DATE_PRESETS = {"Hôm qua": 1, "7 ngày qua": 7, "14 ngày qua": 14, "30 ngày qua": 30}
        bq_date_choice = st.selectbox(
            "Khoảng ngày", list(BQ_DATE_PRESETS.keys()), index=1, key="bq_date",
            help="Dữ liệu này KHÔNG có 'hôm nay' — ngày mới nhất luôn là hôm qua (theo AGENT-BRIEF.md).",
        )
        bq_days_back = BQ_DATE_PRESETS[bq_date_choice]
    with bcol3:
        st.write("")
        st.write("")
        bq_fetch_clicked = st.button("Apply", type="primary", key="bq_fetch", width="stretch")

    if "bq_by_channel" not in st.session_state:
        st.session_state.bq_by_channel = None
        st.session_state.bq_campaign_trend = None
        st.session_state.bq_by_adunit = None
        st.session_state.bq_by_country = None
        st.session_state.bq_admob_trend = None
        st.session_state.bq_err = None
        st.session_state.bq_product_shown = None
        st.session_state.bq_date_shown = None

    if bq_fetch_clicked:
        (
            st.session_state.bq_by_channel,
            st.session_state.bq_campaign_trend,
            st.session_state.bq_by_adunit,
            st.session_state.bq_by_country,
            st.session_state.bq_admob_trend,
            st.session_state.bq_err,
        ) = load_bq_data(product_id, bq_days_back)
        st.session_state.bq_product_shown = product_id
        st.session_state.bq_date_shown = bq_date_choice

    if st.session_state.bq_err:
        st.error(f"❌ {st.session_state.bq_err}")
    elif st.session_state.bq_by_channel is None:
        st.info("👆 Chọn app + khoảng ngày rồi bấm **Apply** để bắt đầu.")
    else:
        st.caption(f"{st.session_state.bq_product_shown} · {st.session_state.bq_date_shown}")

        st.subheader("Meta / TikTok / Google Ads — theo channel")
        st.caption(
            "⚠️ Google Ads: không có CPM/CTR (thiếu impressions thật). "
            "TikTok: ~37% dòng thiếu impressions (đang loại khỏi CPM/CTR)."
        )
        by_channel = st.session_state.bq_by_channel
        if by_channel.empty:
            st.warning("Không có dữ liệu channel nào trong khoảng ngày này.")
        else:
            st.dataframe(by_channel, width="stretch", hide_index=True)

        campaign_trend = st.session_state.bq_campaign_trend
        if campaign_trend is not None and len(campaign_trend) >= 2:
            st.line_chart(campaign_trend.set_index("day")[["spend", "installs"]])
        elif campaign_trend is not None and not campaign_trend.empty:
            st.dataframe(campaign_trend, width="stretch", hide_index=True)

        adcol1, adcol2 = st.columns(2)
        with adcol1:
            st.subheader("AdMob — eCPM theo ad unit")
            by_adunit = st.session_state.bq_by_adunit
            if by_adunit.empty:
                st.warning("Không có dữ liệu AdMob nào trong khoảng ngày này.")
            else:
                st.dataframe(by_adunit, width="stretch", hide_index=True)
        with adcol2:
            st.subheader("AdMob — eCPM theo thị trường (quốc gia)")
            by_country = st.session_state.bq_by_country
            if by_country.empty:
                st.warning("Không có dữ liệu AdMob nào trong khoảng ngày này.")
            else:
                st.dataframe(by_country, width="stretch", hide_index=True)
        st.caption("eCPM là số blended theo impressions, không phải trung bình đơn giản.")

        admob_trend = st.session_state.bq_admob_trend
        if admob_trend is not None and len(admob_trend) >= 2:
            # 2 biểu đồ riêng — eCPM ($0.x-vài $) và doanh thu (hàng trăm $) lệch
            # thang đo quá xa, gộp chung 1 chart sẽ làm eCPM biến mất khỏi mắt.
            tcol1, tcol2 = st.columns(2)
            with tcol1:
                st.caption("eCPM blended theo ngày")
                st.line_chart(admob_trend.set_index("day")[["ecpm_blended"]])
            with tcol2:
                st.caption("Doanh thu suy ra theo ngày (revenue_implied)")
                st.line_chart(admob_trend.set_index("day")[["revenue_implied"]])
        elif admob_trend is not None and not admob_trend.empty:
            st.dataframe(admob_trend, width="stretch", hide_index=True)

        st.caption("ℹ️ 2 bảng trên không nối được ở mức campaign/ad-unit. Revenue/ROAS/Retention xem ở mục Adjust.")


# ══════════════════════════════════════════════════════════════════════
# TRANG — BigQuery Tự chọn dimension (kiểu AdMob console)
# ══════════════════════════════════════════════════════════════════════
def page_bq_flexible():
    st.title("BigQuery — Tự chọn dimension")
    st.caption("🔑 Key dùng chung team. Chỉ có Impressions + eCPM theo Quốc gia/Ad unit/Định dạng.")

    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        flex_product_id = st.selectbox("App (product_id)", bq.KNOWN_PRODUCT_IDS, key="bq_flex_product")
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
# TRANG — Bảng điểm thị trường (eCPM vs benchmark theo quốc gia)
# ══════════════════════════════════════════════════════════════════════
def page_market_scorecard():
    st.title("Bảng điểm thị trường")
    st.caption("eCPM từng quốc gia so với benchmark riêng của nước đó · 🟢 đạt · 🔴 dưới benchmark.")
    st.warning("⚠️ Benchmark có thể mất khi app khởi động lại — chưa lưu bền vững.")

    mcol1, mcol2, mcol3 = st.columns(3)
    with mcol1:
        mkt_product_id = st.selectbox("App (product_id)", bq.KNOWN_PRODUCT_IDS, key="mkt_product")
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
        st.subheader("Bảng điểm thị trường")
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
# Điều hướng — API GỐC của Streamlit (st.navigation), có icon + nhóm danh mục
# ══════════════════════════════════════════════════════════════════════
pg = st.navigation(
    {
        # Key rỗng "" = mục lẻ, KHÔNG thuộc danh mục nào — Streamlit hiện phẳng,
        # không có mũi tên dropdown (giống "Intraday Report" trong ảnh mẫu).
        # Key có tên (VD "BigQuery") = danh mục thật, Streamlit TỰ thêm mũi tên
        # xổ xuống (đã xác nhận trong mã nguồn: data-testid="stNavSectionHeader",
        # tự có sẵn, không cần tự vẽ thêm).
        "": [
            st.Page(page_adjust, title="Dashboard", icon="📈", default=True),
            st.Page(page_market_scorecard, title="Bảng điểm thị trường", icon="🏆"),
        ],
        "BigQuery": [
            st.Page(page_bq_overview, title="Tổng quan", icon="📋"),
            st.Page(page_bq_flexible, title="Tự chọn dimension", icon="🎯"),
        ],
    },
    expanded=True,
)
pg.run()
