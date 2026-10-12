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
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Chênh lệch (%)", ascending=False).reset_index(drop=True)


# THÊM 24/09/2026 theo yêu cầu user: "nên action sớm hơn tầm 1 tiếng, ví dụ
# đến giờ tiêu của Mỹ thì tăng trước 1 tiếng thì để vào giờ tiêu bid căng là
# vừa" — bid/ngân sách cần thời gian "làm nóng" trên hệ thống đấu giá của
# network, tăng/giảm ĐÚNG lúc LTV đổi thường đã trễ mất phần đầu khung giờ đó.
ACTION_LEAD_HOURS = 1


# THÊM 12/10/2026 (theo yêu cầu user): `build_market_suggestions()` ở trên
# chọn "giờ vàng"/"giờ đáy" bằng cách lấy TOP N GIỜ RIÊNG LẺ theo LTV cao/
# thấp nhất — các giờ đó CÓ THỂ không liền nhau (VD giờ vàng là 9h, 14h, 20h
# rải rác) và KHÔNG phân biệt được "đây là 1 ĐỢT tăng/giảm kéo dài" hay chỉ
# là các giờ đơn lẻ tình cờ cao/thấp. User: "chỉ khi bắt đầu một đợt tăng/
# giảm LTV dài thì mới suggest tăng/giảm budget, vì nếu LTV chỉ cao ở 1 khung
# giờ rồi nó down xuống thì việc action tăng budget ở khung giờ đó sẽ không
# phù hợp lắm" — cần tách ĐOẠN xu hướng LIÊN TỤC (giống
# intraday_alerts.detect_trend_segments(), nhưng áp dụng cho đường LTV theo
# GIỜ-TRONG-NGÀY đã gộp qua NHIỀU NGÀY của 1 thị trường, thay vì 1 ngày cụ
# thể của 1 campaign) rồi chỉ gợi ý hành động cho đoạn ĐỦ DÀI.
DEFAULT_MARKET_MIN_STEP_PCT = 10.0
MIN_SEGMENT_HOURS_FOR_MARKET_ACTION = 2


def _pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b - a) / a * 100


