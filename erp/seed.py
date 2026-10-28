# =========================================================
#  가상 회사 '다온정밀' 샘플 데이터 — 2026년 9월 한 달
#  실제 회사·실제 사람과 관계없다. 난수 씨앗을 고정해 매번 같은 데이터가 나온다
# =========================================================

import json
import random
from datetime import date, datetime, timedelta

from erp import schedule
from erp.rules import annual_leave_grants

SEED = 42
MONTH_START = date(2026, 9, 1)
MONTH_END = date(2026, 9, 30)

# ---- 1. 기준정보 ----

COMPANY = (1, "다온정밀(가상)", "자동차 부품 가공", 40, 40, 209, 10, "입사일")

# 2026년 값. 언론 보도로 교차 확인했고 공식 고시 원문 대조는 아직이다 → verified = 0
RATES = [
    (2026, 10320, 4.75, 3.595, 13.14, 0.9, 0,
     "언론·블로그 교차 확인값. 고용노동부·각 공단 고시 원문 대조 전"),
]

# 2026년 9~12월 공휴일 (월력요항·공휴일 규정 기준, 언론 교차 확인). 10월부터는 S07에서 근무표를 만들 때 쓴다
HOLIDAYS = [
    ("2026-09-24", "추석 연휴"),
    ("2026-09-25", "추석"),
    ("2026-09-26", "추석 연휴"),
    ("2026-10-03", "개천절"),
    ("2026-10-05", "대체공휴일(개천절)"),
    ("2026-10-09", "한글날"),
    ("2026-12-25", "기독탄신일"),
]

CODES = [
    ("직급", "R10", "사원", 1), ("직급", "R20", "주임", 2), ("직급", "R30", "조장", 3),
    ("직급", "R40", "대리", 4), ("직급", "R50", "반장", 5), ("직급", "R60", "과장", 6),
    ("직급", "R70", "차장", 7), ("직급", "R80", "부장", 8),
    ("고용형태", "E1", "정규직", 1), ("고용형태", "E2", "계약직", 2), ("고용형태", "E3", "단시간", 3),
    ("휴가종류", "L1", "연차", 1), ("휴가종류", "L2", "반차", 2),
    ("휴가종류", "L3", "경조휴가", 3), ("휴가종류", "L4", "병가", 4),
    ("발령종류", "A1", "입사", 1), ("발령종류", "A2", "승진", 2),
    ("발령종류", "A3", "전보", 3), ("발령종류", "A4", "퇴사", 4),
]
RANK_NAME = {c: n for g, c, n, _ in CODES if g == "직급"}

DEPARTMENTS = [
    ("D100", "관리본부", None, None),
    ("D110", "경영지원팀", "D100", "관리"),
    ("D120", "품질팀", "D100", "관리"),
    ("D200", "생산본부", None, None),
    ("D210", "생산관리팀", "D200", "관리"),
    ("D220", "가공팀", "D200", "생산"),
    ("D230", "조립팀", "D200", "생산"),
]
DEPT_NAME = {d[0]: d[1] for d in DEPARTMENTS}

# 교대 형태는 인터뷰 후 확정 (기획서 §9-1). 지금은 10시간 근무 = 소정 8 + 연장 2 가정
SHIFTS = [
    ("OFC", "사무 주간", "09:00", "18:00", "12:00", "13:00"),
    ("DAY", "생산 주간조", "08:00", "19:00", "12:00", "13:00"),
    ("NGT", "생산 야간조", "20:00", "07:00", "00:00", "01:00"),
    ("PT", "단시간 오전", "10:00", "14:30", "12:00", "12:30"),   # 4시간 근무에도 휴게 30분(제54조)
]
SHIFT_TIME = {s[0]: (s[2], s[3]) for s in SHIFTS}

