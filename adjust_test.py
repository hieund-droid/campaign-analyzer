"""
Script kéo "dữ liệu lõi" từ Adjust Report Service API cho NHIỀU app cùng lúc:
installs, chi phí, CPI (network eCPI), doanh thu ads, ROAS D0/D7/D30, retention D1/D7,
theo app + ngày + campaign + country. In ra bảng để đối chiếu với Datascape trong Adjust
(đối chiếu từng app một).

Đây là script XEM TAY (in ra màn hình) — phần lưu cache tự động chạy nền nằm ở
`adjust_pull_and_cache.py`. Cả 2 dùng chung cấu hình ở `adjust_client.py`.

Cách chạy: xem hướng dẫn cuối file, hoặc README.md đi kèm.
"""

import os
import sys

from dotenv import load_dotenv

import adjust_client as ac

# Windows console mặc định dùng codepage cp1252, không hiển thị được emoji/tiếng Việt
# có dấu → ép stdout/stderr sang UTF-8 để in không bị lỗi.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import pandas as pd
except ImportError:
    pd = None


def print_detail_table(data: dict) -> None:
    rows = data.get("rows") if isinstance(data, dict) else None

    if not rows:
        print("\n⚠️  Không có dữ liệu (rows rỗng). Kiểm tra lại app_token hoặc khoảng ngày.")
        print("Raw response:")
        print(data)
        return

    if pd is not None:
        df = pd.DataFrame(rows)
        for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # ARPU_D0/D7/D30 của TỪNG DÒNG (chỉ đúng cho đúng dòng đó — KHÔNG cộng dồn
        # cột này qua nhiều dòng, xem giải thích ở print_app_totals_table). ARPU
        # không có metric riêng trên Adjust (đã test trực tiếp: arpu, arpu_ad,
        # arpu_d0, cohort_ad_revenue_d0... đều "Unsupported metric") — tự suy ra từ
        # ROAS × network_cost ÷ installs. KHÔNG được dùng network_ecpi ở đây vì mẫu
        # số của network_ecpi là installs do network báo cáo, khác cột "installs".
        for label in ("d0", "d7", "d30"):
            roas_col = f"roas_ad_{label}"
            if roas_col in df.columns and "network_cost" in df.columns and "installs" in df.columns:
                df[f"arpu_{label}"] = df[roas_col] * df["network_cost"] / df["installs"]

        preferred_cols = [
            "app",
            "day",
            "campaign",
            "country",
            "installs",
            "network_cost",
            "network_ecpi",
            "ad_revenue",
            "roas_ad_d0",
            "arpu_d0",
            "roas_ad_d7",
            "arpu_d7",
            "roas_ad_d30",
            "arpu_d30",
            "retention_rate_d1",
            "retention_rate_d7",
        ]
        cols = [c for c in preferred_cols if c in df.columns] + [
            c for c in df.columns if c not in preferred_cols
        ]
        df = df[cols]

        print("\n=== Kết quả chi tiết (theo app + day + campaign + country) ===\n")
        print(df.to_string(index=False))

        # Cảnh báo nếu network_cost trống toàn bộ → đo lường chi phí chưa bật
        if "network_cost" in df.columns:
            non_empty = df["network_cost"].notna()
            if not non_empty.any():
                print(
                    "\n⚠️  CẢNH BÁO: cột network_cost trống toàn bộ (mọi app).\n"
                    "   → Đo lường chi phí (cost tracking) trong Adjust có thể CHƯA được bật.\n"
                    "   → Phải bật trước khi đi tiếp (xem README / brief, mục 'Đối chiếu')."
                )
            elif "app" in df.columns:
                per_app_missing = df.groupby("app")["network_cost"].apply(lambda s: s.notna().sum() == 0)
                missing_apps = per_app_missing[per_app_missing].index.tolist()
                if missing_apps:
                    print(
                        f"\n⚠️  App(s) bị trống network_cost hoàn toàn: {missing_apps}\n"
                        "   → Có thể đo lường chi phí chưa bật riêng cho (các) app này."
                    )
    else:
        print("\n(Không có pandas, in dạng raw JSON rows)\n")
        for row in rows:
            print(row)


def print_app_totals_table(data: dict) -> None:
    """In bảng tổng theo từng app — lấy TRỰC TIẾP từ Adjust (dimensions='app'),
    không tự cộng dồn từ bảng chi tiết, nên CPI/ROAS/ARPU/retention đều là số đúng
    Adjust tự tính, dùng để đối chiếu Datascape.
    """
    rows = data.get("rows") if isinstance(data, dict) else None
    if not rows:
        print("\n⚠️  Không lấy được tổng theo app (rows rỗng).")
        return

    if pd is not None:
        df = pd.DataFrame(rows)
        for col in ac.SUMMABLE_COLS + ac.RATIO_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        for label in ("d0", "d7", "d30"):
            roas_col = f"roas_ad_{label}"
            if roas_col in df.columns and "network_cost" in df.columns and "installs" in df.columns:
                df[f"arpu_{label}"] = df[roas_col] * df["network_cost"] / df["installs"]

        cols = [c for c in df.columns if c != "app"]
        df = df.set_index("app")[cols]

        print("\n=== Tổng theo từng app (lấy trực tiếp từ Adjust, để đối chiếu Datascape) ===\n")
        print(df.to_string())
        print(
            "\n(arpu_d0/d7/d30 = roas_ad_dN × network_cost ÷ installs, tính trên đúng "
            "1 dòng tổng của app — không qua bước cộng dồn nào nên không có sai số "
            "làm tròn tích lũy như bảng chi tiết.)"
        )
    else:
        for row in rows:
            print(row)


def main():
    load_dotenv()  # đọc file .env

    api_token = os.getenv("ADJUST_API_TOKEN")
    app_tokens_raw = os.getenv("ADJUST_APP_TOKENS")

    missing = []
    if not api_token:
        missing.append("ADJUST_API_TOKEN")
    if not app_tokens_raw:
        missing.append("ADJUST_APP_TOKENS")

    if missing:
        print(f"❌ Thiếu biến môi trường: {', '.join(missing)}")
        print("→ Mở file .env (copy từ .env.example) và điền giá trị thật vào.")
        sys.exit(1)

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    if not app_tokens:
        print("❌ ADJUST_APP_TOKENS đang rỗng sau khi tách dấu phẩy. Kiểm tra lại .env.")
        sys.exit(1)

    date_range = ac.get_date_range()
    print(f"Đang lấy dữ liệu Adjust cho {len(app_tokens)} app: {app_tokens}")
    print(f"Khoảng ngày: {date_range} ...")

    detail_data = ac.fetch_detail(api_token, app_tokens)
    warning_msg = ac.extract_warnings(detail_data)
    if warning_msg:
        print(f"\n⚠️  Adjust cảnh báo: {warning_msg}")
    print_detail_table(detail_data)

    app_totals_data = ac.fetch_app_totals(api_token, app_tokens)
    print_app_totals_table(app_totals_data)


if __name__ == "__main__":
    main()
