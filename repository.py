"""
DB CRUD 헬퍼.
Streamlit 페이지에서 직접 SQL을 쓰지 않고 이 모듈을 통해 데이터에 접근한다.
"""

from datetime import date
import pandas as pd
from db import get_conn


# ----------------------------- 마스터 ---------------------------------------

def list_owners():
    with get_conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM owner ORDER BY id")]


def list_categories():
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM category ORDER BY sort_order, id")]


def list_subcategories(category_id=None):
    sql = """SELECT s.*, c.name AS category_name
             FROM subcategory s JOIN category c ON c.id = s.category_id"""
    args = ()
    if category_id is not None:
        sql += " WHERE s.category_id = ?"
        args = (category_id,)
    sql += " ORDER BY c.sort_order, s.sort_order, s.id"
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def add_owner(name):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO owner(name) VALUES (?)", (name,))


def add_category(name, sort_order=99):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO category(name, sort_order) VALUES (?, ?)",
                  (name, sort_order))


def add_subcategory(category_id, name, sort_order=99):
    with get_conn() as c:
        c.execute("""INSERT OR IGNORE INTO subcategory(category_id, name, sort_order)
                     VALUES (?, ?, ?)""", (category_id, name, sort_order))


# ----------------------------- 계좌(상품) -----------------------------------

def list_accounts(active_only=True, subcategory_id=None, owner_id=None):
    sql = """
    SELECT a.*,
           s.name AS subcategory_name,
           c.id   AS category_id,
           c.name AS category_name,
           o.name AS owner_name
    FROM account a
    JOIN subcategory s ON s.id = a.subcategory_id
    JOIN category c    ON c.id = s.category_id
    JOIN owner o       ON o.id = a.owner_id
    WHERE 1=1
    """
    args = []
    if active_only:
        sql += " AND a.is_active = 1"
    if subcategory_id:
        sql += " AND a.subcategory_id = ?"
        args.append(subcategory_id)
    if owner_id:
        sql += " AND a.owner_id = ?"
        args.append(owner_id)
    sql += " ORDER BY c.sort_order, s.sort_order, a.id"
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def get_account(account_id):
    with get_conn() as c:
        r = c.execute("SELECT * FROM account WHERE id = ?", (account_id,)).fetchone()
        return dict(r) if r else None


def upsert_account(account_id=None, **fields):
    """
    fields: subcategory_id, owner_id, name, product_name, start_date, maturity_date,
            payout_start_date, monthly_premium, expected_payout, payout_type,
            status, memo, is_active
    """
    cols = ["subcategory_id", "owner_id", "name", "product_name",
            "start_date", "maturity_date", "payout_start_date",
            "monthly_premium", "expected_payout", "payout_type",
            "status", "memo", "is_active"]
    values = [fields.get(c) for c in cols]

    with get_conn() as c:
        if account_id:
            set_clause = ", ".join(f"{col} = ?" for col in cols)
            c.execute(f"UPDATE account SET {set_clause} WHERE id = ?",
                      values + [account_id])
            return account_id
        cur = c.execute(
            f"INSERT INTO account ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
            values,
        )
        return cur.lastrowid


def delete_account(account_id):
    """잔액 기록이 있으면 삭제 대신 비활성화."""
    with get_conn() as c:
        has_balance = c.execute(
            "SELECT 1 FROM balance WHERE account_id = ? LIMIT 1", (account_id,)
        ).fetchone()
        if has_balance:
            c.execute("UPDATE account SET is_active = 0 WHERE id = ?", (account_id,))
            return "deactivated"
        c.execute("DELETE FROM account WHERE id = ?", (account_id,))
        return "deleted"


# ----------------------------- 스냅샷 ---------------------------------------

def list_snapshots():
    with get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM snapshot ORDER BY snapshot_date DESC")]


def get_or_create_snapshot(snapshot_date, memo=None):
    """snapshot_date: 'YYYY-MM-01' 형식의 문자열."""
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM snapshot WHERE snapshot_date = ?", (snapshot_date,)
        ).fetchone()
        if row:
            return dict(row)
        cur = c.execute(
            "INSERT INTO snapshot(snapshot_date, memo) VALUES (?, ?)",
            (snapshot_date, memo),
        )
        return {"id": cur.lastrowid, "snapshot_date": snapshot_date, "memo": memo}