# (코드, 이름, 지급/공제, 과세, 통상임금 포함, 순서)
PAY_ITEMS = [
    ("P01", "기본급", "지급", 1, 1, 1),
    ("P02", "직책수당", "지급", 1, 1, 2),
    ("P03", "식대", "지급", 0, 1, 3),          # 월 20만 원까지 비과세. 통상임금 포함 여부는 회사 설정값
    ("P04", "연장근로수당", "지급", 1, 0, 4),   # 생산직 비과세 요건은 미확인 (기획서 §9-4)
    ("P05", "야간근로수당", "지급", 1, 0, 5),
    ("P06", "휴일근로수당", "지급", 1, 0, 6),
    ("P07", "주휴수당", "지급", 1, 0, 7),
    ("P08", "미사용연차수당", "지급", 1, 0, 8),
    ("D01", "국민연금", "공제", 0, 0, 11),
    ("D02", "건강보험", "공제", 0, 0, 12),
    ("D03", "장기요양보험", "공제", 0, 0, 13),
    ("D04", "고용보험", "공제", 0, 0, 14),
    ("D05", "소득세", "공제", 0, 0, 15),
    ("D06", "지방소득세", "공제", 0, 0, 16),
]

# ---- 2. 사원 명단 설계 ----
#  일부러 넣은 검증용 사례는 tag로 표시한다

OFFICE = [  # (부서, 직급, 고용형태, 급여형태, 주 소정시간, 입사일, tag)
    ("D110", "R80", "E1", "월급", 40, "2012-03-05", None),
    ("D110", "R60", "E1", "월급", 40, "2016-07-01", None),
    ("D110", "R40", "E1", "월급", 40, "2020-02-03", None),
    ("D110", "R10", "E3", "시급", 12, "2025-11-03", "단시간"),     # 주 12시간 → 주휴·연차 제외(R6·R7)
    ("D120", "R60", "E1", "월급", 40, "2014-09-01", None),
    ("D120", "R40", "E1", "월급", 40, "2019-04-01", "전보"),       # 생산관리팀 → 품질팀
    ("D120", "R10", "E1", "월급", 40, "2026-03-02", None),         # 1년 미만 → 월 단위 연차
    ("D210", "R70", "E1", "월급", 40, "2013-01-07", None),
    ("D210", "R20", "E1", "월급", 40, "2021-08-02", None),
    ("D210", "R10", "E1", "월급", 40, "2024-06-03", None),
]

PRODUCTION = {  # 팀별 반장 1 + 조장 2 + 사원 12 (사원 입사일 None은 무작위)
    "D220": {
        "leaders": [("R50", "2011-04-04"), ("R30", "2015-03-02"), ("R30", "2017-10-10")],
        "fixed": [("E2", "2026-09-14", "신규입사"),                 # 9월 중도 입사
                  ("E2", "2025-04-07", None)],
    },
    "D230": {
        "leaders": [("R50", "2012-06-04"), ("R30", "2016-02-01"), ("R30", "2018-05-02")],
        "fixed": [("E1", "2024-03-04", "임금갱신누락")],            # 2026년 시급 미갱신 → 최저임금 미달(R8)
    },
}
RETIRED = ("D230", "R10", "E1", "시급", 40, "2022-05-02", "2026-08-31")

SURNAMES = list("김이박최정강조윤장임한오서신권황안송전홍")
GIVEN = ["민준", "서연", "도윤", "하은", "예준", "지우", "시우", "서윤", "주원", "지민",
         "하준", "수아", "지호", "채원", "준서", "다은", "건우", "예린", "현우", "소율",
         "우진", "지아", "선우", "유나", "연우", "윤서", "정우", "하린", "승현", "수빈",
         "동현", "예은", "태윤", "나연", "재원", "가은", "민재", "서영", "성민", "혜진",
         "영훈", "미경", "상철", "은정", "경수", "병철", "미숙", "광수", "정희", "두식"]

OFFICE_SALARY = {"R80": 5_200_000, "R70": 4_600_000, "R60": 4_000_000,
                 "R40": 3_300_000, "R20": 2_900_000, "R10": 2_600_000}
POSITION_PAY = {"R80": 300_000, "R70": 200_000, "R60": 150_000, "R50": 150_000, "R30": 100_000}
MEAL = 200_000
PROMOTION_PATH = {"관리": ["R10", "R20", "R40", "R60", "R70", "R80"],
                  "생산": ["R10", "R30", "R50"]}


def d(s):
    return date.fromisoformat(s)


