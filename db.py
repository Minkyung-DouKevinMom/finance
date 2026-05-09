"""
SQLite DB 초기화 및 연결 관리.
- finance.db 파일이 없으면 스키마를 만들고 기본 마스터 데이터를 시드한다.
- 모든 금액 단위는 '만원'으로 통일.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "finance.db"


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 소유자 (본인 / 배우자 / 공동 등)
CREATE TABLE IF NOT EXISTS owner (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE
);

-- 자산 대분류 (금융자산 / 부동산 / 실물자산)
CREATE TABLE IF NOT EXISTS category (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

-- 과목 (보험·연금 / 예금·대출 / 주식·펀드 / 부동산 등)
CREATE TABLE IF NOT EXISTS subcategory (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id  INTEGER NOT NULL REFERENCES category(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(category_id, name)
);

-- 개별 상품(계좌) 마스터
CREATE TABLE IF NOT EXISTS account (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    subcategory_id    INTEGER NOT NULL REFERENCES subcategory(id),
    owner_id          INTEGER NOT NULL REFERENCES owner(id),
    name              TEXT    NOT NULL,           -- 표시명 (예: 미래에셋연금)
    product_name      TEXT,                       -- 상품 정식명
    start_date        TEXT,                       -- 가입/시작일 (YYYY-MM-DD)
    maturity_date     TEXT,                       -- 만기일
    payout_start_date TEXT,                       -- 연금 개시일 (YYYY-MM-DD)
    monthly_premium   REAL,                       -- 누적 납입(또는 월 납입) - 만원
    expected_payout   REAL,                       -- 예상 수령액(연금:월수령, 일시불:총액) - 만원
    payout_type       TEXT DEFAULT 'monthly',     -- 'monthly' | 'lumpsum'
    status            TEXT,                       -- 납입중/납입완료/해지 등
    memo              TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1, -- 0이면 더 이상 추적 안 함
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_account_sub ON account(subcategory_id);
CREATE INDEX IF NOT EXISTS idx_account_owner ON account(owner_id);

-- 월별 스냅샷 시점
CREATE TABLE IF NOT EXISTS snapshot (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,           -- YYYY-MM-01 형태로 저장
    memo          TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 시점별 잔액
CREATE TABLE IF NOT EXISTS balance (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    account_id   INTEGER NOT NULL REFERENCES account(id),
    amount       REAL NOT NULL DEFAULT 0,         -- 만원
    UNIQUE(snapshot_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_balance_snap ON balance(snapshot_id);

-- 미래 계획 (노후/자녀 등)
CREATE TABLE IF NOT EXISTS plan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_year     INTEGER,                  -- 예상 연도
    category      TEXT,                     -- 부동산/주식/예금/연금 등
    item          TEXT NOT NULL,            -- 항목명
    target_amount REAL,                     -- 만원
    age           INTEGER,
    memo          TEXT
);
"""


# 엑셀에 등장하던 기본 분류를 미리 시드
SEED_CATEGORIES = [
    ("금융자산", 1),
    ("부동산", 2),
    ("실물자산", 3),
]
SEED_SUBCATEGORIES = [
    ("금융자산", "보험·연금", 1),
    ("금융자산", "예금·대출", 2),
    ("금융자산", "주식·펀드", 3),
    ("부동산",   "부동산",     1),
    ("실물자산", "실물자산",   1),
]
SEED_OWNERS = ["본인", "배우자", "공동"]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """
    스키마 생성 + 기본 마스터 시드.
    시드는 최초 1회만 실행 (DB 내 seeded 플래그로 판단).
    이후 앱 재시작 시에는 삭제한 항목이 되살아나지 않는다.
    """
    with get_conn() as conn:
        # 스키마 생성
        conn.executescript(SCHEMA_SQL)

        # 시드 완료 여부를 저장하는 설정 테이블 (없으면 생성)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        already_seeded = conn.execute(
            "SELECT value FROM _app_settings WHERE key = 'seeded'"
        ).fetchone()

        if already_seeded:
            return  # 이미 시드 완료 → 아무것도 하지 않음

        # ── 최초 1회만 실행 ──────────────────────────────
        # 소유자 시드
        for name in SEED_OWNERS:
            conn.execute(
                "INSERT OR IGNORE INTO owner(name) VALUES (?)", (name,)
            )

        # 카테고리 시드
        for name, order in SEED_CATEGORIES:
            conn.execute(
                "INSERT OR IGNORE INTO category(name, sort_order) VALUES (?, ?)",
                (name, order),
            )

        # 서브카테고리 시드
        for cat_name, sub_name, order in SEED_SUBCATEGORIES:
            cat = conn.execute(
                "SELECT id FROM category WHERE name=?", (cat_name,)
            ).fetchone()
            if cat:
                conn.execute(
                    """INSERT OR IGNORE INTO subcategory(category_id, name, sort_order)
                       VALUES (?, ?, ?)""",
                    (cat["id"], sub_name, order),
                )

        # 시드 완료 플래그 저장
        conn.execute(
            "INSERT OR REPLACE INTO _app_settings(key, value) VALUES ('seeded', '1')"
        )


if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
