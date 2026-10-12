"""
Phân tích QUY LUẬT LTV theo GIỜ TRONG NGÀY cho TỪNG THỊ TRƯỜNG (quốc gia),
gộp qua NHIỀU NGÀY đã chốt — để tìm "giờ vàng" (LTV cao ổn định)/"giờ đáy"
(LTV thấp ổn định) KHÔNG PHẢI nhiễu ngẫu nhiên của 1 ngày, rồi gợi ý khung
giờ nên tăng/giảm ngân sách theo từng thị trường (THÊM 24/09/2026, theo yêu
cầu user: "tổng hợp từ các camp biến động ... ra được quy luật tăng giảm
LTV của từng thị trường trong ngày rồi đưa ra suggest để UA action đúng").

Dùng `adjust_client.fetch_hourly_by_country()` (dimension "app,hour,country",
NHIỀU NGÀY ĐÃ CHỐT — không lấy "hôm nay", cần dữ liệu hoàn chỉnh để kết luận
quy luật đáng tin, không phải số đang chạy dở của 1 ngày).

CHỈ PHÂN TÍCH LTV (= ad_revenue ÷ installs) — KHÔNG CPI/ROAS: chi phí
(network_cost) không có grain thật theo giờ (Adjust dồn cả ngày vào 1 giờ
duy nhất, xem GHI_CHU_TIEN_DO.md mục "PHÁT HIỆN LỚN..." 23/09/2026) — dù gộp
bao nhiêu ngày cũng không sửa được giới hạn này.

CHỈ XÉT TOP THỊ TRƯỜNG theo DOANH THU (ad_revenue, KHÔNG phải theo installs —
đổi 24/09/2026 theo yêu cầu user: "việc chọn thị trường phải dựa vào rev
thôi, vì install ở các thị trường tier 2 3 lúc nào cũng nhiều hơn tier 1" —
xếp theo installs sẽ ưu tiên nhầm các thị trường tier 2/3 nhiều install
nhưng LTV thấp, bỏ sót tier 1 ít install hơn nhưng mới là nơi kiếm tiền
thật) + CHỈ giữ ô (quốc gia, giờ) có đủ install tối thiểu (gộp qua N ngày) —
quốc gia/giờ có quá ít dữ liệu (1-2 install rải rác) không đủ để kết luận là
"quy luật", chỉ là nhiễu ngẫu nhiên.
"""

import pandas as pd

DEFAULT_TOP_N_MARKETS = 8
DEFAULT_MIN_INSTALLS_PER_HOUR = 5

# THÊM 12/10/2026 (theo yêu cầu user — muốn gợi ý dùng thêm kinh nghiệm UA
# thực tế, VD: "US thì phải tăng tiêu lúc chiều-tối giờ VN vì khi đó bên US
# mới dậy user mới tải và dùng app"): quy đổi "giờ vàng"/"giờ đáy" (vốn tính
# theo mốc giờ VN, vì Adjust trả "hour" theo utc_offset=+07:00 đã cấu hình
# sẵn — xem adjust_client.py) sang GIỜ ĐỊA PHƯƠNG của chính thị trường đó, để
# biết NGAY vì sao khung giờ đó là vàng/đáy (VD trùng giờ user bản địa thức
# dậy) thay vì chỉ thấy 1 con số giờ VN trừu tượng.
#
# QUAN TRỌNG — đây là OFFSET ĐẠI DIỆN GẦN ĐÚNG, KHÔNG chính xác tuyệt đối:
# 1) dùng múi giờ CHUẨN (standard time), CHƯA tính giờ mùa hè (DST) — lệch
#    thêm 1 tiếng ở các nước có áp dụng DST vào mùa hè của họ.
# 2) nước trải dài NHIỀU múi giờ (Mỹ, Nga, Úc, Canada...) chỉ lấy 1 múi giờ
#    đại diện (thường là nơi đông dân/đông user nhất) — KHÔNG đúng cho toàn
#    bộ user của nước đó. Dùng để giải thích XU HƯỚNG chung, không phải số
#    chính xác cho từng user.
COUNTRY_UTC_OFFSET_HOURS = {
    "United States": -5,  # đại diện: giờ Miền Đông (ET) — đông dân/user nhất
    "Canada": -5,  # đại diện: Toronto (ET)
    "Mexico": -6,
    "Brazil": -3,
    "Argentina": -3,
    "United Kingdom": 0,
    "Ireland": 0,
    "Portugal": 0,
    "Germany": 1,
    "France": 1,
    "Spain": 1,
    "Italy": 1,
    "Netherlands": 1,
    "Poland": 1,
    "Sweden": 1,
    "Nigeria": 1,
    "South Africa": 2,
    "Egypt": 2,
    "Turkey": 3,
    "Russia": 3,  # đại diện: Moscow
    "Saudi Arabia": 3,
    "United Arab Emirates": 4,
    "Pakistan": 5,
    "India": 5.5,
    "Bangladesh": 6,
    "Vietnam": 7,
    "Thailand": 7,
    "Indonesia": 7,  # đại diện: Jakarta (WIB)
    "Cambodia": 7,
    "China": 8,
    "Philippines": 8,
    "Malaysia": 8,
    "Singapore": 8,
    "Taiwan": 8,
    "Hong Kong": 8,
    "Japan": 9,
    "South Korea": 9,
    "Australia": 10,  # đại diện: Sydney/Melbourne (AEST)
    "New Zealand": 12,
}


