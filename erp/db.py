# =========================================================
#  DB 연결 — SQLite 파일 하나에 17개 테이블을 담는다
# =========================================================

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "erp.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect():
    """연결할 때마다 외래키 검사를 켠다 (SQLite는 기본이 꺼짐)"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def build(reset=False, demo=False):
    """테이블을 만들고 가상 회사 샘플 데이터를 채운다

    demo=True면 처음 보는 사람이 바로 결과를 볼 수 있게 9월 근태 확정(S09)과 급여 저장(S11, 작성중)까지 해 둔다
    """
    from erp import seed   # seed가 db를 불러오므로 순환을 피하려고 여기서 import

    DB_PATH.parent.mkdir(exist_ok=True)
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed.fill(conn)
    conn.close()
    if demo:
        from erp import payroll, rules, worktime
        year, month = seed.MONTH_START.year, seed.MONTH_START.month
        worktime.save(worktime.compute(rules.Policy(), year, month), year, month)
        results, when, *_ = payroll.calc(year, month)
        payroll.save(year, month, results, when)


def ensure():
    """DB 파일이 없을 때만 만든다. Streamlit Cloud는 재시작하면 파일이 사라지므로 매번 확인"""
    if not DB_PATH.exists():
        build(demo=True)


def query(sql, params=()):
    """SELECT 결과를 표(DataFrame)로 돌려준다"""
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def employees():
    """사원 + 부서·직급·고용형태 이름. 여러 화면이 같이 쓴다"""
    return query("""
        SELECT e.emp_no, e.name, d.name AS dept, r.name AS rank, t.name AS emp_type,
               e.pay_type, e.shift_group, e.weekly_hours, e.hire_date, e.leave_date,
               e.tax_family, e.tax_children, e.withholding_pct
          FROM employee e
          JOIN department d ON d.dept_code = e.dept_code
          JOIN code r ON r.grp = '직급' AND r.code = e.rank_code
          JOIN code t ON t.grp = '고용형태' AND t.code = e.emp_type
         ORDER BY e.emp_no""")


def table_counts():
    """테이블별 행 수 — 홈 화면에서 17개 테이블이 어떻게 채워졌는지 보여준다"""
    names = query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")["name"]
    rows = [(n, int(query(f"SELECT COUNT(*) AS n FROM {n}")["n"][0])) for n in names]
    return pd.DataFrame(rows, columns=["table", "rows"])
