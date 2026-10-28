# =========================================================
#  인사 대시보드 (S14) — 저장된 급여(S11)와 확정된 근태(S09)를 모아 본다
#  새로 계산하지 않는다. 화면에 나오는 숫자는 모두 다른 화면에서 확정·저장한 값이다
# =========================================================

from datetime import date, timedelta

import pandas as pd

from erp import db, rules, schedule

# 인건비를 묶는 방법: 급여항목 → 구분
COST_GROUP = {"P01": "기본급", "P02": "고정수당", "P03": "고정수당",
              "P04": "가산수당", "P05": "가산수당", "P06": "가산수당", "P07": "주휴수당"}
COST_ORDER = ["기본급", "고정수당", "가산수당", "주휴수당"]


def latest_run():
    r = db.query("SELECT * FROM payroll_run ORDER BY pay_month DESC LIMIT 1")
    return None if r.empty else r.iloc[0]


def labor_cost(run_id):
    """부서 × 인건비 구분 합계 (지급 항목만)"""
    lines = db.query("""
        SELECT d.name AS 부서, l.item_code, l.amount
          FROM payroll_line l
          JOIN employee e ON e.emp_no = l.emp_no
          JOIN department d ON d.dept_code = e.dept_code
         WHERE l.run_id = ? AND l.item_code LIKE 'P%'""", (int(run_id),))
    lines["구분"] = lines["item_code"].map(COST_GROUP)
    return lines.groupby(["부서", "구분"], as_index=False)["amount"].sum().rename(columns={"amount": "금액"})


def headcount_paid(run_id):
    return int(db.query("SELECT COUNT(DISTINCT emp_no) n FROM payroll_line WHERE run_id = ?", (int(run_id),))["n"][0])


def work_by_employee(year, month):
    """사원별 그달 확정 근로시간 (시간)"""
    w = db.query("""
        SELECT s.emp_no, e.name, d.name AS 부서,
               SUM(s.overtime_h) AS 연장, SUM(s.holiday_h + s.holiday_over8_h) AS 휴일, SUM(s.night_h) AS 야간
          FROM work_summary s
          JOIN employee e ON e.emp_no = s.emp_no
          JOIN department d ON d.dept_code = e.dept_code
         WHERE s.work_date BETWEEN ? AND ?
         GROUP BY s.emp_no""", schedule.month_range(year, month))
    w["연장+휴일"] = w["연장"] + w["휴일"]
    return w.sort_values("연장+휴일", ascending=False)


def weekly_totals(year, month):
    """R5 — 사원 × 주(월~일) 총근로. 이 달에 걸친 주만, 확정된 근태 기준"""
    first, last = (date.fromisoformat(x) for x in schedule.month_range(year, month))
    w = db.query("""
        SELECT s.emp_no, e.name, d.name AS 부서, s.work_date,
               s.regular_h + s.overtime_h + s.holiday_h + s.holiday_over8_h AS 총근로
          FROM work_summary s
          JOIN employee e ON e.emp_no = s.emp_no
          JOIN department d ON d.dept_code = e.dept_code
         WHERE s.work_date BETWEEN ? AND ?""",
                 ((first - timedelta(days=6)).isoformat(), (last + timedelta(days=6)).isoformat()))
    days = pd.to_datetime(w["work_date"])
    w["주"] = (days - pd.to_timedelta(days.dt.weekday, unit="D")).dt.date
    w = w.groupby(["emp_no", "name", "부서", "주"], as_index=False)["총근로"].sum()
    w = w[(w["주"] <= last) & (w["주"] + timedelta(days=6) >= first)].copy()
    w["주 표시"] = w["주"].map(lambda m: f"{m:%m-%d}~{m + timedelta(days=6):%m-%d}")
    w["52시간 초과"] = w["총근로"] - rules.WEEK_MAX / 60
    return w


def headcount():
    emp = db.employees()
    return emp[emp["leave_date"].isna()]
