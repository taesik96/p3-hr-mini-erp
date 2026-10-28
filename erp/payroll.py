# =========================================================
#  급여 계산 (S11) — 확정된 근태(S09) + 임금 이력(S06) + 요율표(S01) → 사원별 급여 항목과 계산 근거
#  금액은 Fraction으로 정확히 계산하고 마지막에만 끝수를 처리한다 (rules.won_up · won_down10)
# =========================================================

import json
import math
from datetime import date, datetime, timedelta
from fractions import Fraction

import pandas as pd

from erp import db, incometax, rules, schedule

DAY_HOURS = 8
MEAL_TAX_FREE = 200_000          # 식대 비과세 한도 (월)

# 화면과 README에 그대로 보여 주는 계산 전제. 바뀌면 여기만 고친다
ASSUMPTIONS = [
    ("통상시급 (R1)", "월급제 (기본급 + 직책수당 + 식대) ÷ 209, 시급제 시급 + (직책수당 + 식대) ÷ 209. 식대의 통상임금 포함은 회사 설정값 (S03)"),
    ("시급제 기본급", "(S09 기본 근로 + 유급휴가 + 평일 공휴일) × 시급. 토·일과 겹친 공휴일은 유급휴일수당 없음 [행정해석 — 원문 확인 필요]"),
    ("주휴수당 (R6)", "그달에 일요일이 있는 주마다 판정. 소정근로일을 모두 나왔거나 유급휴가면 개근. 시급제는 개근한 주 × 8시간 × 시급 "
                     "(월 고정수당은 이미 월 단위로 주므로 빼고 계산). 월급제는 월급(209시간)에 포함. '다음 주 근로 예정' 요건은 반영 안 함"),
    ("월급제 결근", "(결근일 + 주휴 못 받는 주) × 일급(기본급 ÷ 209 × 8)을 기본급에서 뺌 — 회사 기준, 인터뷰 확인"),
    ("월 중 입사·퇴사", "기본급(월급제)과 고정수당을 달력 날짜로 일할 — 회사 기준"),
    ("4대보험 (R9)", "그달 과세 급여를 보수월액으로 가정 (실무는 공단에 신고한 보수월액 기준) · 상한·하한 미적용 · 10원 미만 절사 · "
                    "월 중 입사자는 국민연금·건강·장기요양 다음 달부터 · 월 소정 60시간 미만은 제외 [모두 원문 확인 필요]"),
    ("비과세", "식대 월 20만 원까지. 생산직 연장·야간 비과세는 미적용 (기획서 §9-4)"),
    ("소득세 (R9)", "근로소득 간이세액표(소득세법 시행령 별표 2, 2026.2.27 개정, 3/1 지급분부터)에서 월급여(과세 급여)와 "
                   "공제대상가족 수로 찾고, 8~20세 자녀 공제를 빼고, 근로자가 고른 비율(80·100·120%)을 곱한 뒤 10원 미만 절사. "
                   "지방소득세는 소득세의 10%. 홈택스 간이세액표 계산기와 13건 대조 일치 (2026-10-29)"),
    ("끝수", "지급 항목은 원 미만 올림, 결근 공제는 원 미만 절사 — 근로자에게 불리하지 않게"),
    ("근로시간", "S09에서 확정한 값을 쓴다. S09 계산 기준을 바꾸면 다시 확정해야 반영된다"),
]


def hm(hours):
    """시간(Fraction) → '9:54'"""
    m = round(hours * 60)
    return f"{m // 60}:{m % 60:02d}"


def num(x):
    """Fraction → '15,716.75' (손계산과 맞추기 쉽게 소수 둘째 자리)"""
    return f"{float(x):,.2f}"


def months_confirmed():
    """근태(S09)를 확정한 달"""
    ym = db.query("SELECT DISTINCT substr(work_date, 1, 7) AS ym FROM work_summary ORDER BY ym")["ym"]
    return [(int(x[:4]), int(x[5:])) for x in ym]


