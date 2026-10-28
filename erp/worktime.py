# =========================================================
#  근태 집계 (S09) — 출퇴근 기록 1건 = 근무 1건으로 계산하고 주 단위로 묶는다
#  규칙 자체는 rules.py, 여기는 DB에서 읽고 순서대로 돌리는 일만 한다
# =========================================================

from datetime import date, datetime, timedelta

import pandas as pd

from erp import db, rules, schedule

KINDS = ["기본", "연장", "휴일", "휴일8h초과", "야간", "연장·야간", "휴일·야간"]


def _at(day, hhmm, after=None):
    """날짜 + 'HH:MM'. after보다 이르면 다음 날로 넘긴다 (야간조 퇴근·휴게)"""
    t = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
    return t + timedelta(days=1) if after and t <= after else t


def _fallback_type(d, holidays):
    """근무표에 없는 날짜(예: 9/30 야간조의 10/1 아침)의 구분"""
    if d.isoformat() in holidays:
        return "공휴일"
    return {6: "주휴일", 5: "휴무일"}.get(d.weekday(), "소정근로일")


# ---- 1. 계산 ----

def months_with_records():
    """출퇴근 기록이 있는 달 [(2026, 9), ...]"""
    ym = db.query("SELECT DISTINCT substr(work_date, 1, 7) AS ym FROM attendance ORDER BY ym")["ym"]
    return [(int(x[:4]), int(x[5:])) for x in ym]


def compute(policy, year, month):
    """그달 출퇴근 기록 → 근무별 결과 표. 조각(pieces)까지 담아 사례 화면에서 그대로 보여준다

    주 40시간은 월요일부터 쌓이므로, 달 앞뒤로 걸친 주의 기록까지 함께 읽고 in_month로 구분한다
    """
    first, last = (date.fromisoformat(d) for d in schedule.month_range(year, month))
    week_from = first - timedelta(days=first.weekday())
    week_to = last + timedelta(days=6 - last.weekday())
    rows = db.query("""
        SELECT a.emp_no, e.name, d.name AS dept, a.work_date, s.shift_code, s.day_type,
               a.clock_in, a.clock_out, f.start_time, f.end_time, f.break_start, f.break_end
          FROM attendance a
          JOIN schedule s USING (emp_no, work_date)
          JOIN shift f ON f.shift_code = s.shift_code
          JOIN employee e ON e.emp_no = a.emp_no
          JOIN department d ON d.dept_code = e.dept_code
         WHERE a.work_date BETWEEN ? AND ?
         ORDER BY a.emp_no, a.work_date""", (week_from.isoformat(), week_to.isoformat()))
    holidays = set(db.query("SELECT date FROM holiday")["date"])
    types = db.query("SELECT emp_no, work_date, day_type FROM schedule")
    day_types = {(r.emp_no, r.work_date): r.day_type for r in types.itertuples()}

    out = []
    for emp, group in rows.groupby("emp_no", sort=False):
        def day_type_of(d, emp=emp):
            return day_types.get((emp, d.isoformat())) or _fallback_type(d, holidays)

        week, week_regular, holiday_used = None, 0, {}
        for r in group.itertuples():
            day = date.fromisoformat(r.work_date)
            monday = day - timedelta(days=day.weekday())          # 1주 = 월~일
            if monday != week:
                week, week_regular = monday, 0

            start = _at(day, r.start_time)
            end = _at(day, r.end_time, after=start)
            has_break = pd.notna(r.break_start)                   # 빈 값은 NaN으로 온다
            b_start = _at(day, r.break_start, after=start) if has_break else None
            b_end = _at(day, r.break_end, after=b_start) if has_break else None
            clock_in = datetime.strptime(r.clock_in, "%Y-%m-%d %H:%M")
            clock_out = datetime.strptime(r.clock_out, "%Y-%m-%d %H:%M")

            s, e, s_note, e_note = rules.recognized_span(clock_in, clock_out, start, end, policy)
            segments = rules.minus_break(s, e, b_start, b_end)
            regular_left = max(0, min(rules.DAY_LIMIT, rules.WEEK_LIMIT - week_regular))
            pieces = rules.classify(segments, day_type_of, regular_left, holiday_used)
            total = rules.summarize(pieces)

            out.append(dict(
                emp_no=emp, name=r.name, dept=r.dept, work_date=r.work_date, week=monday.isoformat(),
                in_month=first <= day <= last,
                shift_code=r.shift_code, day_type=r.day_type, clock_in=r.clock_in, clock_out=r.clock_out,
                shift_span=f"{r.start_time}~{r.end_time}", break_span=f"{r.break_start}~{r.break_end}",
                rec_start=s, rec_end=e, start_note=s_note, end_note=e_note,
                segments=segments, pieces=pieces, week_regular_before=week_regular, **total))
            week_regular += total["기본"]
    return pd.DataFrame(out)


def weekly(daily):
    """R5 — 사원 × 주(월~일) 합계와 52시간 초과. 달 경계에 걸친 주는 앞뒤 달 기록까지 더한다"""
    w = daily.groupby(["emp_no", "name", "dept", "week"], as_index=False)[KINDS].sum()
    w["총근로"] = w[["기본", "연장", "휴일", "휴일8h초과"]].sum(axis=1)
    w["연장+휴일"] = w["총근로"] - w["기본"]
    w["52시간 초과"] = w["총근로"].map(rules.over_week_max)
    span = db.query("SELECT MIN(work_date) AS a, MAX(work_date) AS b FROM attendance").iloc[0]
    week_start = pd.to_datetime(w["week"]).dt.date
    partial = (week_start < date.fromisoformat(span["a"])) | (week_start + timedelta(days=6) > date.fromisoformat(span["b"]))
    w["비고"] = partial.map({True: "부분 주 — 기록이 없는 날짜가 섞여 덜 잡힘", False: ""})
    return w