def delete_balances(snapshot_id, account_ids):
    """특정 스냅샷에서 선택한 계좌들의 잔액 기록만 삭제."""
    with get_conn() as c:
        for aid in account_ids:
            c.execute(
                "DELETE FROM balance WHERE snapshot_id = ? AND account_id = ?",
                (snapshot_id, aid),
            )


def delete_snapshot(snapshot_id):
    with get_conn() as c:
        c.execute("DELETE FROM snapshot WHERE id = ?", (snapshot_id,))


# ----------------------------- 잔액 -----------------------------------------

def get_balances_for_snapshot(snapshot_id):
    """
    스냅샷에 해당하는 모든 활성 계좌 + 잔액(없으면 0)을 반환.
    잔액 입력 화면에서 그대로 사용.
    """
    sql = """
    SELECT a.id AS account_id,
           c.name AS category_name,
           s.name AS subcategory_name,
           o.name AS owner_name,
           a.name AS account_name,
           a.product_name,
           a.payout_start_date,
           a.status,
           COALESCE(b.amount, 0) AS amount,
           c.sort_order AS c_order,
           s.sort_order AS s_order
    FROM account a
    JOIN subcategory s ON s.id = a.subcategory_id
    JOIN category c    ON c.id = s.category_id
    JOIN owner o       ON o.id = a.owner_id
    LEFT JOIN balance b ON b.account_id = a.id AND b.snapshot_id = ?
    WHERE a.is_active = 1
    ORDER BY c.sort_order, s.sort_order, a.id
    """
    with get_conn() as c:
        rows = c.execute(sql, (snapshot_id,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def save_balances(snapshot_id, balances):
    """balances: list of {account_id, amount}"""
    with get_conn() as c:
        for b in balances:
            c.execute("""
                INSERT INTO balance(snapshot_id, account_id, amount)
                VALUES (?, ?, ?)
                ON CONFLICT(snapshot_id, account_id)
                DO UPDATE SET amount = excluded.amount
            """, (snapshot_id, b["account_id"], b["amount"]))


def snapshot_summary(snapshot_id):
    """대시보드용: 카테고리/서브카테고리별 합계."""
    sql = """
    SELECT c.name AS category, s.name AS subcategory,
           SUM(b.amount) AS total
    FROM balance b
    JOIN account a     ON a.id = b.account_id
    JOIN subcategory s ON s.id = a.subcategory_id
    JOIN category c    ON c.id = s.category_id
    WHERE b.snapshot_id = ?
    GROUP BY c.id, s.id
    ORDER BY c.sort_order, s.sort_order
    """
    with get_conn() as c:
        return pd.DataFrame([dict(r) for r in c.execute(sql, (snapshot_id,))])


def time_series_total():
    """자산 추이 그래프용: 시점별 카테고리 합계."""
    sql = """
    SELECT sn.snapshot_date AS date,
           c.name AS category,
           SUM(b.amount) AS total
    FROM balance b
    JOIN snapshot sn   ON sn.id = b.snapshot_id
    JOIN account a     ON a.id = b.account_id
    JOIN subcategory s ON s.id = a.subcategory_id
    JOIN category c    ON c.id = s.category_id
    GROUP BY sn.snapshot_date, c.id
    ORDER BY sn.snapshot_date
    """
    with get_conn() as c:
        return pd.DataFrame([dict(r) for r in c.execute(sql)])


# ----------------------------- 계획 -----------------------------------------

def list_plans():
    with get_conn() as c:
        return pd.DataFrame([dict(r) for r in c.execute(
            "SELECT * FROM plan ORDER BY plan_year, id")])


def upsert_plan(plan_id=None, **fields):
    cols = ["plan_year", "category", "item", "target_amount", "age", "memo"]
    vals = [fields.get(c) for c in cols]
    with get_conn() as c:
        if plan_id:
            set_clause = ", ".join(f"{col} = ?" for col in cols)
            c.execute(f"UPDATE plan SET {set_clause} WHERE id = ?",
                      vals + [plan_id])
            return plan_id
        cur = c.execute(
            f"INSERT INTO plan({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
            vals,
        )
        return cur.lastrowid


def delete_plan(plan_id):
    with get_conn() as c:
        c.execute("DELETE FROM plan WHERE id = ?", (plan_id,))
