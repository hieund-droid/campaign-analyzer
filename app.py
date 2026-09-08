"""
Dashboard Streamlit — 2 tab:
1. Adjust: installs, CPI, ad revenue, ROAS D0/D7/D30, retention D1/D7, ARPU.
   MỖI NGƯỜI TỰ NHẬP API Token + App Token của mình (mỗi người dùng account
   Adjust riêng) — không dùng chung Secrets, chỉ lưu tạm trong session của họ.
2. BigQuery (Meta/TikTok/Google Ads + AdMob): dùng 1 service account key CHUNG
   cho cả team (đọc từ Secrets khi deploy, hoặc GOOGLE_APPLICATION_CREDENTIALS
   trong .env khi chạy local) — xem AGENT-BRIEF.md (không commit git) và
   GHI_CHU_TIEN_DO.md mục "Google Cloud service account key".

Cả 2 tab đều KHÔNG tự gọi API khi vừa mở — chọn bộ lọc rồi bấm nút mới gọi.
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import adjust_client as ac
import bq_client as bq

load_dotenv()  # đọc .env khi chạy local — dùng cho GOOGLE_APPLICATION_CREDENTIALS

st.set_page_config(page_title="Campaign Analyzer", layout="wide")


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
        return None, None, None, None, err

    start, end = bq.get_date_range(days_back)
    try:
        by_channel = bq.fetch_campaign_by_channel(client, product_id, start, end)
        campaign_trend = bq.fetch_campaign_trend(client, product_id, start, end)
        by_adunit = bq.fetch_admob_by_adunit(client, product_id, start, end)
        admob_trend = bq.fetch_admob_trend(client, product_id, start, end)
    except Exception as e:  # noqa: BLE001
        return None, None, None, None, f"Lỗi query BigQuery: {e}"

    return by_channel, campaign_trend, by_adunit, admob_trend, None


st.title("📊 Campaign Analyzer")
tab_adjust, tab_bq = st.tabs(["Adjust", "Meta/TikTok/Google Ads + AdMob (BigQuery)"])

# ══════════════════════════════════════════════════════════════════════
# TAB 1 — Adjust
# ══════════════════════════════════════════════════════════════════════
with tab_adjust:
    st.caption(
        "🔒 API Token + App Token chỉ lưu tạm trong phiên trình duyệt của bạn — "
        "mỗi người trong Apero dùng account Adjust riêng, không dùng chung."
    )
    col1, col2 = st.columns(2)
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

    # Preset kiểu Google Analytics — rõ ràng hơn slider + checkbox riêng.
    ADJUST_DATE_PRESETS = {
        "Hôm nay (đang chạy, chưa chốt)": (1, True),
        "Hôm qua": (1, False),
        "7 ngày qua": (7, False),
        "14 ngày qua": (14, False),
        "30 ngày qua": (30, False),
    }
    date_choice = st.selectbox("Khoảng ngày", list(ADJUST_DATE_PRESETS.keys()), index=2, key="adjust_date")
    days_back, include_today = ADJUST_DATE_PRESETS[date_choice]
    fetch_clicked = st.button("🔄 Kéo dữ liệu từ Adjust", type="primary", key="adjust_fetch")

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
        st.info("👆 Nhập token, chọn khoảng ngày rồi bấm **'Kéo dữ liệu từ Adjust'** để bắt đầu.")
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

        st.caption(
            f"Khoảng ngày: **{st.session_state.adjust_date_choice}**, giờ Việt Nam (UTC+7). "
            "Nguồn: Adjust Report Service API. Đổi bộ lọc App/Quốc gia/Campaign KHÔNG "
            "gọi lại API — chỉ lọc trên dữ liệu đã kéo."
        )
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
            st.caption(
                "Các cột ecpi_all/roas_ad_dN/retention_rate_dN ở bảng này là số Adjust "
                "trả về CHO ĐÚNG DÒNG đó — không cộng dồn/lấy trung bình qua nhiều dòng "
                "(KPI tổng hợp ở trên đã tính đúng cách rồi)."
            )
            st.dataframe(filtered, width="stretch", hide_index=True)

# ══════════════════════════════════════════════════════════════════════
# TAB 2 — BigQuery (Meta/TikTok/Google Ads + AdMob)
# ══════════════════════════════════════════════════════════════════════
with tab_bq:
    st.caption(
        "🔑 Dùng 1 key BigQuery dùng CHUNG cho cả team (không phải cá nhân như Adjust) — "
        "đã cấu hình sẵn, không cần nhập gì thêm."
    )

    bcol1, bcol2 = st.columns(2)
    with bcol1:
        product_id = st.selectbox("App (product_id)", bq.KNOWN_PRODUCT_IDS, key="bq_product")
    with bcol2:
        BQ_DATE_PRESETS = {"Hôm qua": 1, "7 ngày qua": 7, "14 ngày qua": 14, "30 ngày qua": 30}
        bq_date_choice = st.selectbox(
            "Khoảng ngày", list(BQ_DATE_PRESETS.keys()), index=1, key="bq_date",
            help="Dữ liệu này KHÔNG có 'hôm nay' — ngày mới nhất luôn là hôm qua (theo AGENT-BRIEF.md).",
        )
        bq_days_back = BQ_DATE_PRESETS[bq_date_choice]

    bq_fetch_clicked = st.button("🔄 Kéo dữ liệu từ BigQuery", type="primary", key="bq_fetch")

    if "bq_by_channel" not in st.session_state:
        st.session_state.bq_by_channel = None
        st.session_state.bq_campaign_trend = None
        st.session_state.bq_by_adunit = None
        st.session_state.bq_admob_trend = None
        st.session_state.bq_err = None
        st.session_state.bq_product_shown = None
        st.session_state.bq_date_shown = None

    if bq_fetch_clicked:
        (
            st.session_state.bq_by_channel,
            st.session_state.bq_campaign_trend,
            st.session_state.bq_by_adunit,
            st.session_state.bq_admob_trend,
            st.session_state.bq_err,
        ) = load_bq_data(product_id, bq_days_back)
        st.session_state.bq_product_shown = product_id
        st.session_state.bq_date_shown = bq_date_choice

    if st.session_state.bq_err:
        st.error(f"❌ {st.session_state.bq_err}")
    elif st.session_state.bq_by_channel is None:
        st.info("👆 Chọn app + khoảng ngày rồi bấm **'Kéo dữ liệu từ BigQuery'** để bắt đầu.")
    else:
        st.caption(
            f"App: **{st.session_state.bq_product_shown}** · Khoảng ngày: "
            f"**{st.session_state.bq_date_shown}**, giờ Bangkok/VN (UTC+7). "
            "Nguồn: BigQuery (`v_campaign_4c_daily`, `v_admob_ecpm_adunit_daily`)."
        )

        st.subheader("Meta / TikTok / Google Ads — theo channel")
        st.caption(
            "⚠️ Google Ads KHÔNG có impressions/clicks thật (đã kiểm chứng: ra 0 chứ "
            "không NULL — cột `cpm`/`ctr_pct`/`cvr_pct` sẽ trống với Google Ads, đây là "
            "đúng theo thiết kế, không phải lỗi — chỉ tin `spend`/`installs`/`cpi` của "
            "Google Ads). TikTok hiện có ~37% dòng NULL impressions mà tài liệu gốc "
            "KHÔNG lường trước — đang tạm loại các dòng đó khỏi tính CPM/CTR, CHƯA có "
            "xác nhận cuối cùng từ team Data."
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

        st.subheader("AdMob — eCPM theo ad unit (blended, weighted theo impressions)")
        by_adunit = st.session_state.bq_by_adunit
        if by_adunit.empty:
            st.warning("Không có dữ liệu AdMob nào trong khoảng ngày này.")
        else:
            st.dataframe(by_adunit, width="stretch", hide_index=True)

        admob_trend = st.session_state.bq_admob_trend
        if admob_trend is not None and len(admob_trend) >= 2:
            st.line_chart(admob_trend.set_index("day")[["ecpm_blended"]])
        elif admob_trend is not None and not admob_trend.empty:
            st.dataframe(admob_trend, width="stretch", hide_index=True)

        st.caption(
            "Lưu ý (theo AGENT-BRIEF.md): 2 bảng trên KHÔNG nối được với nhau ở mức "
            "campaign/ad-unit — chỉ nối được ở mức country×ngày, và impressions AdMob "
            "đến từ TOÀN BỘ user active, không riêng user do campaign này mang về. "
            "Không có Revenue/ROAS/Retention trong nguồn này — dùng tab Adjust cho phần đó."
        )
