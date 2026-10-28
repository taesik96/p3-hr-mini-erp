# =========================================================
#  급여 계산(S11) 테스트 — 임시 DB에 샘플을 만들고 9월 근태를 확정한 뒤 계산한다
#  기대값은 손으로 계산해 넣었다. 태식 손계산과 다르면 여기부터 대조한다
# =========================================================

import sqlite3
from datetime import date
from fractions import Fraction

import pytest

from erp import db, payroll, rules, worktime


@pytest.fixture(autouse=True)
def september(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "erp.db")
    db.build()
    worktime.save(worktime.compute(rules.Policy(), 2026, 9), 2026, 9)      # S09 확정


def run():
    results, when, *_ = payroll.calc(2026, 9)
    return {r["emp_no"]: r for r in results}, when


def amount(r, code):
    return next(a for c, a, _ in r["lines"] if c == code)


# ---- 규칙 함수 ----

def test_통상시급():
    assert rules.ordinary_hourly("월급", 5_260_000, {"P02": 300_000, "P03": 200_000}, {"P02", "P03"}, 209) \
        == Fraction(5_760_000, 209)                                          # 27,559.81
    assert rules.ordinary_hourly("시급", 16_000, {"P02": 150_000, "P03": 200_000}, {"P02", "P03"}, 209) \
        == 16_000 + Fraction(350_000, 209)                                   # 17,674.64


def test_4대보험_끝수():
    rate = {"pension_rate": 4.75, "health_rate": 3.595, "ltc_rate": 13.14, "employment_rate": 0.9}
    got = {c: a for c, a, _ in rules.social_insurance(5_901_053, rate)}
    assert got == {"D01": 280_300, "D02": 212_140, "D03": 27_870, "D04": 53_100}


def test_주휴_시간():
    assert rules.weekly_holiday_hours(40) == 8
    assert rules.weekly_holiday_hours(20) == 4
    assert rules.weekly_holiday_hours(12) == 0


# ---- 9월 샘플 ----

def test_지급일은_주말과_공휴일을_피해_앞당긴다():
    _, when = run()
    assert when == date(2026, 10, 8)            # 10/10(토) → 10/9(한글날) → 10/8(목)


def test_월급제_야근():
    r = run()[0]["2012001"]
    assert amount(r, "P01") == 5_260_000
    assert amount(r, "P04") == 341_053           # 8.25시간 × 5,760,000/209 × 1.5 = 341,052.6 → 올림


def test_월급제_결근은_결근일과_주휴를_공제():
    r = run()[0]["2024005"]
    assert r["absent_days"] == ["2026-09-22"]
    assert amount(r, "P01") == 2_700_000 - 206_698     # 2 × 2,700,000/209 × 8 = 206,698.56 → 절사


