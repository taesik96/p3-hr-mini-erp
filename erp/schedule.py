# =========================================================
#  근무표 (S07) — 교대 패턴으로 한 달 근무표를 만들고, 특근·근무 변경을 반영한다
#  샘플 생성기(seed.py)도 같은 build()를 쓴다
# =========================================================

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from erp import db


MONTHS = [(2026, m) for m in (9, 10, 11, 12)]     # 공휴일 달력이 준비된 달


@dataclass
class Pattern:
    """교대 패턴 — 교대 형태는 인터뷰로 확정한다 (기획서 §9-1)"""
    base_monday: date = date(2026, 8, 31)   # 이 주에 A조가 주간조
    cycle_weeks: int = 1                    # 몇 주마다 주간·야간을 바꾸는지
    part_time_days: tuple = (0, 2, 4)       # 단시간 근로자 근무 요일 (0 = 월요일)


def month_days(year, month):
    return [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def month_range(year, month):
    days = month_days(year, month)
    return days[0].isoformat(), days[-1].isoformat()


# ---- 1. 생성 규칙 ----

def day_type(emp, day, holidays, pattern):
    """날짜 구분은 달력과 고용형태로 정해진다. 근무조를 바꿔도 이 값은 그대로다"""
    if day.isoformat() in holidays:
        return "공휴일"
    if day.weekday() == 6:
        return "휴무일" if emp["weekly_hours"] < 15 else "주휴일"   # 주 15시간 미만은 주휴일 없음 (제18조 제3항)
    if day.weekday() == 5:
        return "휴무일"
    if emp["emp_type"] == "E3" and day.weekday() not in pattern.part_time_days:
        return "휴무일"
    return "소정근로일"


def shift_for(emp, day, pattern):
    """그날 맡을 근무조. 생산직은 기준 주부터 cycle_weeks마다 A조·B조가 주간·야간을 바꾼다"""
    if emp["emp_type"] == "E3":
        return "PT"
    if not emp["shift_group"]:
        return "OFC"
    monday = day - timedelta(days=day.weekday())
    a_on_day = (monday - pattern.base_monday).days // 7 // pattern.cycle_weeks % 2 == 0
    return "DAY" if a_on_day == (emp["shift_group"] == "A") else "NGT"


def build(employees, days, holidays, pattern):
    """사원 × 날짜 → (사번, 날짜, 근무조, 날짜 구분). 입사 전·퇴사 후 날짜는 뺀다

    employees  dict 목록: emp_no, emp_type, shift_group, weekly_hours, hire_date, leave_date (날짜는 date)
    """
    rows = []
    for emp in employees:
        for day in days:
            if day < emp["hire_date"] or (emp["leave_date"] and day > emp["leave_date"]):
                continue
            kind = day_type(emp, day, holidays, pattern)
            rows.append((emp["emp_no"], day, shift_for(emp, day, pattern) if kind == "소정근로일" else None, kind))
    return rows


# ---- 2. DB와 주고받기 ----

def _employees():
    df = db.query("SELECT emp_no, emp_type, shift_group, weekly_hours, hire_date, leave_date FROM employee")
    return [dict(emp_no=r.emp_no, emp_type=r.emp_type,
                 shift_group=r.shift_group if pd.notna(r.shift_group) else None,
                 weekly_hours=r.weekly_hours, hire_date=date.fromisoformat(r.hire_date),
                 leave_date=date.fromisoformat(r.leave_date) if pd.notna(r.leave_date) else None)
            for r in df.itertuples()]


def month_status(year, month):
    """그달 근무표·출퇴근 기록 건수와 등록된 공휴일"""
    first, last = month_range(year, month)
    count = lambda t, col: int(db.query(f"SELECT COUNT(*) n FROM {t} WHERE {col} BETWEEN ? AND ?",
                                        (first, last))["n"][0])
    return dict(schedule=count("schedule", "work_date"), attendance=count("attendance", "work_date"),
                holidays=db.query("SELECT date, name FROM holiday WHERE date BETWEEN ? AND ? ORDER BY date",
                                  (first, last)))


def generate(year, month, pattern):
    """저장하지 않고 결과만 만든다 → 화면에서 미리 보고 저장"""
    holidays = set(db.query("SELECT date FROM holiday")["date"])
    rows = build(_employees(), month_days(year, month), holidays, pattern)
    return pd.DataFrame([(e, d.isoformat(), s, k) for e, d, s, k in rows],
                        columns=["emp_no", "work_date", "shift_code", "day_type"])


def save_month(df, year, month):
    """그달 근무표를 통째로 바꾼다. 출퇴근 기록이 있는 달은 기록과 어긋나므로 막는다"""
    if month_status(year, month)["attendance"]:
        raise ValueError("출퇴근 기록이 있는 달은 다시 생성할 수 없습니다. 개별 변경을 쓰세요.")
    first, last = month_range(year, month)
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM schedule WHERE work_date BETWEEN ? AND ?", (first, last))
        conn.executemany("INSERT INTO schedule VALUES (?,?,?,?)",
                         [tuple(None if pd.isna(v) else v for v in r) for r in df.itertuples(index=False)])
    conn.close()


def change(emp_nos, day, shift_code):
    """특근 편성·근무 변경. 날짜 구분은 달력이 정하므로 근무조만 바꾼다 → (바꾼 사번, [(사번, 사유)])"""
    done, refused = [], []
    conn = db.connect()
    with conn:
        for emp in emp_nos:
            row = conn.execute("SELECT shift_code FROM schedule WHERE emp_no = ? AND work_date = ?",
                               (emp, day)).fetchone()
            has_record = conn.execute("SELECT 1 FROM attendance WHERE emp_no = ? AND work_date = ?",
                                      (emp, day)).fetchone()
            if row is None:
                refused.append((emp, "그날 근무표가 없습니다 (생성 전이거나 입사 전·퇴사 후)"))
            elif shift_code is None and has_record:
                refused.append((emp, "출퇴근 기록이 있어 근무를 없앨 수 없습니다. 기록을 먼저 지우세요 (S08)"))
            else:
                conn.execute("UPDATE schedule SET shift_code = ? WHERE emp_no = ? AND work_date = ?",
                             (shift_code, emp, day))
                done.append(emp)
    conn.close()
    return done, refused
