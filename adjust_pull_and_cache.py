"""
Script chạy NỀN (được Windows Task Scheduler gọi mỗi ngày): kéo dữ liệu lõi từ
Adjust rồi LƯU vào SQLite (`adjust_data.db`), thay vì chỉ in ra màn hình như
`adjust_test.py`.

Mỗi lần chạy: lấy lại N ngày gần nhất (mặc định 7, xem DAYS_BACK_DEFAULT trong
adjust_client.py) và GHI ĐÈ (UPSERT) theo khóa app+day+campaign+country — nhờ vậy
số liệu các ngày gần đây tự "vá" dần khi Adjust có số mới/chính xác hơn.

Không in bảng đẹp ra màn hình — chỉ log ngắn gọn để xem trong Task Scheduler
history hoặc file log. Muốn xem bảng đẹp để đối chiếu tay, dùng `adjust_test.py`.
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

import adjust_client as ac

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adjust_data.db")

# Cột khóa (định danh duy nhất 1 dòng) — trùng đúng bộ dimension đang lấy.
KEY_COLS = ["app", "day", "campaign", "country"]
# Cột dữ liệu — đúng bộ metric đã chốt trong adjust_client.py (SUMMABLE_COLS +
# RATIO_COLS), giữ nguyên thứ tự để dễ đối chiếu với GHI_CHU_TIEN_DO.md.
VALUE_COLS = ac.SUMMABLE_COLS + ac.RATIO_COLS


def ensure_schema(conn: sqlite3.Connection) -> None:
    cols_sql = ",\n".join(f'"{c}" TEXT' for c in KEY_COLS) + ",\n" + ",\n".join(
        f'"{c}" REAL' for c in VALUE_COLS
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS adjust_daily (
            {cols_sql},
            fetched_at TEXT NOT NULL,
            PRIMARY KEY ({", ".join(f'"{c}"' for c in KEY_COLS)})
        )
        """
    )
    # Tự thêm cột mới nếu đổi/thêm metric sau này (VD ecpi_all thay network_ecpi) —
    # tránh phải xoá adjust_data.db mỗi lần đổi danh sách metric trong adjust_client.py.
    existing_cols = {row[1] for row in conn.execute('PRAGMA table_info("adjust_daily")')}
    for col in VALUE_COLS:
        if col not in existing_cols:
            conn.execute(f'ALTER TABLE adjust_daily ADD COLUMN "{col}" REAL')

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pull_log (
            pulled_at TEXT NOT NULL,
            date_range TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT
        )
        """
    )
    conn.commit()


def upsert_rows(conn: sqlite3.Connection, rows: list, fetched_at: str) -> int:
    placeholders = ", ".join(["?"] * (len(KEY_COLS) + len(VALUE_COLS) + 1))
    all_cols = KEY_COLS + VALUE_COLS + ["fetched_at"]
    update_clause = ", ".join(f'"{c}" = excluded."{c}"' for c in VALUE_COLS + ["fetched_at"])
    sql = f"""
        INSERT INTO adjust_daily ({", ".join(f'"{c}"' for c in all_cols)})
        VALUES ({placeholders})
        ON CONFLICT ({", ".join(f'"{c}"' for c in KEY_COLS)})
        DO UPDATE SET {update_clause}
    """

    count = 0
    for row in rows:
        values = [row.get(c) for c in KEY_COLS] + [row.get(c) for c in VALUE_COLS] + [fetched_at]
        conn.execute(sql, values)
        count += 1
    conn.commit()
    return count


def run() -> None:
    load_dotenv()
    api_token = os.getenv("ADJUST_API_TOKEN")
    app_tokens_raw = os.getenv("ADJUST_APP_TOKENS")

    fetched_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)

    if not api_token or not app_tokens_raw:
        msg = "Thiếu ADJUST_API_TOKEN hoặc ADJUST_APP_TOKENS trong .env"
        print(f"❌ {msg}")
        conn.execute(
            "INSERT INTO pull_log VALUES (?, ?, ?, ?, ?)",
            (fetched_at, "", 0, "error", msg),
        )
        conn.commit()
        conn.close()
        sys.exit(1)

    app_tokens = ac.parse_app_tokens(app_tokens_raw)
    date_range = ac.get_date_range()

    try:
        data = ac.fetch_detail(api_token, app_tokens, exit_on_error=False)
    except Exception as e:  # noqa: BLE001 — log lỗi rồi thoát, không để crash im lặng
        print(f"❌ Lỗi gọi Adjust API: {e}")
        conn.execute(
            "INSERT INTO pull_log VALUES (?, ?, ?, ?, ?)",
            (fetched_at, date_range, 0, "error", str(e)),
        )
        conn.commit()
        conn.close()
        sys.exit(1)

    warning_msg = ac.extract_warnings(data)  # vd: app_token sai bị Adjust âm thầm bỏ qua

    rows = data.get("rows") or []
    count = upsert_rows(conn, rows, fetched_at)
    conn.execute(
        "INSERT INTO pull_log VALUES (?, ?, ?, ?, ?)",
        (fetched_at, date_range, count, "ok" if not warning_msg else "warning", warning_msg),
    )
    conn.commit()
    conn.close()

    print(f"✅ Đã lưu {count} dòng vào {DB_PATH} (khoảng ngày {date_range}, lúc {fetched_at})")
    if warning_msg:
        print(f"⚠️  Adjust cảnh báo: {warning_msg}")


if __name__ == "__main__":
    run()