def next_weekday(day):
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def build_people(rng):
    """사원 명세 목록을 만들고 사번·이름을 붙인다"""
    people = []
    for dept, rank, etype, ptype, hours, hire, tag in OFFICE:
        people.append(dict(dept=dept, rank=rank, etype=etype, ptype=ptype, group=None,
                           hours=hours, hire=d(hire), leave=None, tag=tag))

    for dept, team in PRODUCTION.items():
        members = [dict(rank=r, etype="E1", hire=d(h), tag=None) for r, h in team["leaders"]]
        members += [dict(rank="R10", etype=e, hire=d(h), tag=t) for e, h, t in team["fixed"]]
        while len(members) < 15:
            hire = next_weekday(date(2016, 1, 1) + timedelta(days=rng.randrange(365 * 10)))
            members.append(dict(rank="R10", etype="E1", hire=hire, tag=None))
        for i, m in enumerate(members):
            people.append(dict(dept=dept, ptype="시급", group="AB"[i % 2], hours=40, leave=None, **m))

    dept, rank, etype, ptype, hours, hire, leave = RETIRED
    people.append(dict(dept=dept, rank=rank, etype=etype, ptype=ptype, group="B",
                       hours=hours, hire=d(hire), leave=d(leave), tag="퇴사"))

    # 사번 = 입사연도 + 그해 입사 순번
    people.sort(key=lambda p: p["hire"])
    per_year = {}
    names = set()
    for p in people:
        y = p["hire"].year
        per_year[y] = per_year.get(y, 0) + 1
        p["emp_no"] = f"{y}{per_year[y]:03d}"
        while True:
            name = rng.choice(SURNAMES) + rng.choice(GIVEN)
            if name not in names:
                names.add(name)
                p["name"] = name
                break
    return people


def family(p):
    return "생산" if p["group"] else "관리"


# ---- 3. 인사 이력 ----

def assignments(p):
    """입사 → 승진(1월 1일자) → 전보 → 퇴사 순으로 발령 이력을 만든다"""
    path = PROMOTION_PATH[family(p)]
    steps = path.index(p["rank"]) if p["rank"] in path else 0
    first_dept = "D210" if p["tag"] == "전보" else p["dept"]
    rows = [(p["hire"], "A1", None, f"{DEPT_NAME[first_dept]} / {RANK_NAME[path[0]]}")]

    span = 2026 - p["hire"].year
    for j in range(1, steps + 1):
        year = p["hire"].year + max(1, round(span * j / (steps + 1)))
        rows.append((date(year, 1, 1), "A2", RANK_NAME[path[j - 1]], RANK_NAME[path[j]]))

    if p["tag"] == "전보":
        rows.append((date(2022, 7, 1), "A3", DEPT_NAME["D210"], DEPT_NAME[p["dept"]]))
    if p["leave"]:
        rows.append((p["leave"], "A4", DEPT_NAME[p["dept"]], None))
    return sorted(rows, key=lambda r: r[0])


def wage_rows(p, rng):
    """2025년부터의 임금 이력. 2026년 1월 1일에 약 3% 인상"""
    fixed = {}
    if p["rank"] in POSITION_PAY:
        fixed["P02"] = POSITION_PAY[p["rank"]]
    if p["hours"] >= 40:
        fixed["P03"] = MEAL

    if p["ptype"] == "월급":
        y2026 = OFFICE_SALARY[p["rank"]] + rng.randrange(0, 11) * 10_000
        y2025 = int(round(y2026 / 1.03, -4))
    elif p["tag"] == "단시간":
        y2026, y2025 = 11_000, 10_500
    else:
        tenure = min(2026 - p["hire"].year, 10)
        base = {"R50": 14_500, "R30": 13_000}.get(p["rank"], 10_320)
        y2026 = base + tenure * 150
        y2025 = max(int(round(y2026 / 1.03, -1)), 10_030)

    first = max(p["hire"], date(2025, 1, 1))
    if p["hire"] >= date(2026, 1, 1):
        return [(p["hire"], y2026, fixed)]
    if p["tag"] == "임금갱신누락":
        return [(first, 10_030, fixed)]
    return [(first, y2025, fixed), (date(2026, 1, 1), y2026, fixed)]


# ---- 4. 근무표 ----
#  기본 근무표는 S07과 같은 생성기로 만들고, 휴일 특근만 얹는다

PATTERN = schedule.Pattern()       # 8/31 주에 A조 주간, 1주마다 교대, 단시간은 월·수·금