# ---- 2. 확정: 근로시간 집계 테이블에 저장 ----

def save(daily, year, month):
    """그달 근무만 저장한다. 앞뒤 달 근무는 주 계산에만 쓰고 저장하지 않는다"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    daily = daily[daily["in_month"]]
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM work_summary WHERE work_date BETWEEN ? AND ?", schedule.month_range(year, month))
        conn.executemany(
            "INSERT INTO work_summary VALUES (?,?,?,?,?,?,?,?)",
            [(r.emp_no, r.work_date, r.기본 / 60, r.연장 / 60, r.야간 / 60, r.휴일 / 60, r.휴일8h초과 / 60, now)
             for r in daily.itertuples()])
    conn.close()
    return now


def saved_at(year, month):
    """그달 마지막 확정 시각과 건수. 확정 전이면 None"""
    r = db.query("SELECT MAX(computed_at) AS at, COUNT(*) AS n FROM work_summary WHERE work_date BETWEEN ? AND ?",
                 schedule.month_range(year, month))
    return (r["at"][0], int(r["n"][0])) if r["n"][0] else None


# ---- 3. 손계산 검증용 사례 10건 ----
#  조건에 맞는 근무 중 첫 번째를 고른다. 데이터를 초기화해도 같은 근무가 뽑힌다

CASES = [
    ("C01", "주간조 평일 — 기본형", "R2",
     "08~19시 근무, 휴게 1시간 → 실근로 10시간. 하루 8시간을 넘는 2시간이 연장이다. "
     "근무 시작 전 출근과 종료 후 잠깐 남은 시간은 회사 기준상 근로로 보지 않았다.",
     lambda d: (d.shift_code == "DAY") & (d.day_type == "소정근로일")
               & (d.start_note.str.startswith("근무 시작")) & (d.end_note.str.startswith("근무 종료"))
               & (d.week_regular_before == 0)),
    ("C02", "야간조 평일 — 연장과 야간이 겹침", "R2, R4",
     "20~07시 근무, 00~01시 휴게. 시작부터 8시간(20~24시, 01~05시)이 기본, 05~07시가 연장. "
     "22~06시는 야간이라 05~06시 1시간은 연장 가산과 야간 가산이 둘 다 붙는다.",
     lambda d: (d.shift_code == "NGT") & (d.day_type == "소정근로일") & (d.work_date != "2026-09-23")
               & (d.start_note.str.startswith("근무 시작")) & (d.end_note.str.startswith("근무 종료"))),
    ("C03", "지각", "R2",
     "늦게 온 만큼 실근로가 줄어든다. 연장은 실제 일한 시간이 8시간을 넘는 부분만이다.",
     lambda d: (d.shift_code == "DAY") & (d.day_type == "소정근로일") & d.start_note.str.contains("지각")),
    ("C04", "주간조 잔업", "R2, R5",
     "근무 종료(19시) 후 30분 이상 남으면 잔업으로 보고 실제 퇴근까지 분 단위로 인정한다 (회사 기준).",
     lambda d: (d.shift_code == "DAY") & (d.day_type == "소정근로일") & d.end_note.str.contains("잔업")),
    ("C05", "토요일 특근 — 휴무일 근로", "R2, R5",
     "토요일은 휴일이 아니라 휴무일이다. 그래서 휴일근로가 아니라, 그 주 실근로가 40시간을 넘는 부분이 연장근로다. "
     "이 사람은 월~금에 기본 40시간을 이미 채워 토요일 전부가 연장이고, 주 52시간도 넘는다.",
     lambda d: (d.day_type == "휴무일") & (d.week_regular_before >= rules.WEEK_LIMIT)),
    ("C06", "일요일 특근 — 주휴일 근로 10시간", "R3",
     "주휴일 근로는 휴일근로다. 8시간까지 50%, 넘는 2시간은 100% 가산 (제56조 제2항). "
     "휴일근로는 주 40시간 계산에는 넣지 않지만 주 52시간에는 들어간다.",
     lambda d: (d.day_type == "주휴일")),
    ("C07", "추석 연휴 특근 — 공휴일 근로", "R3",
     "공휴일은 유급휴일이라(제55조 제2항) 이날 일하면 휴일근로다. 계산은 C06과 같다.",
     lambda d: (d.day_type == "공휴일")),
    ("C08", "야간조가 자정 넘어 공휴일로 이어짐", "R3, R4",
     "평일(9/23) 밤에 시작한 근무가 0시를 넘어 공휴일(9/24)로 이어졌다. 0시 이후는 휴일근로로 본다 "
     "[행정해석 기준 — 원문 확인 필요]. 휴일 시간 중 01~06시는 야간도 겹친다.",
     lambda d: (d.shift_code == "NGT") & (d.work_date == "2026-09-23")),
    ("C09", "사무직 오후 반차", "R2",
     "14시 퇴근, 실근로 4시간. 반차 4시간은 유급휴가지만 실제 일한 시간이 아니라 주 40시간 계산에 넣지 않는다 "
     "[행정해석 기준 — 원문 확인 필요].",
     lambda d: (d.shift_code == "OFC") & d.end_note.str.contains("반차")),
    ("C10", "사무직 야근", "R2",
     "18시 이후 잔업은 연장. 22시 전에 끝나 야간은 없다.",
     lambda d: (d.shift_code == "OFC") & d.end_note.str.contains("잔업")),
]


def pick_cases(daily):
    daily = daily[daily["in_month"]]
    picked = []
    for cid, title, rule, point, cond in CASES:
        hit = daily[cond(daily)]
        if len(hit):
            picked.append(dict(id=cid, title=title, rule=rule, point=point, index=hit.index[0]))
    return picked
