"""
So sánh LTV (doanh thu ads ÷ installs) "cuối ngày" vs "N tiếng trước" (hoặc 1
giờ cụ thể trong ngày, VD 8h) TRONG 1 NGÀY CỤ THỂ — kéo TRỰC TIẾP dimension
"hour" của Adjust (adjust_client.fetch_hourly_for_date()/fetch_hourly_today()).

ĐỔI HẲN 23/09/2026 — BỎ CPI/ROAS THEO GIỜ, CHỈ CÒN LTV: đã kiểm chứng bằng số
thật (nhiều ngày, đối chiếu tổng theo giờ vs tổng theo ngày):
- `network_cost` (chi phí network) KHÔNG có grain theo giờ thật — Adjust dồn
  TOÀN BỘ chi phí của CẢ NGÀY vào ĐÚNG 1 GIỜ DUY NHẤT (thường là 00:00), 23
  giờ còn lại luôn là $0 — kể cả những ngày đã qua rất lâu, đã chốt hẳn. Vì
  vậy CPI (= chi phí ÷ installs) và ROAS D0 (= LTV ÷ CPI) tính theo giờ là VÔ
  NGHĨA ở BẤT KỲ khung so sánh nào (1 tiếng hay 24 tiếng đều vậy) — không có
  cách nào sửa được vì đây là giới hạn của chính dữ liệu Adjust trả về, xem
  GHI_CHU_TIEN_DO.md.
- `ad_revenue` (doanh thu quảng cáo) THÌ KHÁC — đến từ chính SDK Adjust cài
  trong app (ghi nhận thật theo thời gian, giống installs, KHÔNG phụ thuộc
  network bên ngoài) — đã kiểm chứng: mỗi giờ có giá trị THẬT khác nhau, cộng
  24 giờ khớp gần như tuyệt đối với tổng theo ngày (chỉ lệch do làm tròn 4 số
  thập phân của Adjust). Vì vậy LTV = ad_revenue ÷ installs tính theo giờ
  ĐÁNG TIN — module này giờ CHỈ còn tính LTV + installs.

⚠️ LTV ở đây là "doanh thu ads tích lũy đến hiện tại của user cài trong giờ
đó" — khác "LTV (ARPU D0)" dùng ở Tầng 1 Xét nghiệm (vốn tính qua
`roas_ad_d0 × network_cost`, giới hạn đúng ngày cài D0). Với NGÀY ĐÃ QUA khá
lâu, mọi giờ trong ngày đó đều đã "chín" gần như nhau (chênh nhau tối đa 23
tiếng so với hàng chục ngày đã trôi qua) nên so sánh giữa các giờ vẫn công
bằng — chỉ không nên so trực tiếp con số này với benchmark LTV D0 ở nơi khác.

CÁCH TÍNH: mỗi dòng Adjust trả về (dimension "hour") là số PHÁT SINH TRONG
giờ đó, KHÔNG PHẢI cộng dồn — build_cumulative_by_hour() tự cộng dồn theo
(app, campaign) rồi tính lại LTV từ số ĐÃ CỘNG DỒN.

ĐỔI 24/09/2026 — BỎ BỘ MỐC CỐ ĐỊNH (1/2/3/6 tiếng trước áp dụng chung cho MỌI
campaign), theo phản hồi user ("cứ lấy mốc cố định để so mọi camp là quá cứng
nhắc, có tự flex và phân tích riêng từng camp được không"). Giờ mỗi campaign
TỰ quét toàn bộ các giờ nó có dữ liệu để tìm ra cặp giờ cho LTV đổi nhiều
nhất — xem find_best_swing()/list_flagged_best_swing().
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

VN_TZ = timezone(timedelta(hours=7))


def _pct(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b - a) / a * 100


def build_cumulative_by_hour(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Input: df thô từ adjust_client.fetch_hourly_today()/fetch_hourly_for_date()
    (cột app, hour, campaign, installs, ad_revenue, ...). Output: thêm các
    cột CỘNG DỒN từ đầu ngày đến hết mỗi giờ: installs_cum, ad_revenue_cum,
    arpu (= LTV, suy ra từ số ĐÃ cộng dồn — KHÔNG lấy trung bình cộng qua
    nhiều giờ).

    Trả về NGUYÊN VẸN nếu df rỗng (VD vừa qua nửa đêm, chưa có install nào)
    — tránh KeyError do df rỗng không có cột nào để đọc."""
    if hourly_df is None or hourly_df.empty:
        return hourly_df
    df = hourly_df.copy()
    for col in ("installs", "ad_revenue"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df = df.sort_values("hour")
    grp = df.groupby(["app", "campaign"], group_keys=False)
    df["installs_cum"] = grp["installs"].cumsum()
    df["ad_revenue_cum"] = grp["ad_revenue"].cumsum()
    df["arpu"] = df["ad_revenue_cum"] / df["installs_cum"].replace(0, pd.NA)
    return df


def _compare_to_target(cum_df: pd.DataFrame, app: str, campaign: str, target_dt: datetime) -> dict | None:
    """Lõi dùng chung: so giờ MỚI NHẤT (đang chạy, hoặc cuối ngày nếu xem
    ngày đã qua) với giờ đã có dữ liệu GẦN `target_dt` nhất. Trả về None nếu
    campaign chưa có nổi 2 giờ dữ liệu khác nhau."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if len(hours_sorted) < 2:
        return None

    latest_hour = hours_sorted[-1]
    latest = g[g["hour"] == latest_hour].iloc[0]
    latest_dt = datetime.fromisoformat(latest_hour)

    earlier_hours = hours_sorted[:-1]
    baseline_hour = min(earlier_hours, key=lambda h: abs((datetime.fromisoformat(h) - target_dt).total_seconds()))
    baseline = g[g["hour"] == baseline_hour].iloc[0]
    actual_hours_gap = (latest_dt - datetime.fromisoformat(baseline_hour)).total_seconds() / 3600

    return {
        "baseline_ts": baseline_hour,
        "latest_ts": latest_hour,
        "baseline": baseline.to_dict(),
        "latest": latest.to_dict(),
        "actual_hours_gap": round(actual_hours_gap, 1),
        "arpu_pct_change": _pct(baseline["arpu"], latest["arpu"]),
    }


DEFAULT_MAX_GAP_HOURS = 6.0


def find_best_swing(
    cum_df: pd.DataFrame,
    app: str,
    campaign: str,
    min_installs: int = 0,
    max_gap_hours: float = DEFAULT_MAX_GAP_HOURS,
) -> dict | None:
    """THAY THẾ bộ mốc CỐ ĐỊNH (1/2/3/6 tiếng trước, áp dụng chung cho MỌI
    campaign) — đổi 24/09/2026 theo yêu cầu user ("mốc cố định quá cứng
    nhắc, có tự flex và phân tích riêng từng camp được không").

    Tự quét các giờ campaign này ĐÃ CÓ DỮ LIỆU trong ngày làm baseline (không
    giới hạn vào 1 bộ mốc giờ định sẵn), so mỗi giờ đó với giờ MỚI NHẤT (cuối
    ngày), rồi chọn ra cặp cho LTV đổi NHIỀU NHẤT (trị tuyệt đối). Nhờ vậy
    mỗi campaign tự "tìm" mốc so sánh khớp với chính nhịp biến động của nó —
    campaign nào chỉ biến động rõ giữa giờ 7 và giờ 12 vẫn bắt được, dù
    khoảng cách đó không nằm trong bộ mốc cố định nào.

    GIỚI HẠN `max_gap_hours` (mặc định 6 tiếng, THÊM 24/09/2026 — user chỉ ra
    so trong khoảng 18 tiếng "quá rộng, không mang nhiều ý nghĩa, cần chi
    tiết theo khung giờ hơn"): CHỈ xét baseline cách giờ mới nhất tối đa
    `max_gap_hours` tiếng — nếu quét KHÔNG giới hạn, thuật toán có thể chọn
    1 cặp cách nhau gần cả ngày (VD 18-20 tiếng) vì tình cờ % đổi lớn nhất,
    nhưng khoảng đó quá dài để dùng cho hành động BID/ngân sách cụ thể (LTV
    "đổi" qua gần cả ngày không nói lên khung giờ NÀO mới là vấn đề thật).
    Giới hạn này giữ được tinh thần "tự flex" (không ép về đúng 1/2/3/6 tiếng
    cố định) nhưng vẫn đảm bảo kết quả đủ CHI TIẾT/CỤ THỂ theo khung giờ.

    Bỏ qua baseline nào có installs_cum dưới `min_installs` — so với 1 giờ
    đầu ngày gần như trống (0-1 install) ra % đổi cực đoan là nhiễu do mẫu
    quá nhỏ, không phải biến động thật."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if len(hours_sorted) < 2:
        return None

    latest_hour = hours_sorted[-1]
    latest = g[g["hour"] == latest_hour].iloc[0]
    latest_dt = datetime.fromisoformat(latest_hour)

    best = None
    for h in hours_sorted[:-1]:
        gap = (latest_dt - datetime.fromisoformat(h)).total_seconds() / 3600
        if max_gap_hours and gap > max_gap_hours:
            continue
        baseline = g[g["hour"] == h].iloc[0]
        if min_installs and (baseline.get("installs_cum") or 0) < min_installs:
            continue
        pct = _pct(baseline["arpu"], latest["arpu"])
        if pct is None:
            continue
        if best is None or abs(pct) > abs(best["arpu_pct_change"]):
            best = {
                "baseline_ts": h,
                "latest_ts": latest_hour,
                "baseline": baseline.to_dict(),
                "latest": latest.to_dict(),
                "actual_hours_gap": round(gap, 1),
                "arpu_pct_change": pct,
            }
    return best


def compare_since_hour(cum_df: pd.DataFrame, app: str, campaign: str, baseline_hour_of_day: int) -> dict | None:
    """So giờ MỚI NHẤT với 1 GIỜ CỤ THỂ trong ngày (VD baseline_hour_of_day=8
    → so với ~8h sáng). Tự chọn giờ ĐÃ CÓ DỮ LIỆU gần `baseline_hour_of_day`
    nhất (không nhất thiết đúng tuyệt đối vì Adjust có thể thiếu 1 vài giờ)."""
    g = cum_df[(cum_df["app"] == app) & (cum_df["campaign"] == campaign)]
    hours_sorted = sorted(g["hour"].unique())
    if not hours_sorted:
        return None
    latest_dt = datetime.fromisoformat(hours_sorted[-1])
    target_dt = latest_dt.replace(hour=int(baseline_hour_of_day), minute=0, second=0, microsecond=0)
    return _compare_to_target(cum_df, app, campaign, target_dt)


def _flag_entry(app: str, campaign: str, cmp: dict, threshold_pct: float, min_installs: int, target_label) -> dict | None:
    """ĐIỀU KIỆN GẮN CỜ: LTV đổi (TĂNG hoặc GIẢM) vượt threshold_pct% — CẢ 2
    CHIỀU (đổi 24/09/2026, theo yêu cầu user: muốn biết cả lúc LTV tăng để
    gợi ý hành động tương ứng ở Xét nghiệm — VD tăng ngân sách khi LTV tăng,
    không chỉ cảnh báo lúc giảm). Thêm field `direction` ("tang"/"giam") để
    nơi gọi (app.py, campaign_doctor.py) biết chiều nào mà gợi ý đúng hành
    động."""
    if cmp is None:
        return None
    if min_installs and (cmp["latest"].get("installs_cum") or 0) < min_installs:
        return None
    pct = cmp["arpu_pct_change"]
    if pct is None or abs(pct) < threshold_pct:
        return None
    direction = "giam" if pct < 0 else "tang"
    return {
        "app": app, "campaign": campaign, "target": target_label,
        "arpu_bad": direction == "giam",  # giữ tên cũ để tương thích ngược
        "direction": direction,
        **cmp,
    }


def list_flagged_best_swing(
    cum_df: pd.DataFrame,
    threshold_pct: float = 20.0,
    min_installs: int = 0,
    max_gap_hours: float = DEFAULT_MAX_GAP_HOURS,
) -> list:
    """CẢNH BÁO TRONG NGÀY — BẢN "TỰ FLEX" (thay hẳn bộ mốc cố định 1/2/3/6
    tiếng cũ, xem docstring find_best_swing()). Mỗi campaign tự quét giờ nó
    có dữ liệu (trong tối đa `max_gap_hours` tiếng trước giờ mới nhất) để
    tìm cặp giờ cho LTV đổi (tăng HOẶC giảm) nhiều nhất, gắn cờ nếu vượt
    threshold_pct%."""
    if cum_df is None or cum_df.empty:
        return []
    flagged = []
    for (app, campaign), _ in cum_df.groupby(["app", "campaign"]):
        cmp = find_best_swing(cum_df, app, campaign, min_installs, max_gap_hours)
        entry = _flag_entry(app, campaign, cmp, threshold_pct, min_installs, "auto")
        if entry:
            flagged.append(entry)
    return sorted(flagged, key=lambda f: f.get("arpu_pct_change") or 0)


def list_flagged_since_hour(
    cum_df: pd.DataFrame,
    baseline_hour_of_day: int = 8,
    threshold_pct: float = 20.0,
    min_installs: int = 0,
) -> list:
    """So với 1 GIỜ CỤ THỂ user tự chọn trong ngày (mặc định 8h) — cả 2 chiều
    tăng/giảm, xem docstring _flag_entry()."""
    if cum_df is None or cum_df.empty:
        return []
    flagged = []
    for (app, campaign), _ in cum_df.groupby(["app", "campaign"]):
        cmp = compare_since_hour(cum_df, app, campaign, baseline_hour_of_day)
        entry = _flag_entry(app, campaign, cmp, threshold_pct, min_installs, baseline_hour_of_day)
        if entry:
            flagged.append(entry)
    return sorted(flagged, key=lambda f: f.get("arpu_pct_change") or 0)


DEFAULT_TREND_MIN_INSTALLS_PER_HOUR = 5
DEFAULT_TREND_MIN_STEP_PCT = 10.0


def _build_segment(hourly_ltv_df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> dict:
    start_row = hourly_ltv_df.loc[start_idx]
    end_row = hourly_ltv_df.loc[end_idx]
    return {
        "direction": direction,
        "start_ts": start_row["hour"],
        "end_ts": end_row["hour"],
        "start_ltv": start_row["ltv"],
        "end_ltv": end_row["ltv"],
        "pct_change": _pct(start_row["ltv"], end_row["ltv"]),
    }


DEFAULT_TREND_MIN_TOTAL_INSTALLS = 50


def detect_trend_segments(
    hourly_df: pd.DataFrame,
    app: str,
    campaign: str,
    min_installs_per_hour: int = DEFAULT_TREND_MIN_INSTALLS_PER_HOUR,
    min_step_pct: float = DEFAULT_TREND_MIN_STEP_PCT,
    min_total_installs: int = DEFAULT_TREND_MIN_TOTAL_INSTALLS,
) -> list:
    """THÊM 29/09/2026 (theo yêu cầu user — chỉ ra `find_best_swing()` LUÔN
    neo 1 đầu vào giờ MỚI NHẤT trong ngày (VD 23h), nên "bị động, cho ít ý
    nghĩa": nếu LTV giảm 05h-12h rồi hồi lại 13h-22h rồi giảm tiếp lúc 23h,
    thuật toán chỉ bắt được đoạn CUỐI (so với 23h), bỏ sót đoạn giảm-rồi-hồi
    ở giữa ngày. Hàm này KHÔNG neo vào giờ nào cả — quét TOÀN BỘ 24 giờ để tự
    tách ra các ĐOẠN xu hướng liên tục (tăng dần / giảm dần), trả về ĐÚNG lúc
    nào bắt đầu giảm, lúc nào bắt đầu hồi (hoặc giảm tiếp) trong ngày.

    QUAN TRỌNG — dùng LTV THEO GIỜ KHÔNG CỘNG DỒN (marginal, phát sinh TRONG
    giờ đó) — KHÁC với `cum_df`/"arpu" dùng ở find_best_swing() (cộng dồn từ
    đầu ngày, càng về cuối ngày càng bị "trung bình hoá" bởi các giờ trước
    đó, làm mờ đúng lúc xu hướng đổi chiều). Vì vậy hàm này nhận `hourly_df`
    THÔ (chưa cộng dồn, cùng input đưa vào build_cumulative_by_hour()), tự
    gộp lại theo giờ ở đây. HỆ QUẢ: cột "Chiều" (dựa trên số CỘNG DỒN) và
    kết quả hàm này (dựa trên số THEO GIỜ) có thể "nhìn có vẻ trái chiều nhau"
    ở cùng 1 campaign (VD "Chiều" báo Giảm nhưng có 1 đoạn ở đây báo Tăng) —
    KHÔNG PHẢI lỗi, mà là 2 CÁCH ĐO khác nhau đang trả lời 2 câu hỏi khác
    nhau ("từ lúc X tới cuối ngày, xu hướng chung là gì" vs "trong ngày, lúc
    nào tăng lúc nào giảm cụ thể") — ĐÃ SỬA 29/09/2026 (user chỉ ra hiện
    tượng này + phản hồi kết quả "trông thiếu tin cậy"): siết chặt 2 điều
    kiện dưới đây để giảm hẳn khả năng đây là NHIỄU (installs/giờ quá ít)
    thay vì tín hiệu thật.

    `min_installs_per_hour`: bỏ qua giờ có quá ít install (mẫu quá nhỏ, LTV
    dễ nhảy vọt vô nghĩa — cùng tinh thần các nơi khác trong project).

    `min_total_installs` (MỚI 29/09/2026): nếu TỔNG install của các giờ ĐỦ
    điều kiện (sau khi lọc `min_installs_per_hour`) dưới ngưỡng này, TRẢ VỀ
    RỖNG thay vì cố tách đoạn — campaign quá ít dữ liệu (VD chỉ 41 install
    CẢ NGÀY) thì bất kỳ đoạn nào tách ra cũng chỉ là nhiễu ngẫu nhiên từ vài
    install lẻ tẻ, không đáng tin để gọi là "xu hướng".

    KHÔNG BẮC CẦU qua giờ bị lọc mất (MỚI 29/09/2026 — user chỉ ra đoạn dài
    kiểu "12h→18h" trông như tăng liên tục suốt 6 tiếng nhưng thật ra nhiều
    giờ ở giữa (13h-17h) không đủ install nên bị lọc mất, KHÔNG BIẾT thật sự
    chuyện gì xảy ra trong khoảng đó): nếu 2 giờ ĐỦ điều kiện liền nhau trong
    `df` KHÔNG PHẢI 2 giờ liên tiếp thật (có giờ bị lọc ở giữa), NGẮT thành 2
    đoạn riêng tại đó thay vì gộp thành 1 đoạn dài bắc cầu qua khoảng trống.

    `min_step_pct`: bước giữa 2 giờ LIỀN NHAU THẬT phải đổi ít nhất % này mới
    tính là "đổi hướng" — bước nhỏ hơn coi là nhiễu/đi ngang, KHÔNG cắt đoạn
    (vẫn tính là tiếp tục xu hướng đang có, tránh tách vụn thành quá nhiều
    đoạn ngắn vô nghĩa từ nhiễu)."""
    if hourly_df is None or hourly_df.empty:
        return []
    df = hourly_df[(hourly_df["app"] == app) & (hourly_df["campaign"] == campaign)].copy()
    if df.empty:
        return []
    for col in ("installs", "ad_revenue"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df = df.groupby("hour")[["installs", "ad_revenue"]].sum().reset_index().sort_values("hour")
    df = df[df["installs"] >= min_installs_per_hour]
    if len(df) < 2 or df["installs"].sum() < min_total_installs:
        return []
    df["ltv"] = df["ad_revenue"] / df["installs"].replace(0, pd.NA)
    df = df.dropna(subset=["ltv"]).reset_index(drop=True)
    if len(df) < 2:
        return []
    df["hour_dt"] = df["hour"].apply(datetime.fromisoformat)

    segments = []
    current_dir = None
    seg_start_idx = 0
    for i in range(1, len(df)):
        gap_hours = (df.loc[i, "hour_dt"] - df.loc[i - 1, "hour_dt"]).total_seconds() / 3600
        if gap_hours > 1.0:
            # Có giờ bị lọc mất ở giữa (không liên tiếp thật) — KHÔNG bắc
            # cầu qua khoảng trống này, đóng đoạn đang có (nếu có) rồi bắt
            # đầu lại từ đây, coi như chưa biết gì về đoạn trước đó.
            if current_dir is not None:
                segments.append(_build_segment(df, seg_start_idx, i - 1, current_dir))
            current_dir = None
            seg_start_idx = i
            continue

        pct = _pct(df.loc[i - 1, "ltv"], df.loc[i, "ltv"])
        if pct is None:
            continue
        if pct >= min_step_pct:
            step_dir = "tang"
        elif pct <= -min_step_pct:
            step_dir = "giam"
        else:
            step_dir = None  # bước nhỏ/đi ngang — coi là nhiễu, không cắt đoạn

        if step_dir is None:
            continue
        if current_dir is None:
            current_dir = step_dir
            seg_start_idx = i - 1
        elif step_dir != current_dir:
            segments.append(_build_segment(df, seg_start_idx, i - 1, current_dir))
            current_dir = step_dir
            seg_start_idx = i - 1

    if current_dir is not None:
        segments.append(_build_segment(df, seg_start_idx, len(df) - 1, current_dir))

    return segments


DEFAULT_TREND_MAX_SEGMENTS_SHOWN = 3


def format_trend_segments(segments: list, max_segments_shown: int = DEFAULT_TREND_MAX_SEGMENTS_SHOWN) -> str:
    """Rút gọn kết quả detect_trend_segments() thành 1 chuỗi ngắn để nhét
    THẲNG vào 1 cột của bảng cảnh báo (THÊM 29/09/2026 — user chỉ ra không
    cần tách riêng 1 mục/dropdown bên dưới, "không thể trình bày luôn tại
    bảng này à" — gộp thẳng vào bảng đang có luôn, không thêm UI mới).

    SỬA 29/09/2026 (user chê kết quả "nhìn hơi thiếu chuyên nghiệp" khi liệt
    kê quá nhiều đoạn vụn trong 1 ô): nếu có nhiều hơn `max_segments_shown`
    đoạn, CHỈ hiện `max_segments_shown` đoạn có % thay đổi LỚN NHẤT (đáng chú
    ý nhất), vẫn giữ ĐÚNG thứ tự thời gian giữa các đoạn được chọn, kèm
    "+N đoạn khác" ở cuối nếu có đoạn bị lược bớt — gọn hơn nhiều so với liệt
    kê hết mọi đoạn nhỏ lẻ.

    VD: "05h→12h ↓33% · 12h→22h ↑129% · 22h→23h ↓84%"."""
    if not segments:
        return ""
    shown = segments
    hidden_count = 0
    if len(segments) > max_segments_shown:
        by_magnitude = sorted(segments, key=lambda s: abs(s["pct_change"] or 0), reverse=True)
        keep_ts = {(s["start_ts"], s["end_ts"]) for s in by_magnitude[:max_segments_shown]}
        shown = [s for s in segments if (s["start_ts"], s["end_ts"]) in keep_ts]
        hidden_count = len(segments) - len(shown)

    parts = []
    for seg in shown:
        arrow = "↑" if seg["direction"] == "tang" else "↓"
        start_h = seg["start_ts"][11:13]
        end_h = seg["end_ts"][11:13]
        pct = seg["pct_change"]
        pct_str = f"{abs(pct):.0f}%" if pct is not None else "?"
        parts.append(f"{start_h}h→{end_h}h {arrow}{pct_str}")
    result = " · ".join(parts)
    if hidden_count:
        result += f" · +{hidden_count} đoạn khác"
    return result