SPECIAL_WORK = {  # 휴일 특근: (날짜, 부서, 조 또는 None, 인원 수)
    "휴무일 특근 → 연장근로": (date(2026, 9, 12), "D230", "B", 99),   # 그 주 주간조였던 B조
    "주휴일 특근 → 휴일근로, 8시간 초과": (date(2026, 9, 20), "D220", "A", 2),
    "공휴일 특근 → 휴일근로": (date(2026, 9, 24), "D220", "B", 6),
}


def as_employee(p):
    """샘플 명세 → 근무표 생성기가 받는 모양"""
    return dict(emp_no=p["emp_no"], emp_type=p["etype"], shift_group=p["group"],
                weekly_hours=p["hours"], hire_date=p["hire"], leave_date=p["leave"])


def build_schedule(people, holidays):
    special = {}
    for day, dept, group, count in SPECIAL_WORK.values():
        team = [p for p in people if p["dept"] == dept and p["group"] == group and not p["leave"]]
        for p in team[:count]:
            weekday_shift = schedule.shift_for(as_employee(p), day, PATTERN)
            special[(p["emp_no"], day)] = "DAY" if day.weekday() >= 5 else weekday_shift

    rows = schedule.build([as_employee(p) for p in people],
                          schedule.month_days(MONTH_START.year, MONTH_START.month), holidays, PATTERN)
    return [(e, day, special.get((e, day), shift), kind) for e, day, shift, kind in rows]


# ---- 5. 휴가 · 결근 ----

def build_leave(people, schedule, rng):
    """승인 7건, 반려 1건, 신청 1건 + 결근 1건"""
    workdays = {}
    for emp, day, shift, kind in schedule:
        if kind == "소정근로일" and shift:
            workdays.setdefault(emp, []).append(day)

    full_month = [p for p in people
                  if p["hire"] < date(2025, 9, 1) and not p["leave"] and p["hours"] >= 40]
    picked = rng.sample(full_month, 10)
    office = [p for p in full_month if not p["group"]]
    half_day = rng.choice([p for p in office if p not in picked])

    uses, absent = [], None
    plan = [("L1", 1.0, "승인")] * 5 + [("L3", 1.0, "승인"), ("L1", 1.0, "반려"), ("L1", 1.0, "신청")]
    for p, (ltype, days, status) in zip(picked, plan):
        day = date(2026, 10, 16) if status == "신청" else rng.choice(workdays[p["emp_no"]])
        uses.append((p["emp_no"], day, ltype, days, status))
    uses.append((half_day["emp_no"], rng.choice(workdays[half_day["emp_no"]]), "L2", 0.5, "승인"))

    p = picked[8]                                  # 휴가 없이 하루 빠진 사람
    absent = (p["emp_no"], rng.choice(workdays[p["emp_no"]]))
    return uses, absent


# ---- 6. 출퇴근 기록 ----

def at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m)


def build_attendance(people, schedule, uses, absent, rng):
    by_no = {p["emp_no"]: p for p in people}
    off = {(e, day) for e, day, t, n, s in uses if s == "승인" and t != "L2"}
    half = {(e, day) for e, day, t, n, s in uses if s == "승인" and t == "L2"}

    rows = []
    for emp, day, shift, kind in schedule:
        if not shift or (emp, day) in off or (emp, day) == absent:
            continue
        p = by_no[emp]
        start, end = (at(day, t) for t in SHIFT_TIME[shift])
        if end <= start:                                # 야간조는 다음 날 퇴근
            end += timedelta(days=1)

        late = rng.random() < 0.05
        clock_in = start + timedelta(minutes=rng.randint(3, 20) if late else -rng.randint(3, 15))
        clock_out = end + timedelta(minutes=rng.randint(0, 12))
        if (emp, day) in half:                          # 오후 반차
            clock_out = at(day, "14:00")
        elif shift == "OFC" and rng.random() < 0.10:    # 사무직 야근
            clock_out = end + timedelta(minutes=rng.randint(60, 180))
        elif shift == "DAY" and rng.random() < 0.08:    # 생산직 추가 잔업
            clock_out = end + timedelta(minutes=rng.randint(60, 120))

        source = "수기" if p["tag"] == "단시간" else "단말기"
        rows.append((emp, day.isoformat(), clock_in.strftime("%Y-%m-%d %H:%M"),
                     clock_out.strftime("%Y-%m-%d %H:%M"), source))
    return rows