def test_시급제_기본급은_근로_유급휴가_공휴일을_더한다():
    r = run()[0]["2016003"]                         # 9/16 연차
    assert (r["leave_h"], r["hol_h"]) == (8, 16)
    assert amount(r, "P01") == (r["work"]["기본"] // 60 + 8 + 16) * 11_820
    assert amount(r, "P07") == 4 * 8 * 11_820       # 4주 개근


def test_중도_입사자():
    r = run()[0]["2026002"]                         # 9/14 입사
    assert r["worked_days"] == 17
    assert amount(r, "P03") == 113_334               # 200,000 × 17/30 = 113,333.3 → 올림
    assert amount(r, "P07") == 2 * 8 * 10_320        # 입사 뒤 2주
    assert amount(r, "D01") == amount(r, "D02") == 0 and amount(r, "D04") > 0


def test_단시간_근로자():
    r = run()[0]["2025002"]
    assert amount(r, "P07") == 0
    assert all(amount(r, c) == 0 for c in ("D01", "D02", "D03", "D04"))


def test_최저임금은_고정수당까지_넣어_판단한다():
    r = run()[0]["2024001"]                         # 시급 10,030 + 식대 20만
    assert [lvl for lvl, _ in r["notes"]] == ["주의"]
    assert round(float(r["min_wage_hourly"]), 2) == 10_986.94


def test_과세_급여는_식대_20만원을_뺀다():
    r = run()[0]["2012001"]
    assert r["taxable"] == r["pay_total"] - 200_000


def test_확정된_회차는_다시_계산할_수_없다():
    results, when, *_ = payroll.calc(2026, 9)
    run_id = payroll.save(2026, 9, results, when)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE payroll_run SET status = '확정', closed_at = '2026-10-08' WHERE run_id = ?", (run_id,))
    with pytest.raises(sqlite3.IntegrityError):                     # DB 트리거가 막는다
        with conn:
            conn.execute("UPDATE payroll_line SET amount = 0 WHERE run_id = ?", (run_id,))
    conn.close()
    with pytest.raises(ValueError):
        payroll.save(2026, 9, results, when)


# ---- 급여대장 · 마감 (S12) ----

def saved_run():
    results, when, *_ = payroll.calc(2026, 9)
    return payroll.save(2026, 9, results, when), results


def test_급여대장_합계는_사원별_합과_같다():
    run_id, results = saved_run()
    ledger = payroll.ledger_table(payroll.saved_lines(run_id))
    total = ledger.iloc[-1]
    assert total["지급 합계"] == sum(r["pay_total"] for r in results)
    assert total["실지급"] == sum(r["net"] for r in results)


def test_저장_뒤_임금이_바뀌면_확정_전_점검에_걸린다():
    run_id, _ = saved_run()
    run = payroll.runs().iloc[0]
    assert len(payroll.review(run, 2026, 9)["diff"]) == 0
    conn = db.connect()
    with conn:
        conn.execute("UPDATE wage_contract SET base_amount = base_amount + 100 WHERE emp_no = '2012001'")
    conn.close()
    diff = payroll.review(run, 2026, 9)["diff"]
    assert len(diff) > 0 and set(diff["사번"]) == {"2012001"}


def test_확정하면_잠기고_취소하면_풀린다():
    run_id, results = saved_run()
    payroll.confirm(run_id)
    assert payroll.saved_run(2026, 9)["status"] == "확정"
    assert "확정된 급여 회차는 수정할 수 없습니다" in payroll.try_edit(run_id)
    payroll.reopen(run_id)
    assert payroll.saved_run(2026, 9)["status"] == "작성중"
    assert payroll.try_edit(run_id) is None                      # 작성중이면 고칠 수 있다


# ---- 임금명세서 (S13) ----

def test_명세서는_저장된_급여와_같다():
    from erp import payslip
    run_id, results = saved_run()
    r = next(x for x in results if x["emp_no"] == "2011001")
    d = payslip.data(run_id, "2011001")
    assert (d["pay_total"], d["deduct_total"], d["net"]) == (r["pay_total"], r["deduct"], r["net"])
    assert d["hours"]["휴일 8시간 초과"] == "2:00"
    assert all(basis for _, amount, basis in d["pay"])          # 지급 항목마다 계산 방법이 있다


def test_명세서_PDF():
    from erp import payslip
    if payslip.font() is None:
        pytest.skip("한글 글꼴 없음")
    run_id, _ = saved_run()
    pdf = payslip.pdf_bytes(run_id, ["2011001", "2024005"])
    assert pdf[:4] == b"%PDF" and b"/Count 2" in pdf                # 2명 → 2장


# ---- 소득세 (R9) ----

def test_소득세는_간이세액표로_계산한다():
    by = run()[0]
    assert amount(by["2012001"], "D05") == 411_520       # 가족 4·자녀 1·120%: (363,770 − 20,830) × 1.2 → 절사
    assert amount(by["2012001"], "D06") == 41_150
    assert amount(by["2016005"], "D05") == 14_940         # 가족 5·자녀 3: 94,100 − 79,160
    assert amount(by["2025002"], "D05") == 0              # 단시간, 표 최저 구간 미만


def test_원천징수_정보를_바꾸면_확정_전_점검에_걸린다():
    from erp import incometax
    saved_run()
    run_row = payroll.runs().iloc[0]
    incometax.set_profile("2012001", 4, 1, 100)          # 120% → 100%
    diff = payroll.review(run_row, 2026, 9)["diff"]
    assert set(diff["항목"]) == {"소득세", "지방소득세"} and set(diff["사번"]) == {"2012001"}
