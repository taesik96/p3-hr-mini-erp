# =========================================================
#  소득세 (R9 간이세액표) 테스트
#  표 값은 erp/tax/간이세액표_2026-03.csv에서 직접 옮겨 적었다
# =========================================================

import pandas as pd
import pytest

from erp import incometax, rules

ROWS, ANCHOR = incometax.table()


def tax(monthly, family=1, children=0, pct=100):
    return rules.simplified_tax(monthly, family, children, pct, ROWS, ANCHOR)[0]


# ---- 표 자체 ----

def test_표는_770천원부터_10000천원까지_빈틈없이_이어진다():
    assert ROWS[0][0] == 770_000 and ROWS[-1][1] == 10_000_000
    assert all(a[1] == b[0] for a, b in zip(ROWS, ROWS[1:]))
    assert len(ROWS) == 646


def test_표_값_몇_줄():
    assert tax(3_010_000, 1) == 74_350          # 3,000~3,020천원 · 1명
    assert tax(5_005_000, 3) == 237_850         # 5,000~5,020천원 · 3명
    assert tax(1_062_000, 1) == 1_040           # 세액이 처음 생기는 구간
    assert tax(1_062_000, 2) == 0


# ---- 표 밖의 규칙 ----

def test_표_최저_구간_미만은_0원():
    assert tax(525_250) == 0


def test_자녀_공제():
    assert [rules.child_deduction(n) for n in range(5)] == [0, 20_830, 45_830, 79_160, 112_490]
    assert tax(5_005_000, 3, children=1) == 237_850 - 20_830
    assert tax(1_062_000, 1, children=0) == 1_040
    assert tax(3_010_000, 3, children=2) == 0                     # 31,940 − 45,830 < 0 → 0원


def test_원천징수_비율과_10원_미만_절사():
    assert tax(5_905_000, 4, children=1, pct=120) == 411_520      # (363,770 − 20,830) × 1.2 = 411,528
    assert tax(5_905_000, 4, children=1, pct=80) == 274_350       # 342,940 × 0.8 = 274,352


def test_가족_11명_초과():
    t10, t11 = 106_600, 87_850                                     # 5,000~5,020천원 10명·11명
    assert tax(5_005_000, 12) == t11 - (t10 - t11) * 1
    assert tax(5_005_000, 13) == t11 - (t10 - t11) * 2


def test_월급여_1천만원():
    assert tax(10_000_000, 1) == 1_507_400                         # 10,000천원 행
    assert tax(12_000_000, 1) == rules.won_down10(1_507_400 + 25_000 + 2_000_000 * 0.98 * 0.35)
    assert tax(20_000_000, 2) == rules.won_down10(1_431_570 + 1_397_000 + 6_000_000 * 0.98 * 0.38)
    assert tax(50_000_000, 1) == rules.won_down10(1_507_400 + 13_394_600 + 5_000_000 * 0.42)


def test_원천징수_정보_검사():
    with pytest.raises(ValueError):
        incometax.set_profile("2012001", 2, 2, 100)                # 자녀 수 = 가족 수
    with pytest.raises(ValueError):
        incometax.set_profile("2012001", 2, 0, 90)                 # 80·100·120만


def test_화면용_표_줄():
    row = incometax.row_for(5_901_053)
    assert row["월급여(천원)"][0] == "5,900 이상 5,920 미만" and row["4명"][0] == 363_770
    assert incometax.row_for(500_000) is None