# ---- 7. 원천징수 정보 (R9 소득세) ----
#  (공제대상가족 수, 8~20세 자녀 수). 본인·배우자 포함이라 1명 = 본인만
JUNIOR_FAMILY = [(1, 0), (1, 0), (2, 0), (3, 1)]
SENIOR_FAMILY = [(2, 0), (3, 1), (4, 1), (4, 2), (5, 3)]
WITHHOLDING = {"R80": 120, "R70": 80}          # 원천징수 비율 80·120%를 고른 사람도 한 명씩 둔다


def tax_profile(p, rng):
    """가상 부양가족. 다른 샘플 데이터가 바뀌지 않게 별도 난수를 쓴다"""
    if p["tag"] == "단시간" or (p["rank"] == "R10" and p["hire"].year >= 2024):
        family, children = 1, 0
    elif p["rank"] in ("R50", "R60", "R70", "R80"):
        family, children = rng.choice(SENIOR_FAMILY)
    else:
        family, children = rng.choice(JUNIOR_FAMILY)
    return family, children, WITHHOLDING.get(p["rank"], 100)


# ---- 8. 한 번에 채우기 ----

def fill(conn):
    rng = random.Random(SEED)
    holidays = {h for h, _ in HOLIDAYS}

    conn.execute("INSERT INTO company VALUES (?,?,?,?,?,?,?,?)", COMPANY)
    conn.executemany("INSERT INTO rate_table VALUES (?,?,?,?,?,?,?,?)", RATES)
    conn.executemany("INSERT INTO holiday VALUES (?,?)", HOLIDAYS)
    conn.executemany("INSERT INTO code VALUES (?,?,?,?)", CODES)
    conn.executemany("INSERT INTO department VALUES (?,?,?,?)", DEPARTMENTS)
    conn.executemany("INSERT INTO shift VALUES (?,?,?,?,?,?)", SHIFTS)
    conn.executemany("INSERT INTO pay_item VALUES (?,?,?,?,?,?)", PAY_ITEMS)

    people = build_people(rng)
    tax_rng = random.Random(SEED + 1)
    for p in people:
        conn.execute("INSERT INTO employee VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (p["emp_no"], p["name"], p["dept"], p["rank"], p["etype"], p["ptype"],
                      p["group"], p["hours"], p["hire"].isoformat(),
                      p["leave"].isoformat() if p["leave"] else None, *tax_profile(p, tax_rng)))
        for eff, kind, before, after in assignments(p):
            conn.execute("INSERT INTO assignment (emp_no, eff_date, kind, before_value, after_value) "
                         "VALUES (?,?,?,?,?)", (p["emp_no"], eff.isoformat(), kind, before, after))
        for eff, amount, fixed in wage_rows(p, rng):
            conn.execute("INSERT INTO wage_contract (emp_no, eff_date, base_amount, fixed_items) "
                         "VALUES (?,?,?,?)", (p["emp_no"], eff.isoformat(), amount, json.dumps(fixed)))
        if not p["leave"]:
            for g, days, basis, expire in annual_leave_grants(p["hire"], MONTH_END, p["hours"]):
                conn.execute("INSERT INTO leave_grant (emp_no, grant_date, days, basis, expire_date) "
                             "VALUES (?,?,?,?,?)", (p["emp_no"], g.isoformat(), days, basis, expire.isoformat()))

    schedule = build_schedule(people, holidays)
    conn.executemany("INSERT INTO schedule VALUES (?,?,?,?)",
                     [(e, day.isoformat(), s, k) for e, day, s, k in schedule])

    uses, absent = build_leave(people, schedule, rng)
    conn.executemany("INSERT INTO leave_use (emp_no, use_date, leave_type, days, status) VALUES (?,?,?,?,?)",
                     [(e, day.isoformat(), t, n, s) for e, day, t, n, s in uses])

    conn.executemany("INSERT INTO attendance VALUES (?,?,?,?,?)",
                     build_attendance(people, schedule, uses, absent, rng))