def pay_date(year, month, pay_day, holidays):
    """다음 달 지급일. 토·일·공휴일이면 앞당긴다"""
    d = date(year + month // 12, month % 12 + 1, pay_day)
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d -= timedelta(days=1)
    return d


# ---- 1. 입력 모으기 ----

def _context(year, month):
    first, last = (date.fromisoformat(x) for x in schedule.month_range(year, month))
    rate = db.query("SELECT * FROM rate_table WHERE year = ?", (year,))
    if rate.empty:
        raise ValueError(f"{year}년 요율표가 없습니다 (S01)")
    items = db.query("SELECT * FROM pay_item ORDER BY sort")
    sundays = [d for d in schedule.month_days(year, month) if d.weekday() == 6]
    span = (sundays[0] - timedelta(days=6)).isoformat(), sundays[-1].isoformat()     # 주휴 판정할 주 전체

    emps = db.query("""SELECT * FROM employee WHERE hire_date <= ? AND (leave_date IS NULL OR leave_date >= ?)
                        ORDER BY emp_no""", (last.isoformat(), first.isoformat()))
    names = db.employees().set_index("emp_no")
    wages = (db.query("SELECT * FROM wage_contract WHERE eff_date <= ? ORDER BY eff_date", (last.isoformat(),))
             .groupby("emp_no").tail(1).set_index("emp_no"))
    work = db.query("""
        SELECT emp_no, SUM(regular_h) AS 기본, SUM(overtime_h) AS 연장, SUM(night_h) AS 야간,
               SUM(holiday_h) AS 휴일, SUM(holiday_over8_h) AS 휴일8h초과
          FROM work_summary WHERE work_date BETWEEN ? AND ? GROUP BY emp_no""", schedule.month_range(year, month))
    work = {r.emp_no: {k: round(getattr(r, k) * 60) for k in ("기본", "연장", "야간", "휴일", "휴일8h초과")}
            for r in work.itertuples()}
    leave = db.query("SELECT * FROM leave_use WHERE status = '승인' AND use_date BETWEEN ? AND ?", span)
    sched = db.query("""SELECT emp_no, work_date, day_type, shift_code FROM schedule
                         WHERE work_date BETWEEN ? AND ?""", span)
    att = set(db.query("SELECT emp_no || '|' || work_date AS k FROM attendance WHERE work_date BETWEEN ? AND ?",
                       span)["k"])
    special = {k: set(g["emp_no"]) for k, g in sched[(sched["day_type"] != "소정근로일") & sched["shift_code"].notna()
                                                       & sched["work_date"].between(first.isoformat(), last.isoformat())]
               .groupby("day_type")}
    holidays = set(db.query("SELECT date FROM holiday")["date"])
    company = db.query("SELECT * FROM company").iloc[0]
    return dict(first=first, last=last, pay_date=pay_date(year, month, int(company["pay_day"]), holidays), n_days=last.day, rate=rate.iloc[0], company=company,
                ordinary_codes=set(items[items["ordinary_wage"] == 1]["item_code"]),
                item_name=dict(zip(items["item_code"], items["name"])), item_kind=dict(zip(items["item_code"], items["kind"])),
                sundays=sundays, emps=emps, names=names, wages=wages, work=work, leave=leave, sched=sched, att=att,
                special=special, holidays=holidays,
                month_holidays=[date.fromisoformat(h) for h in sorted(holidays) if first.isoformat() <= h <= last.isoformat()])


# ---- 2. 사원 한 명 ----

def _weeks(emp, hire, leave_date, c):
    """R6 주휴 판정 — 일요일이 이 달에 있는 주마다 소정근로일 개근 여부"""
    mine = c["sched"][(c["sched"]["emp_no"] == emp) & (c["sched"]["day_type"] == "소정근로일")
                      & c["sched"]["shift_code"].notna()]["work_date"]
    paid_off = set(c["leave"][c["leave"]["emp_no"] == emp]["use_date"])
    out = []
    for sun in c["sundays"]:
        mon = sun - timedelta(days=6)
        if hire > sun or (leave_date and leave_date < mon):
            continue                                            # 그 주에 재직하지 않음
        days = [d for d in mine if mon.isoformat() <= d <= sun.isoformat()]
        came = [d for d in days if f"{emp}|{d}" in c["att"]]
        off = [d for d in days if d not in came and d in paid_off]
        absent = [d for d in days if d not in came and d not in off]
        out.append({"주": f"{mon:%m-%d} ~ {sun:%m-%d}", "소정근로일": len(days), "출근": len(came),
                    "유급휴가": len(off), "결근": len(absent), "결근일": absent,
                    "개근": bool(days) and not absent})
    return out


def calc_one(e, c):
    emp, pay_type = e["emp_no"], e["pay_type"]
    w = c["wages"].loc[emp]
    base, fixed = int(w["base_amount"]), json.loads(w["fixed_items"])
    hire = date.fromisoformat(e["hire_date"])
    leave_date = date.fromisoformat(e["leave_date"]) if pd.notna(e["leave_date"]) else None
    start, end = max(hire, c["first"]), min(leave_date or c["last"], c["last"])
    worked_days = (end - start).days + 1
    ratio = Fraction(worked_days, c["n_days"])
    monthly_hours = c["company"]["monthly_hours"]
    weekly_hours = Fraction(e["weekly_hours"])
    daily = min(Fraction(DAY_HOURS), weekly_hours / 5)
    ordinary = rules.ordinary_hourly(pay_type, base, fixed, c["ordinary_codes"], monthly_hours)
    work = c["work"].get(emp, dict.fromkeys(("기본", "연장", "야간", "휴일", "휴일8h초과"), 0))
    weeks = _weeks(emp, hire, leave_date, c)
    absent_days = [d for wk in weeks for d in wk["결근일"] if c["first"].isoformat() <= d <= c["last"].isoformat()]
    lost_weeks = [wk for wk in weeks if wk["결근"]]
    pro = f" × 재직 {worked_days}/{c['n_days']}일 (일할, 회사 기준)" if ratio < 1 else ""
    lines, notes = [], []

    # 기본급
    leave_h = hol_h = Fraction(0)
    if pay_type == "월급":
        amount = rules.won_up(base * ratio)
        basis = f"월 기본급 {base:,}원{pro}"
        if absent_days or lost_weeks:
            day_wage = Fraction(base) / Fraction(monthly_hours) * DAY_HOURS
            cut = math.floor((len(absent_days) + len(lost_weeks)) * day_wage)
            amount -= cut
            basis += (f" − (결근 {len(absent_days)}일 + 주휴 못 받는 주 {len(lost_weeks)}일) × 일급 {num(day_wage)}원"
                      f"(= 기본급 ÷ {monthly_hours:g} × 8) = {cut:,}원 공제 (회사 기준)")
    else:
        mine = c["leave"][(c["leave"]["emp_no"] == emp) & c["leave"]["use_date"].between(
            c["first"].isoformat(), c["last"].isoformat())]
        leave_h = sum((Fraction(str(x)) * daily for x in mine["days"]), Fraction(0))
        paid_holidays = [h for h in c["month_holidays"] if h.weekday() < 5 and start <= h <= end and weekly_hours >= 15]
        hol_h = len(paid_holidays) * daily
        total = Fraction(work["기본"], 60) + leave_h + hol_h
        amount = rules.won_up(total * base)
        basis = (f"(근로 {hm(Fraction(work['기본'], 60))} + 유급휴가 {hm(leave_h)} + 유급 공휴일 {hm(hol_h)})"
                 f" = {hm(total)} × 시급 {base:,}원")
    lines.append(("P01", amount, basis))

    # 고정수당
    for code in sorted(fixed):
        tail = " · 월 20만 원까지 비과세" if code == "P03" else ""
        lines.append((code, rules.won_up(fixed[code] * ratio), f"고정 {fixed[code]:,}원{pro}{tail}"))

    # 가산수당 (R2·R3·R4) — 통상시급 기준
    t = f"통상시급 {num(ordinary)}원"
    if work["연장"]:
        lines.append(("P04", rules.won_up(Fraction(work["연장"], 60) * ordinary * Fraction(3, 2)),
                      f"연장 {hm(Fraction(work['연장'], 60))} × {t} × 1.5"))
    if work["야간"]:
        lines.append(("P05", rules.won_up(Fraction(work["야간"], 60) * ordinary / 2),
                      f"야간 {hm(Fraction(work['야간'], 60))} × {t} × 0.5 (가산분만, 시간 자체 임금은 기본급·연장·휴일에 있음)"))
    if work["휴일"] or work["휴일8h초과"]:
        h8, over = Fraction(work["휴일"], 60), Fraction(work["휴일8h초과"], 60)
        lines.append(("P06", rules.won_up(h8 * ordinary * Fraction(3, 2) + over * ordinary * 2),
                      f"휴일 {hm(h8)} × {t} × 1.5 + 8시간 초과 {hm(over)} × {t} × 2.0"))

    # 주휴수당 (R6) — 시급제만. 월급제는 월급에 들어 있다
    if pay_type == "시급":
        per_week = rules.weekly_holiday_hours(e["weekly_hours"])
        ok = [wk for wk in weeks if wk["개근"]]
        if per_week == 0:
            lines.append(("P07", 0, "주 15시간 미만 → 주휴 없음 (제18조 제3항)"))
        else:
            miss = [wk["주"] for wk in weeks if not wk["개근"]]
            lines.append(("P07", rules.won_up(len(ok) * per_week * base),
                          f"개근한 주 {len(ok)}주 × {hm(per_week)} × 시급 {base:,}원"
                          + (f" (개근 못 한 주: {', '.join(miss)})" if miss else "")))

    # 과세 급여 → 4대보험 (R9) → 소득세
    pay_total = sum(a for _, a, _ in lines)
    meal = next((a for code, a, _ in lines if code == "P03"), 0)
    taxable = pay_total - min(meal, MEAL_TAX_FREE)
    covered = weekly_hours * 365 / 7 / 12 >= 60                  # 월 소정근로 60시간 이상
    mid_month = c["first"] <= hire <= c["last"] and hire.day != 1
    lines += rules.social_insurance(taxable, c["rate"], pension_health=not mid_month, covered=covered)
    rows, anchor = incometax.table()
    tax, tax_basis = rules.simplified_tax(taxable, int(e["tax_family"]), int(e["tax_children"]),
                                          int(e["withholding_pct"]), rows, anchor)
    lines += [("D05", tax, tax_basis),
              ("D06", rules.won_down10(Fraction(tax, 10)), f"소득세 {tax:,}원 × 10% → 10원 미만 절사")]

    # 최저임금 (R8)
    mw = rules.min_wage_hourly(pay_type, base, fixed, monthly_hours)
    min_wage = int(c["rate"]["min_wage"])
    if mw < min_wage:
        notes.append(("오류", f"최저임금 미달 — 환산 시급 {num(mw)}원 < {min_wage:,}원 (R8)"))
    elif pay_type == "시급" and base < min_wage:
        notes.append(("주의", f"시급 {base:,}원만 보면 {min_wage:,}원보다 낮지만, 매월 고정 지급하는 수당을 넣으면 "
                             f"환산 {num(mw)}원으로 충족 (산입범위, R8) [원문 확인 필요]. 임금 갱신이 빠진 건 아닌지 확인"))
    if emp not in c["work"]:
        notes.append(("주의", "확정된 근태가 없습니다 (S09)"))
    if c["pay_date"].isoformat() < incometax.EFFECTIVE:
        notes.append(("주의", f"지급일이 {incometax.EFFECTIVE} 전이라 2026년 3월 개정 간이세액표 적용 대상이 아닙니다"))

    deduct = sum(a for code, a, _ in lines if c["item_kind"][code] == "공제")
    return dict(emp_no=emp, name=c["names"].loc[emp, "name"], dept=c["names"].loc[emp, "dept"],
                pay_type=pay_type, weekly_hours=e["weekly_hours"], hire_date=e["hire_date"],
                worked_days=worked_days, n_days=c["n_days"], wage_eff=w["eff_date"], base=base, fixed=fixed,
                ordinary=ordinary, ordinary_codes=c["ordinary_codes"], monthly_hours=monthly_hours,
                min_wage_hourly=mw, work=work, leave_h=leave_h, hol_h=hol_h, weeks=weeks,
                absent_days=absent_days, mid_month=mid_month, covered=covered,
                tax_family=int(e["tax_family"]), tax_children=int(e["tax_children"]),
                withholding_pct=int(e["withholding_pct"]),
                lines=lines, pay_total=pay_total, taxable=taxable, deduct=deduct, net=pay_total - deduct, notes=notes,
                special={k for k, v in c["special"].items() if emp in v})


# ---- 3. 전체 ----

def calc(year, month):
    c = _context(year, month)
    results = [calc_one(e, c) for e in c["emps"].to_dict("records")]
    return results, c["pay_date"], c["item_name"], c["item_kind"]


def lines_frame(results, item_name, item_kind):
    return pd.DataFrame([{"사번": r["emp_no"], "이름": r["name"], "부서": r["dept"], "항목코드": code,
                          "항목": item_name[code], "구분": item_kind[code], "금액": amount, "계산 근거": basis}
                         for r in results for code, amount, basis in r["lines"]])


def save(year, month, results, when):
    """급여 회차(작성중)와 급여 상세를 저장한다. 확정된 회차는 DB 트리거가 막는다"""
    pay_month = f"{year}-{month:02d}"
    conn = db.connect()
    with conn:
        run = conn.execute("SELECT run_id, status FROM payroll_run WHERE pay_month = ? AND run_kind = '급여'",
                           (pay_month,)).fetchone()
        if run and run[1] == "확정":
            raise ValueError("확정된 급여 회차는 다시 계산할 수 없습니다")
        if run:
            run_id = run[0]
            conn.execute("DELETE FROM payroll_line WHERE run_id = ?", (run_id,))
            conn.execute("UPDATE payroll_run SET pay_date = ? WHERE run_id = ?", (when.isoformat(), run_id))
        else:
            run_id = conn.execute("INSERT INTO payroll_run (pay_month, pay_date) VALUES (?, ?)",
                                  (pay_month, when.isoformat())).lastrowid
        conn.executemany("INSERT INTO payroll_line VALUES (?,?,?,?,?)",
                         [(run_id, r["emp_no"], code, amount, basis) for r in results for code, amount, basis in r["lines"]])
    conn.close()
    return run_id


def saved_run(year, month):
    r = db.query("SELECT * FROM payroll_run WHERE pay_month = ? AND run_kind = '급여'", (f"{year}-{month:02d}",))
    return None if r.empty else r.iloc[0]


# ---- 4. 손계산 검증용 사원 10명 ----

PICKS = [
    ("V01", "월급제 사무직 — 야근 연장", lambda r: r["pay_type"] == "월급" and r["work"]["연장"] > 0 and not r["absent_days"]),
    ("V02", "월급제 결근 — 결근일·주휴 공제", lambda r: r["pay_type"] == "월급" and r["absent_days"]),
    ("V03", "시급제 생산직 — 특근·휴가 없음", lambda r: r["pay_type"] == "시급" and r["weekly_hours"] >= 40
             and not r["special"] and r["leave_h"] == 0 and r["worked_days"] == r["n_days"] and not r["notes"]),
    ("V04", "토요일 특근 — 주 52시간 초과", lambda r: "휴무일" in r["special"]),
    ("V05", "일요일 특근 — 휴일 8시간 초과", lambda r: "주휴일" in r["special"]),
    ("V06", "추석 특근 — 유급 공휴일 + 휴일근로", lambda r: "공휴일" in r["special"]),
    ("V07", "시급제 연차 사용 — 유급휴가 시간", lambda r: r["pay_type"] == "시급" and r["leave_h"] > 0),
    ("V08", "9월 중도 입사 — 일할·4대보험 취득월", lambda r: r["mid_month"]),
    ("V09", "단시간 근로자 — 주휴·4대보험 제외", lambda r: r["weekly_hours"] < 15),
    ("V10", "시급 갱신 누락 — 최저임금 산입범위", lambda r: any("산입범위" in n for _, n in r["notes"])),
    ("V11", "소득세 — 8~20세 자녀 공제", lambda r: r["tax_children"] >= 2 and r["withholding_pct"] == 100),
    ("V12", "소득세 — 원천징수 비율 80%", lambda r: r["withholding_pct"] == 80),
]


def pick(results):
    out = []
    for vid, title, cond in PICKS:
        hit = next((r for r in results if cond(r)), None)
        if hit:
            out.append(dict(id=vid, title=title, emp_no=hit["emp_no"]))
    return out


# ---- 5. 급여대장 · 확정 (S12) ----

def runs():
    return db.query("SELECT * FROM payroll_run ORDER BY pay_month DESC, run_kind")


def saved_lines(run_id):
    """저장된 급여 상세 → lines_frame()과 같은 모양"""
    run_id = int(run_id)                         # 판다스에서 온 numpy 정수는 SQLite가 숫자로 받지 않는다
    return db.query("""
        SELECT l.emp_no AS 사번, e.name AS 이름, d.name AS 부서, l.item_code AS 항목코드, p.name AS 항목,
               p.kind AS 구분, l.amount AS 금액, l.basis AS "계산 근거"
          FROM payroll_line l
          JOIN employee e ON e.emp_no = l.emp_no
          JOIN department d ON d.dept_code = e.dept_code
          JOIN pay_item p ON p.item_code = l.item_code
         WHERE l.run_id = ? ORDER BY l.emp_no, p.sort""", (run_id,))


def ledger_table(lines):
    """사원 × 항목 급여대장. 지급 합계·공제 합계·실지급, 맨 아래 합계 줄"""
    items = db.query("SELECT item_code, name, kind FROM pay_item ORDER BY sort")
    order = [c for c in items["item_code"] if c in set(lines["항목코드"])]
    kind = dict(zip(items["item_code"], items["kind"]))
    t = lines.pivot_table(index=["사번", "이름", "부서"], columns="항목코드", values="금액",
                          aggfunc="sum", fill_value=0)[order]
    t["지급 합계"] = t[[c for c in order if kind[c] == "지급"]].sum(axis=1)
    t["공제 합계"] = t[[c for c in order if kind[c] == "공제"]].sum(axis=1)
    t["실지급"] = t["지급 합계"] - t["공제 합계"]
    t = t.rename(columns=dict(zip(items["item_code"], items["name"]))).reset_index()
    total = t.select_dtypes("number").sum()
    return pd.concat([t, pd.DataFrame([{"사번": "합계", "이름": f"{len(t)}명", "부서": "", **total}])],
                     ignore_index=True)


def review(run, year, month):
    """확정 전 점검 — 저장한 뒤 근태 재확정·임금 변경으로 지금 계산과 달라진 줄, 최저임금 오류"""
    try:
        results, _, item_name, item_kind = calc(year, month)
    except ValueError as e:
        return dict(diff=None, errors=[str(e)])
    now = lines_frame(results, item_name, item_kind)[["사번", "항목", "금액"]]
    saved = saved_lines(run["run_id"])[["사번", "항목", "금액"]]
    both = saved.merge(now, on=["사번", "항목"], how="outer", suffixes=(" 저장값", " 지금 계산"))
    diff = both[both["금액 저장값"].fillna(-1) != both["금액 지금 계산"].fillna(-1)]
    errors = [f"{r['emp_no']} {r['name']}: {text}" for r in results for level, text in r["notes"] if level == "오류"]
    return dict(diff=diff, errors=errors)


def confirm(run_id):
    """마감: 확정하면 급여 상세는 DB 트리거가 수정·삭제를 막는다"""
    conn = db.connect()
    with conn:
        conn.execute("UPDATE payroll_run SET status = '확정', closed_at = ? WHERE run_id = ? AND status = '작성중'",
                     (datetime.now().strftime("%Y-%m-%d %H:%M"), int(run_id)))
    conn.close()


def reopen(run_id):
    """확정 취소 — 실무에서는 권한·사유 기록이 필요하다 (이번 범위 밖)"""
    conn = db.connect()
    with conn:
        conn.execute("UPDATE payroll_run SET status = '작성중', closed_at = NULL WHERE run_id = ? AND status = '확정'",
                     (int(run_id),))
    conn.close()


def try_edit(run_id):
    """잠금 시험: 확정된 회차의 금액을 1원 바꿔 본다 → DB가 거부하면 그 메시지를 돌려준다"""
    conn = db.connect()
    try:
        with conn:
            conn.execute("UPDATE payroll_line SET amount = amount + 1 WHERE rowid = "
                         "(SELECT rowid FROM payroll_line WHERE run_id = ? LIMIT 1)", (int(run_id),))
        return None
    except Exception as e:                       # 트리거의 RAISE(ABORT)
        return str(e)
    finally:
        conn.close()


def ledger_xlsx(ledger, lines, title):
    """급여대장 엑셀: 시트 1 급여대장, 시트 2 계산 근거"""
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        ledger.to_excel(xw, sheet_name="급여대장", index=False, startrow=1)
        xw.sheets["급여대장"].cell(row=1, column=1, value=title)
        lines.to_excel(xw, sheet_name="계산근거", index=False)
    return buf.getvalue()