def _vn_hour_to_local_hour(hour_vn: int, country: str) -> int | None:
    """Giờ `hour_vn` (0-23, giờ VN — mốc Adjust đang trả về, xem docstring
    COUNTRY_UTC_OFFSET_HOURS) -> giờ địa phương gần đúng của `country`, hoặc
    None nếu chưa có offset cho nước đó."""
    offset = COUNTRY_UTC_OFFSET_HOURS.get(country)
    if offset is None:
        return None
    return int((hour_vn - (7 - offset)) % 24)


def format_local_hours(hours: list, country: str) -> str | None:
    """Đổi 1 danh sách giờ VN (VD giờ vàng/giờ đáy) sang chuỗi giờ địa phương
    gần đúng (VD "02h, 03h"), hoặc None nếu nước đó chưa có trong
    COUNTRY_UTC_OFFSET_HOURS (bỏ qua annotation thay vì suy đoán sai)."""
    local_hours = [_vn_hour_to_local_hour(h, country) for h in hours]
    if any(h is None for h in local_hours):
        return None
    return ", ".join(f"{h:02d}h" for h in sorted(set(local_hours)))


def build_hourly_market_patterns(
    hourly_country_df: pd.DataFrame,
    top_n_markets: int = DEFAULT_TOP_N_MARKETS,
    min_installs_per_hour: int = DEFAULT_MIN_INSTALLS_PER_HOUR,
) -> pd.DataFrame:
    """Input: df thô từ fetch_hourly_by_country() (cột app, hour, country,
    installs, ad_revenue, ...) — nhiều dòng, mỗi dòng là 1 (giờ CỤ THỂ của 1
    NGÀY CỤ THỂ, quốc gia). Gộp theo (quốc gia, GIỜ-TRONG-NGÀY 0-23, bỏ
    thông tin NGÀY nào) — cộng installs + ad_revenue của CÙNG khung giờ qua
    TẤT CẢ các ngày trong dữ liệu, rồi tính LTV trung bình cho khung giờ đó
    (sum-then-divide đúng cách, không lấy trung bình cộng qua các ngày).

    Output: DataFrame cột "Quốc gia", "Giờ" (0-23), "Installs" (tổng qua mọi
    ngày), "LTV" — CHỈ giữ Top `top_n_markets` quốc gia theo TỔNG DOANH THU
    (ad_revenue, KHÔNG phải installs — xem docstring đầu file), và CHỈ giữ ô
    (quốc gia, giờ) có đủ `min_installs_per_hour` install."""
    if hourly_country_df is None or hourly_country_df.empty:
        return pd.DataFrame()

    df = hourly_country_df.copy()
    for col in ("installs", "ad_revenue"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["hour_of_day"] = df["hour"].str.slice(11, 13).astype(int)

    top_markets = (
        df.groupby("country")["ad_revenue"].sum().sort_values(ascending=False).head(top_n_markets).index.tolist()
    )
    df = df[df["country"].isin(top_markets)]
    if df.empty:
        return pd.DataFrame()

    grouped = df.groupby(["country", "hour_of_day"])[["installs", "ad_revenue"]].sum().reset_index()
    grouped = grouped[grouped["installs"] >= min_installs_per_hour].copy()
    if grouped.empty:
        return pd.DataFrame()
    grouped["ltv"] = grouped["ad_revenue"] / grouped["installs"].replace(0, pd.NA)

    return grouped.rename(
        columns={"country": "Quốc gia", "hour_of_day": "Giờ", "installs": "Installs", "ltv": "LTV"}
    )[["Quốc gia", "Giờ", "Installs", "LTV"]]


def summarize_peak_and_low_hours(patterns_df: pd.DataFrame, top_n_hours: int = 3) -> pd.DataFrame:
    """Với MỖI quốc gia trong `patterns_df` (kết quả của
    build_hourly_market_patterns()), tìm `top_n_hours` giờ có LTV CAO NHẤT
    ("giờ vàng") và `top_n_hours` giờ có LTV THẤP NHẤT ("giờ đáy") — dùng để
    gợi ý khung giờ nên tăng/giảm ngân sách. Bỏ qua quốc gia có ít hơn 2×
    `top_n_hours` giờ dữ liệu (không đủ để so sánh "cao" vs "thấp" có ý
    nghĩa — VD nếu chỉ có 4 giờ dữ liệu mà lấy top 3 + bottom 3 sẽ trùng
    nhau)."""
    if patterns_df is None or patterns_df.empty:
        return pd.DataFrame()

    rows = []
    for country, g in patterns_df.groupby("Quốc gia"):
        if len(g) < 2 * top_n_hours:
            continue
        g_sorted = g.sort_values("LTV", ascending=False)
        peak = g_sorted.head(top_n_hours)
        low = g_sorted.tail(top_n_hours)
        peak_avg = peak["LTV"].mean()
        low_avg = low["LTV"].mean()
        # SỬA 24/09/2026 — lưu dạng PHÂN SỐ (0.6635), KHÔNG nhân sẵn 100
        # (66.35): dùng `st.column_config.NumberColumn(format="percent")` ở
        # app.py cần input là phân số (tự nhân 100 khi hiện) — trước đó lưu
        # số ĐÃ nhân 100 + format in kèm "%%" viết tay khiến cột hiện TRỐNG
        # trên Streamlit Cloud (user chụp ảnh chỉ ra) dù dữ liệu/sắp xếp vẫn
        # đúng ngầm bên trong — đổi sang cách "percent" chuẩn, đã dùng ổn ở
        # nơi khác trong app (VD cột ROAS D0/Retention D1).
        diff_pct = ((peak_avg - low_avg) / low_avg) if low_avg else None
        rows.append({
            "Quốc gia": country,
            "Giờ vàng": ", ".join(f"{h:02d}h" for h in sorted(peak["Giờ"])),
            "LTV giờ vàng (TB)": peak_avg,
            "Giờ đáy": ", ".join(f"{h:02d}h" for h in sorted(low["Giờ"])),
            "LTV giờ đáy (TB)": low_avg,
            "Chênh lệch (%)": diff_pct,
            # Cột ẨN (bắt đầu bằng "_") — list giờ THÔ (không phải chuỗi hiển
            # thị) để build_market_suggestions() tính giờ NÊN HÀNH ĐỘNG (sớm
            # hơn giờ thực tế — xem hàm đó). app.py PHẢI bỏ 2 cột này trước
            # khi hiện bảng ra UI (không phải dữ liệu để xem trực tiếp).
            "_peak_hours": sorted(peak["Giờ"].tolist()),
            "_low_hours": sorted(low["Giờ"].tolist()),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Chênh lệch (%)", ascending=False).reset_index(drop=True)


ACTION_LEAD_HOURS = 1


def _format_hour_list(hours: list) -> str:
    return ", ".join(f"{h:02d}h" for h in sorted(hours))


def _shift_hours_earlier(hours: list, lead_hours: int = ACTION_LEAD_HOURS) -> list:
    """Trừ `lead_hours` tiếng cho mỗi giờ (mod 24, qua nửa đêm vẫn đúng — VD
    giờ 0 trừ 1 tiếng ra giờ 23). THÊM 24/09/2026 theo yêu cầu user: "nên
    action sớm hơn tầm 1 tiếng, ví dụ đến giờ tiêu của Mỹ thì tăng trước 1
    tiếng thì để vào giờ tiêu bid căng là vừa" — bid/ngân sách cần thời gian
    "làm nóng" trên hệ thống đấu giá của network, tăng/giảm ĐÚNG lúc LTV đổi
    thường đã trễ mất phần đầu khung giờ đó."""
    return sorted({(h - lead_hours) % 24 for h in hours})


def build_market_suggestions(summary_df: pd.DataFrame) -> list:
    """THÊM 24/09/2026 (theo yêu cầu user — "bảng ... hãy có cả suggest ở
    dưới ... theo đầu thị trường"): sinh 1 câu gợi ý hành động CỤ THỂ cho
    TỪNG thị trường trong `summary_df` (kết quả summarize_peak_and_low_hours())
    — tăng ngân sách vào ĐÚNG khung giờ vàng của thị trường đó, giảm vào ĐÚNG
    khung giờ đáy — thay vì chỉ 1 caption chung chung áp dụng mọi thị trường
    như nhau. Giữ nguyên thứ tự `summary_df` (đã sắp chênh lệch cao nhất lên
    đầu — đáng làm nhất trước).

    SỬA 24/09/2026 — HÀNH ĐỘNG SỚM HƠN `ACTION_LEAD_HOURS` (mặc định 1) tiếng
    so với khung giờ vàng/đáy THỰC TẾ (xem docstring _shift_hours_earlier()):
    câu gợi ý giờ nêu RÕ CẢ HAI — giờ NÊN HÀNH ĐỘNG (sớm hơn) và khung giờ LTV
    thực tế quan sát được (để biết vì sao lại chọn giờ đó)."""
    if summary_df is None or summary_df.empty:
        return []
    # LƯU Ý escape "\$" (KHÔNG để "$" trần) — Streamlit render markdown coi 2
    # dấu "$" trở lên trong CÙNG 1 lần gọi st.markdown() là ranh giới công
    # thức LaTeX, nuốt mất chữ ở giữa (kể cả **bold**) — đã gặp lỗi thật
    # (24/09/2026, user chụp ảnh chỉ ra "**giảm**" hiện nguyên văn không in
    # đậm, dấu "$" biến mất) do câu gợi ý có 2 số tiền "$X" trong 1 câu.
    rows = []
    for _, r in summary_df.iterrows():
        country = r["Quốc gia"]
        peak_action = _format_hour_list(_shift_hours_earlier(r["_peak_hours"]))
        low_action = _format_hour_list(_shift_hours_earlier(r["_low_hours"]))

        # THÊM 12/10/2026 (theo yêu cầu user — muốn gợi ý dùng kinh nghiệm UA
        # thực tế thay vì chỉ 1 con số giờ VN trừu tượng): nếu nước này có
        # trong COUNTRY_UTC_OFFSET_HOURS, chú thích thêm giờ ĐỊA PHƯƠNG của
        # khung giờ vàng/đáy THỰC TẾ — giúp giải thích/kiểm chứng bằng mắt
        # thường VÌ SAO đó là giờ vàng (VD trùng giờ user bản địa thức dậy)
        # thay vì chỉ tin số liệu thuần tuý. Bỏ qua (None) nếu chưa có offset
        # cho nước đó — KHÔNG suy đoán.
        peak_local = format_local_hours(r["_peak_hours"], country)
        low_local = format_local_hours(r["_low_hours"], country)
        peak_local_txt = f" (≈ {peak_local} giờ địa phương {country})" if peak_local else ""
        low_local_txt = f" (≈ {low_local} giờ địa phương {country})" if low_local else ""

        rows.append({
            "Quốc gia": country,
            "Gợi ý": (
                f"**Tăng** ngân sách/bid vào khung **{peak_action}** (đón đầu "
                f"{ACTION_LEAD_HOURS} tiếng trước khung LTV thực tế cao "
                f"**{r['Giờ vàng']}**{peak_local_txt}, LTV TB "
                f"\\${r['LTV giờ vàng (TB)']:.4f}) "
                f"— **giảm**/dồn ngân sách khỏi khung **{low_action}** (đón "
                f"đầu trước khung LTV thực tế thấp **{r['Giờ đáy']}**"
                f"{low_local_txt}, LTV TB "
                f"\\${r['LTV giờ đáy (TB)']:.4f}) — chênh lệch "
                f"{r['Chênh lệch (%)'] * 100:.0f}%."
            ),
        })
    return rows
