"""
Dashboard Streamlit — xem dữ liệu lõi từ Adjust (installs, CPI, ad revenue,
ROAS D0/D7/D30, retention D1/D7, ARPU).

MỖI NGƯỜI DÙNG TỰ NHẬP API TOKEN + APP TOKEN CỦA MÌNH ở sidebar khi mở app —
không dùng chung 1 bộ token trong Secrets, vì mỗi người trong Apero dùng account
Adjust riêng (cả API Token lẫn App Token đều khác nhau giữa mọi người). Token chỉ
lưu tạm trong session_state của trình duyệt người đó, không lưu trên server,
không chia sẻ giữa những người cùng dùng chung link app này.

App KHÔNG tự gọi Adjust API khi vừa mở — người dùng nhập token, chọn khoảng
ngày, rồi bấm nút "Kéo dữ liệu" mới gọi (tránh gọi API liên tục mỗi lần đổi bộ
lọc/mở lại trang, nhất là sau khi từng bị nghi rate limit vì gọi quá nhiều lần).
Có cache tạm 15 phút cho mỗi tổ hợp (token, khoảng ngày) đã kéo.

App không đọc từ adjust_data.db (dù có sẵn) — vì app chạy trên máy chủ Streamlit,
không đọc được file SQLite nằm trên máy cá nhân — xem GHI_CHU_TIEN_DO.md.

Chạy thử ở máy: streamlit run app.py (không cần .env — nhập token trực tiếp trên
giao diện). Deploy lên Streamlit Cloud: không cần dán Secrets nữa, xem README.md.
"""

import pandas as pd
import streamlit as st

import adjust_client as ac

st.set_page_config(page_title="Campaign Analyzer — Adjust", layout="wide")


@st.cache_data(ttl=15 * 60, show_spinner="Đang lấy dữ liệu từ Adjust...")
def load_data(days_back: int, app_tokens_raw: str, api_token: str):
    # QUAN TRỌNG: api_token + app_tokens_raw PHẢI là tham số của hàm (không đọc
    # secret/session ngầm bên trong) — Streamlit chỉ cache dựa theo tham số truyền
    # vào. Nếu đọc ngầm bên trong hàm, đổi giá trị sẽ KHÔNG làm cache cũ mất hiệu
    # lực (đã gặp lỗi thật: thêm app thứ 2 vẫn chỉ thấy app cũ).
    if not api_token or not app_tokens_raw:
        return None, "Thiếu API Token / ADJUST_APP_TOKENS.", None

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    try:
        data = ac.fetch_detail(api_token, app_tokens, days_back=days_back, exit_on_error=False)
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
    dòng, cộng dồn, rồi chia lại — giống cách adjust_test.py đang làm.
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


# ── Sidebar: mỗi người tự nhập token của mình ───────────────────────
# Mỗi người trong Apero dùng account Adjust riêng (API Token + App Token đều
# khác nhau giữa các người) — KHÔNG dùng chung 1 bộ token trong Secrets nữa.
# Token nhập vào đây chỉ nằm trong session_state của TRÌNH DUYỆT người đó, không
# lưu lại trên server, không ai khác xem được — nhập lại mỗi khi mở app mới.
st.sidebar.header("Tài khoản Adjust của bạn")
user_api_token = st.sidebar.text_input(
    "API Token cá nhân",
    type="password",
    help='Adjust → Settings góc dưới trái → Account settings → tab "My profile" → API Token',
)
user_app_tokens_raw = st.sidebar.text_input(
    "App Token (cách nhau bởi dấu phẩy nếu nhiều app)",
    help='Adjust → mở app → Cài đặt app → "App Token" (~12 ký tự)',
)
st.sidebar.caption(
    "🔒 2 ô trên chỉ lưu tạm trong phiên trình duyệt của bạn, không lưu trên "
    "server, không chia sẻ với người khác dùng chung app này."
)

st.sidebar.header("Bộ lọc")
days_back = st.sidebar.slider("Số ngày gần nhất", min_value=1, max_value=30, value=7)
fetch_clicked = st.sidebar.button("🔄 Kéo dữ liệu từ Adjust", type="primary")

# Lưu kết quả vào session_state — để đổi bộ lọc app/quốc gia/campaign bên dưới
# KHÔNG làm gọi lại API (Streamlit chạy lại toàn bộ script mỗi khi đổi widget).
if "df" not in st.session_state:
    st.session_state.df = None
    st.session_state.err = None
    st.session_state.warning_msg = None
    st.session_state.days_back = None

if fetch_clicked:
    st.session_state.df, st.session_state.err, st.session_state.warning_msg = load_data(
        days_back, user_app_tokens_raw, user_api_token
    )
    st.session_state.days_back = days_back

df = st.session_state.df
err = st.session_state.err
warning_msg = st.session_state.warning_msg

st.title("📊 Campaign Analyzer — Adjust")

if err:
    st.error(f"❌ {err}")
    st.stop()
if warning_msg:
    st.warning(f"⚠️ Adjust cảnh báo: {warning_msg}")
if df is None:
    st.info("👈 Chọn số ngày ở sidebar rồi bấm **'Kéo dữ liệu từ Adjust'** để bắt đầu.")
    st.stop()
if df.empty:
    st.warning("⚠️ Không có dữ liệu cho khoảng ngày này.")
    st.stop()

apps = sorted(df["app"].dropna().unique().tolist())
countries = sorted(df["country"].dropna().unique().tolist())

selected_apps = st.sidebar.multiselect("App", apps, default=apps)
selected_countries = st.sidebar.multiselect("Quốc gia (để trống = tất cả)", countries, default=[])
campaign_search = st.sidebar.text_input("Tìm campaign (gõ 1 phần tên)")

filtered = df[df["app"].isin(selected_apps)] if selected_apps else df.iloc[0:0]
if selected_countries:
    filtered = filtered[filtered["country"].isin(selected_countries)]
if campaign_search:
    filtered = filtered[filtered["campaign"].str.contains(campaign_search, case=False, na=False)]

# ── Nội dung chính ───────────────────────────────────────────────────
st.caption(
    f"Dữ liệu {st.session_state.days_back} ngày gần nhất (tính đến hôm qua), giờ "
    "Việt Nam (UTC+7). Nguồn: Adjust Report Service API. Chưa gồm AdMob/Meta. "
    "Đổi bộ lọc App/Quốc gia/Campaign bên dưới KHÔNG gọi lại API — chỉ lọc trên "
    "dữ liệu đã kéo."
)

if filtered.empty:
    st.warning("Không có dòng nào khớp bộ lọc hiện tại.")
    st.stop()

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
    # Không vẽ biểu đồ với đúng 1 điểm — cả line_chart (không có đường để nối)
    # lẫn bar_chart (Streamlit/Vega-Lite kéo giãn cột thành mảng phẳng sai hình
    # khi chỉ có 1 category) đều hiển thị sai. Hiện bảng số thay thế.
    st.info("Chỉ có 1 ngày dữ liệu — chọn thêm ngày ở sidebar để xem xu hướng dạng biểu đồ.")
    st.dataframe(trend, width="stretch")
else:
    st.line_chart(trend)

st.subheader("Dữ liệu chi tiết")
st.caption(
    "Các cột ecpi_all/roas_ad_dN/retention_rate_dN ở bảng này là số Adjust trả "
    "về CHO ĐÚNG DÒNG đó — không cộng dồn/lấy trung bình các cột này qua nhiều dòng "
    "(xem KPI tổng hợp ở trên đã tính đúng cách rồi)."
)
st.dataframe(filtered, width="stretch", hide_index=True)
