# =========================================================
#  근무표 생성(S07)과 출퇴근 입력 검사(S08) 테스트
#  매번 임시 폴더에 샘플 DB를 새로 만들어 쓴다 → 앱의 data/erp.db는 건드리지 않는다
# =========================================================

from datetime import date

import pandas as pd
import pytest

from erp import attendance, db, schedule, worktime
from erp.rules import Policy


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "erp.db")
    db.build()


def emp(group=None, emp_type="E1", hours=40):
    return dict(emp_no="T", emp_type=emp_type, shift_group=group, weekly_hours=hours,
                hire_date=date(2020, 1, 1), leave_date=None)


# ---- 근무표 ----

def test_교대는_기준_주부터_한_주씩_바뀐다():
    p = schedule.Pattern()                                   # 8/31 주에 A조 주간
    assert schedule.shift_for(emp("A"), date(2026, 9, 1), p) == "DAY"
    assert schedule.shift_for(emp("A"), date(2026, 9, 8), p) == "NGT"
    assert schedule.shift_for(emp("B"), date(2026, 9, 8), p) == "DAY"


def test_2주_주기면_두_주_동안_같은_근무조():
    p = schedule.Pattern(cycle_weeks=2)
    assert schedule.shift_for(emp("A"), date(2026, 9, 8), p) == "DAY"
    assert schedule.shift_for(emp("A"), date(2026, 9, 15), p) == "NGT"


def test_날짜_구분():
    p, hol = schedule.Pattern(), {"2026-10-05"}
    assert schedule.day_type(emp("A"), date(2026, 10, 5), hol, p) == "공휴일"      # 대체공휴일(월)
    assert schedule.day_type(emp("A"), date(2026, 10, 4), hol, p) == "주휴일"      # 일요일
    assert schedule.day_type(emp("A"), date(2026, 10, 10), hol, p) == "휴무일"     # 토요일
    part = emp(emp_type="E3", hours=12)
    assert schedule.day_type(part, date(2026, 10, 6), hol, p) == "휴무일"          # 단시간 화요일
    assert schedule.day_type(part, date(2026, 10, 4), hol, p) == "휴무일"          # 주 15시간 미만은 주휴일 없음


def test_10월_생성과_저장():
    df = schedule.generate(2026, 10, schedule.Pattern())
    assert df["emp_no"].nunique() == 40                     # 8월 말 퇴사자는 빠진다
    assert df[df["work_date"] == "2026-10-09"]["day_type"].eq("공휴일").all()
    schedule.save_month(df, 2026, 10)
    assert schedule.month_status(2026, 10)["schedule"] == len(df)


def test_출퇴근_기록이_있는_달은_다시_생성할_수_없다():
    with pytest.raises(ValueError):
        schedule.save_month(schedule.generate(2026, 9, schedule.Pattern()), 2026, 9)


def test_기록이_있는_날은_근무를_없앨_수_없다():
    day = db.query("SELECT emp_no, work_date FROM attendance LIMIT 1").iloc[0]
    done, refused = schedule.change([day["emp_no"]], day["work_date"], None)
    assert not done and refused


# ---- 출퇴근 검사 ----

def check(rows):
    return attendance.validate(pd.DataFrame(rows, columns=attendance.COLUMNS))


def test_야간조는_퇴근을_다음_날로_본다():
    schedule.save_month(schedule.generate(2026, 10, schedule.Pattern()), 2026, 10)
    night = db.query("SELECT emp_no FROM schedule WHERE work_date = '2026-10-01' AND shift_code = 'NGT' LIMIT 1")
    r = check([[night["emp_no"][0], "2026-10-01", "19:50", "07:04"]]).iloc[0]
    assert r["상태"] == "새 기록" and r["퇴근"] == "2026-10-02 07:04"


def test_오류_사유():
    schedule.save_month(schedule.generate(2026, 10, schedule.Pattern()), 2026, 10)
    a = db.query("SELECT emp_no FROM schedule WHERE work_date = '2026-10-01' AND shift_code = 'DAY' LIMIT 1")["emp_no"][0]
    r = check([
        ["9999001", "2026-10-01", "08:00", "19:00"],
        [a, "2026-10-03", "08:00", "19:00"],                # 개천절, 근무 없음
        [a, "2026-10-01", "8시", "19:00"],
        [a, "2026-10-02", "08:00", "07:00"],                # 23시간
        [a, "2026-11-02", "08:00", "19:00"],                # 11월 근무표 없음
    ])
    assert r["상태"].eq("오류").all()
    assert ["없는 사번" in r["사유"][0], "근무 없는 날" in r["사유"][1], "형식 오류" in r["사유"][2],
            "20시간 초과" in r["사유"][3], "근무표 없음" in r["사유"][4]] == [True] * 5


def test_같은_사번_근무일은_덮어쓰기():
    rec = db.query("SELECT emp_no, work_date FROM attendance LIMIT 1").iloc[0]
    r = check([[rec["emp_no"], rec["work_date"], "08:00", "19:00"]]).iloc[0]
    assert r["상태"] == "덮어쓰기"


def test_예시_파일_검사():
    schedule.save_month(schedule.generate(2026, 10, schedule.Pattern()), 2026, 10)
    path = "docs/samples/2026-10_출퇴근_업로드예시.xlsx"
    with open(path, "rb") as f:
        r = attendance.validate(attendance.read_upload(path, f.read()))
    assert r["상태"].value_counts().to_dict() == {"새 기록": 78, "오류": 5}


# ---- 달 경계 ----

def test_달_경계에_걸친_주는_앞달_기록까지_센다():
    """10/1(목) 근무의 '이 근무 전 주 기본'에 9/28~9/30 기록이 들어가야 한다"""
    schedule.save_month(schedule.generate(2026, 10, schedule.Pattern()), 2026, 10)
    a = db.query("SELECT emp_no FROM schedule WHERE work_date = '2026-10-01' AND shift_code = 'DAY' LIMIT 1")["emp_no"][0]
    attendance.save(check([[a, "2026-10-01", "08:00", "19:00"]]), "엑셀")
    daily = worktime.compute(Policy(), 2026, 10)
    oct1 = daily[(daily["emp_no"] == a) & (daily["work_date"] == "2026-10-01")].iloc[0]
    sept = daily[(daily["emp_no"] == a) & (~daily["in_month"])]
    assert oct1["week_regular_before"] == sept["기본"].sum() > 0