def _build_market_segment(df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> dict:
    start_row = df.loc[start_idx]
    end_row = df.loc[end_idx]
    pct_change = _pct(start_row["LTV"], end_row["LTV"])
    # SỬA 12/10/2026 — xem docstring intraday_alerts._build_segment() (CÙNG
    # bug, cùng cơ chế: `direction` kế thừa từ bước kích hoạt lớn gần nhất có
    # thể ngược dấu với % đổi THẬT đầu-cuối của cả đoạn). Luôn ưu tiên dấu
    # thật của `pct_change`.
    final_direction = direction if pct_change is None else ("tang" if pct_change >= 0 else "giam")
    return {
        "direction": final_direction,
        "start_hour": int(start_row["Giờ"]),
        "end_hour": int(end_row["Giờ"]),
        "start_ltv": start_row["LTV"],
        "end_ltv": end_row["LTV"],
        "pct_change": pct_change,
    }


def detect_market_trend_segments(
    patterns_df: pd.DataFrame,
    country: str,
    min_step_pct: float = DEFAULT_MARKET_MIN_STEP_PCT,
    min_endpoint_installs_ratio: float = 0.2,
    min_absolute_installs: int = 15,
) -> list:
    """Input: `patterns_df` = kết quả build_hourly_market_patterns() (cột
    "Quốc gia", "Giờ" 0-23, "Installs", "LTV" — đã gộp qua NHIỀU NGÀY). Tách
    đường LTV theo GIỜ-TRONG-NGÀY của ĐÚNG `country` thành các ĐOẠN xu hướng
    liên tục (tăng dần/giảm dần) — CÙNG thuật toán với
    intraday_alerts.detect_trend_segments() (xem docstring hàm đó để biết
    đầy đủ lý do từng bước), chuyển sang dùng "Giờ" (int 0-23) thay vì
    timestamp đầy đủ vì đây là đường ĐÃ GỘP nhiều ngày thành 1 ngày đại diện.

    KHÔNG bắc cầu qua giờ bị lọc mất (gap giữa 2 giờ liền kề trong df > 1) —
    cùng lý do: nếu giờ ở giữa bị lọc vì quá ít install, không biết thật sự
    chuyện gì xảy ra trong khoảng đó, không nên gộp thành 1 đoạn liền.

    `min_endpoint_installs_ratio`/`min_absolute_installs` — CÙNG cơ chế
    chống "cold start" đã dùng ở intraday_alerts.py (giờ đầu tiên luôn có
    LTV thấp giả tạo vì user mới cài chưa kịp sinh doanh thu TRONG giờ đó,
    áp dụng cho MỌI ngày nên vẫn đúng ở đường đã gộp nhiều ngày): điểm đầu/
    cuối 1 bước phải đạt CẢ tỉ lệ % lẫn số tuyệt đối install (cộng dồn theo
    thứ tự Giờ) so với install cộng dồn cuối cùng mới hợp lệ.

    GIỚI HẠN ĐÃ BIẾT: không xử lý xu hướng "bắc cầu qua nửa đêm" (VD 1 đợt
    giảm thật ra kéo dài từ 22h hôm trước sang 2h hôm sau) — vì "Giờ" ở đây
    là chu kỳ 0-23 của 1 NGÀY ĐẠI DIỆN (đã gộp nhiều ngày), sắp xếp tuyến
    tính 0→23 nên không nối được 23h với 0h. Chấp nhận đánh đổi này để đơn
    giản hoá — đa số đợt tăng/giảm đáng chú ý nằm trong 1 ngày, không qua
    nửa đêm."""
    if patterns_df is None or patterns_df.empty:
        return []
    df = patterns_df[patterns_df["Quốc gia"] == country].copy()
    if df.empty or len(df) < 2:
        return []
    df = df.sort_values("Giờ").reset_index(drop=True)

    df["installs_running_cum"] = df["Installs"].cumsum()
    final_installs_cum = df["installs_running_cum"].iloc[-1]
    min_endpoint_installs = max(
        min_endpoint_installs_ratio * final_installs_cum if min_endpoint_installs_ratio else 0,
        min_absolute_installs or 0,
    )
    if min_endpoint_installs:
        df = df[df["installs_running_cum"] >= min_endpoint_installs].reset_index(drop=True)
    if len(df) < 2:
        return []

    segments = []
    current_dir = None
    seg_start_idx = 0
    for i in range(1, len(df)):
        gap = df.loc[i, "Giờ"] - df.loc[i - 1, "Giờ"]
        if gap > 1:
            if current_dir is not None:
                segments.append(_build_market_segment(df, seg_start_idx, i - 1, current_dir))
            current_dir = None
            seg_start_idx = i
            continue

        pct = _pct(df.loc[i - 1, "LTV"], df.loc[i, "LTV"])
        if pct is None:
            continue
        if pct >= min_step_pct:
            step_dir = "tang"
        elif pct <= -min_step_pct:
            step_dir = "giam"
        else:
            step_dir = None

        if step_dir is None:
            continue
        if current_dir is None:
            current_dir = step_dir
            seg_start_idx = i - 1
        elif step_dir != current_dir:
            segments.append(_build_market_segment(df, seg_start_idx, i - 1, current_dir))
            current_dir = step_dir
            seg_start_idx = i - 1

    if current_dir is not None:
        segments.append(_build_market_segment(df, seg_start_idx, len(df) - 1, current_dir))

    return segments


def describe_market_segment_suggestion(segment: dict, country: str, lead_hours: int = ACTION_LEAD_HOURS) -> str:
    """Build 1 câu gợi ý hành động từ 1 ĐOẠN xu hướng (kết quả
    detect_market_trend_segments()) — dùng ĐÚNG giờ BẮT ĐẦU đoạn (không phải
    giờ LTV cao/thấp nhất trong đoạn) để tính giờ NÊN hành động (đón đầu
    `lead_hours` tiếng, cùng tinh thần `_shift_hours_earlier()`/
    ACTION_LEAD_HOURS ở trên)."""
    duration = segment["end_hour"] - segment["start_hour"]
    action_hour = (segment["start_hour"] - lead_hours) % 24
    verb = "TĂNG" if segment["direction"] == "tang" else "GIẢM"
    pct = segment["pct_change"]
    pct_str = f"{pct:+.0f}%" if pct is not None else "?"
    local = format_local_hours([segment["start_hour"]], country)
    local_txt = f" (≈ {local} giờ địa phương {country})" if local else ""
    return (
        f"Xu hướng {verb} BẮT ĐẦU từ **{segment['start_hour']:02d}h**{local_txt} (kéo dài tới "
        f"{segment['end_hour']:02d}h, {duration} tiếng, đổi {pct_str}) — nên **{verb.lower()} "
        f"ngân sách/bid từ khoảng {action_hour:02d}h** (đón đầu {lead_hours} tiếng)."
    )


def build_market_suggestions_from_segments(
    patterns_df: pd.DataFrame, countries: list, min_segment_hours: int = MIN_SEGMENT_HOURS_FOR_MARKET_ACTION
) -> list:
    """THAY THẾ `build_market_suggestions()` (dựa trên top giờ riêng lẻ) bằng
    gợi ý dựa trên ĐOẠN xu hướng liên tục — theo đúng yêu cầu user ("chỉ khi
    bắt đầu một đợt tăng/giảm LTV DÀI thì mới suggest tăng/giảm budget").

    Với MỖI `country` trong `countries` (thường truyền `summary_df["Quốc
    gia"]` từ summarize_peak_and_low_hours() — đã lọc sẵn các nước đủ dữ
    liệu): tách đoạn bằng detect_market_trend_segments(), CHỈ giữ đoạn đạt
    tối thiểu `min_segment_hours` tiếng liên tục, rồi chọn đoạn có |% đổi|
    LỚN NHẤT trong số đó (đáng chú ý nhất) để build gợi ý. Nếu KHÔNG có đoạn
    nào đủ dài — trả về câu giải thích rõ lý do (KHÔNG suggest hành động cụ
    thể, tránh gợi ý sai dựa trên biến động ngắn/nhiễu)."""
    rows = []
    for country in countries:
        segments = detect_market_trend_segments(patterns_df, country)
        long_enough = [s for s in segments if (s["end_hour"] - s["start_hour"]) >= min_segment_hours]
        if not long_enough:
            rows.append({
                "Quốc gia": country,
                "Gợi ý": (
                    "Không có đợt tăng/giảm LTV nào đủ dài (≥"
                    f"{min_segment_hours} tiếng liên tục) để gợi ý hành động cụ "
                    "thể — LTV biến động ngắn/lẻ tẻ theo từng giờ, action theo "
                    "1-2 giờ đơn lẻ sẽ không đáng tin."
                ),
            })
            continue
        best = max(long_enough, key=lambda s: abs(s["pct_change"] or 0))
        rows.append({"Quốc gia": country, "Gợi ý": describe_market_segment_suggestion(best, country)})
    return rows
