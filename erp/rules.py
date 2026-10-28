# =========================================================
#  계산 규칙 — 기획서 §7의 R1~R11을 하나씩 여기에 옮긴다
#  지금 있는 것: R1 통상시급, R2~R5 근로시간 분류, R6 주휴 시간, R7 연차 발생, R8 최저임금 환산,
#               R9 4대보험·소득세(간이세액표)
#  ※ 법령 원문 대조와 손계산 검증 전이다
# =========================================================

import bisect
import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from fractions import Fraction


def add_months(d, months):
    """n개월 뒤 같은 날. 그 달에 그 날이 없으면 말일로 (1/31 + 1개월 → 2/28)"""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def annual_leave_grants(hire_date, as_of, weekly_hours=40):
    """R7 연차 발생 (입사일 기준) — as_of 시점에 아직 쓸 수 있는 발생분만 돌려준다

    - 1년 미만: 1개월 개근마다 1일, 최대 11일 (근로기준법 제60조 제2항)
    - 1년 이상: 15일, 3년차부터 2년마다 1일 가산, 최대 25일 (제60조 제1항·제4항)
    - 주 15시간 미만 단시간 근로자는 연차 없음 (제18조 제3항)
    - 샘플이라 출근율 80% 이상·매월 개근으로 가정한다
    """
    if weekly_hours < 15:
        return []

    grants = []
    one_year = add_months(hire_date, 12)

    for k in range(1, 12):                       # 1년 미만 월 단위 발생
        g = add_months(hire_date, k)
        if g > as_of:
            break
        grants.append((g, 1.0, "제60조 제2항 · 1년 미만 1개월 개근", one_year))

    n = 1                                        # 매년 입사기념일 발생
    while add_months(hire_date, 12 * n) <= as_of:
        g = add_months(hire_date, 12 * n)
        days = min(15 + (n - 1) // 2, 25)
        basis = f"제60조 제1항{'·제4항' if n >= 3 else ''} · 근속 {n}년"
        grants.append((g, float(days), basis, add_months(g, 12)))
        n += 1

    return [x for x in grants if x[3] > as_of]   # 소멸된 발생분은 뺀다


# ---- R2·R3·R4·R5 근로시간 분류 ----
#  모든 시간은 '분' 단위로 계산한다. 반올림·절사하지 않는다

DAY_LIMIT = 8 * 60          # 1일 법정근로시간 (제50조 제2항)
WEEK_LIMIT = 40 * 60        # 1주 법정근로시간 (제50조 제1항)
WEEK_MAX = 52 * 60          # 1주 최대: 40 + 연장 12, 휴일 포함 7일 기준 (제53조 제1항, 제2조 제1항 제7호)
HOLIDAY_LIMIT = 8 * 60      # 휴일근로 8시간까지 50%, 넘는 부분 100% (제56조 제2항)
NIGHT_FROM, NIGHT_TO = 22, 6    # 야간 22시~다음 날 06시 (제56조 제3항)
HOLIDAY_TYPES = ("주휴일", "공휴일")

PREMIUM = {"연장": 0.5, "휴일": 0.5, "휴일8h초과": 1.0, "야간": 0.5}   # 통상임금 대비 가산율


@dataclass
class Policy:
    """법이 아니라 회사가 정하는 기준 — 인터뷰로 확정한다 (기획서 §9)"""
    early_in: bool = False      # 근무 시작 전 출근을 근로로 인정할지
    min_extra: int = 30         # 근무 종료 후 몇 분 이상 남아야 잔업으로 볼지


def minutes(a, b):
    return int((b - a).total_seconds() // 60)


def recognized_span(clock_in, clock_out, start, end, policy):
    """출퇴근 기록 중 근로로 인정할 시작·끝과 그 이유"""
    if clock_in > start:
        s, s_note = clock_in, "출근 시각 (지각)"
    elif clock_in < start and policy.early_in:
        s, s_note = clock_in, "출근 시각 (조기 출근 인정)"
    elif clock_in < start:
        s, s_note = start, f"근무 시작 ({minutes(clock_in, start)}분 일찍 온 것은 미인정)"
    else:
        s, s_note = start, "근무 시작"

    extra = minutes(end, clock_out)
    if extra < 0:
        e, e_note = clock_out, "퇴근 시각 (조기 퇴근·반차)"
    elif extra >= policy.min_extra:
        e, e_note = clock_out, f"퇴근 시각 (잔업 {extra}분 인정)"
    elif extra > 0:
        e, e_note = end, f"근무 종료 (초과 {extra}분은 {policy.min_extra}분 미만이라 미인정)"
    else:
        e, e_note = end, "근무 종료"
    return s, e, s_note, e_note


def minus_break(s, e, break_start, break_end):
    """근로 구간에서 휴게 구간을 뺀다 → 구간 0~2개"""
    if break_start is None or break_end <= s or break_start >= e:
        return [(s, e)]
    parts = []
    if s < break_start:
        parts.append((s, break_start))
    if break_end < e:
        parts.append((break_end, e))
    return parts


def is_night(t):
    return t.hour >= NIGHT_FROM or t.hour < NIGHT_TO


def _cuts(s, e):
    """구간 안에 있는 0시·06시·22시 경계. 여기서 잘라야 조각마다 날짜·야간 여부가 하나로 정해진다"""
    out, day = [], datetime.combine(s.date(), time())
    while day < e:
        out += [day + timedelta(hours=h) for h in (0, NIGHT_TO, NIGHT_FROM) if s < day + timedelta(hours=h) < e]
        day += timedelta(days=1)
    return sorted(out)


def classify(segments, day_type_of, regular_left, holiday_used):
    """R2·R3·R4 — 근로 구간을 기본·연장·휴일·휴일8h초과 조각으로 나누고 야간 여부를 붙인다

    segments      휴게를 뺀 근로 구간 (시간순)
    day_type_of   날짜 → 날짜 구분. 휴일인지는 달력 날짜(0시 기준)로 정한다
    regular_left  이 근무에서 '기본'으로 칠 수 있는 남은 분 = min(하루 8시간, 주 40시간 − 이번 주 기본)
    holiday_used  {날짜: 이미 쓴 휴일근로 분}. 8시간 초과 판단에 쓰고, 이 함수가 갱신한다
    """
    pieces = []
    for s, e in segments:
        bounds = [s, *_cuts(s, e), e]
        for a, b in zip(bounds, bounds[1:]):
            n, kind_of_day = minutes(a, b), day_type_of(a.date())
            if kind_of_day in HOLIDAY_TYPES:
                used = holiday_used.get(a.date(), 0)
                first = max(0, min(n, HOLIDAY_LIMIT - used))
                holiday_used[a.date()] = used + n
                split = [("휴일", first), ("휴일8h초과", n - first)]
            else:
                first = min(n, regular_left)
                regular_left -= first
                split = [("기본", first), ("연장", n - first)]
            t = a
            for kind, m in split:
                if m > 0:
                    pieces.append((t, t + timedelta(minutes=m), kind, is_night(a), kind_of_day))
                    t += timedelta(minutes=m)
    return pieces


def summarize(pieces):
    """조각을 분류별 분으로 더한다. 겹치는 야간은 따로 센다 → 가산이 둘 다 붙는 시간"""
    total = dict.fromkeys(["기본", "연장", "휴일", "휴일8h초과", "야간", "연장·야간", "휴일·야간"], 0)
    for a, b, kind, night, _ in pieces:
        n = minutes(a, b)
        total[kind] += n
        if night:
            total["야간"] += n
            if kind == "연장":
                total["연장·야간"] += n
            elif kind != "기본":
                total["휴일·야간"] += n
    return total


def over_week_max(total_minutes):
    """R5 — 1주 총 근로(휴일근로 포함)가 52시간을 넘은 분"""
    return max(0, total_minutes - WEEK_MAX)


# ---- R1·R6·R8·R9 급여 ----
#  금액은 Fraction으로 끝까지 정확히 계산하고, 마지막에만 끝수를 처리한다

def hourly_equivalent(pay_type, base, monthly_fixed, monthly_hours):
    """월 고정액을 시간당으로 환산한 시급
    월급제: (기본급 + 고정수당) ÷ 월 소정근로시간 / 시급제: 시급 + 고정수당 ÷ 월 소정근로시간
    """
    if pay_type == "월급":
        return Fraction(base + monthly_fixed) / Fraction(monthly_hours)
    return Fraction(base) + Fraction(monthly_fixed) / Fraction(monthly_hours)


def ordinary_hourly(pay_type, base, fixed, ordinary_codes, monthly_hours):
    """R1 통상시급 — 통상임금에 들어가는 고정수당만 더한다 (근로기준법 시행령 제6조)"""
    extra = sum(v for k, v in fixed.items() if k in ordinary_codes)
    return hourly_equivalent(pay_type, base, extra, monthly_hours)


def min_wage_hourly(pay_type, base, fixed, monthly_hours):
    """R8 최저임금 비교용 시급 — 매월 정기 지급하는 수당·복리후생비는 전액 산입
    (최저임금법 제6조 제4항, 2024년부터 전액) [원문 확인 필요]"""
    return hourly_equivalent(pay_type, base, sum(fixed.values()), monthly_hours)


def weekly_holiday_hours(weekly_hours):
    """R6 주휴 1일의 시간 = 1주 소정근로시간 ÷ 40 × 8, 최대 8. 주 15시간 미만이면 없음 (제18조 제3항)"""
    if weekly_hours < 15:
        return Fraction(0)
    return min(Fraction(8), Fraction(weekly_hours) / 40 * 8)


def won_up(x):
    """지급액 끝수: 원 미만 올림 — 근로자에게 불리하지 않게 (회사 기준)"""
    return math.ceil(x)


def won_down10(x):
    """4대보험료 끝수: 10원 미만 절사 [공단별 끝수 처리 원문 확인 필요]"""
    return int(x // 10 * 10)


def social_insurance(taxable, rate, pension_health=True, covered=True):
    """R9 4대보험 근로자 부담분 → [(코드, 금액, 계산 근거)]

    taxable         보수월액으로 볼 과세 급여 (단순화: 신고한 보수월액 대신 그달 과세 급여)
    rate            요율표 한 줄 (%, 장기요양은 건강보험료 대비 %)
    pension_health  False면 국민연금·건강·장기요양 제외 (월 중 취득 → 다음 달부터)
    covered         False면 국민연금·건강·고용 모두 제외 (월 소정근로 60시간 미만)
    """
    t = Fraction(taxable)
    out = []
    if covered and pension_health:
        p = won_down10(t * Fraction(str(rate["pension_rate"])) / 100)
        h = won_down10(t * Fraction(str(rate["health_rate"])) / 100)
        l = won_down10(h * Fraction(str(rate["ltc_rate"])) / 100)
        out += [("D01", p, f"과세 급여 {taxable:,}원 × {rate['pension_rate']}% → 10원 미만 절사"),
                ("D02", h, f"과세 급여 {taxable:,}원 × {rate['health_rate']}% → 10원 미만 절사"),
                ("D03", l, f"건강보험료 {h:,}원 × {rate['ltc_rate']}% → 10원 미만 절사")]
    else:
        why = "월 소정근로 60시간 미만 → 적용 제외 [원문 확인 필요]" if not covered else "월 중 입사 → 다음 달부터 [원문 확인 필요]"
        out += [(c, 0, why) for c in ("D01", "D02", "D03")]
    if covered:
        e = won_down10(t * Fraction(str(rate["employment_rate"])) / 100)
        out.append(("D04", e, f"과세 급여 {taxable:,}원 × {rate['employment_rate']}% → 10원 미만 절사"))
    else:
        out.append(("D04", 0, "월 소정근로 60시간 미만 → 적용 제외 [원문 확인 필요]"))
    return out


# ---- R9 소득세 — 근로소득 간이세액표 ----
#  소득세법 시행령 [별표 2] (개정 2026. 2. 27., 2026년 3월 1일 이후 원천징수분부터)
#  표의 숫자는 erp/tax/간이세액표_2026-03.csv, 표 밖의 규칙은 여기에 둔다

# 월급여 10,000천원 초과: (상한, 더하는 고정액, 기준 금액, 기준 초과분에 곱하는 비율) — 별표 2 제6호 끝
OVER_10M = [
    (14_000_000, 25_000, 10_000_000, Fraction(98, 100) * Fraction(35, 100)),
    (28_000_000, 1_397_000, 14_000_000, Fraction(98, 100) * Fraction(38, 100)),
    (30_000_000, 6_610_600, 28_000_000, Fraction(98, 100) * Fraction(40, 100)),
    (45_000_000, 7_394_600, 30_000_000, Fraction(40, 100)),
    (87_000_000, 13_394_600, 45_000_000, Fraction(42, 100)),
    (None, 31_034_600, 87_000_000, Fraction(45, 100)),
]


def over_10m_extra(monthly):
    """10,000천원 행 세액에 더할 금액과 그 계산식"""
    for upper, fixed, base, rate in OVER_10M:
        if upper is None or monthly <= upper:
            extra = fixed + (monthly - base) * rate
            return extra, f"{fixed:,}원 + ({monthly:,} − {base:,})원 × {float(rate) * 100:g}%"


def child_deduction(children):
    """8세 이상 20세 이하 자녀 공제 (별표 2 제3호)"""
    if children <= 0:
        return 0
    if children == 1:
        return 20_830
    return 45_830 + 33_330 * (children - 2)


def simplified_tax(monthly, family, children, pct, rows, anchor):
    """R9 소득세 원천징수액 → (소득세, 계산 근거)

    monthly   월급여액 (비과세·학자금 제외, 원)
    family    공제대상가족 수 (본인·배우자 각 1명 포함, 별표 2 제2호)
    children  그중 8세 이상 20세 이하 자녀 수
    pct       근로자가 고른 원천징수 비율 80·100·120 [원문 확인 필요]
    rows      [(이상 원, 미만 원, (가족1~11 세액))] — 오름차순
    anchor    월급여가 정확히 10,000천원일 때 (가족1~11 세액)
    """
    if monthly < rows[0][0]:
        return 0, f"월급여(비과세 제외) {monthly:,}원 — 표 최저 구간 {rows[0][0] // 1000:,}천원 미만 → 0원"

    if monthly < 10_000_000:
        lo, hi, by = rows[bisect.bisect_right([r[0] for r in rows], monthly) - 1]
        where = f"간이세액표 {lo // 1000:,}~{hi // 1000:,}천원 구간"
        per = lambda f: Fraction(by[f - 1])
    elif monthly == 10_000_000:
        where = "간이세액표 10,000천원 행"
        per = lambda f: Fraction(anchor[f - 1])
    else:
        extra, how = over_10m_extra(monthly)
        where = f"10,000천원 행 + [{how}]"
        per = lambda f: anchor[f - 1] + extra

    if family <= 11:
        tax = per(family)
        text = f"월급여(비과세 제외) {monthly:,}원 → {where} · 가족 {family}명 = {num_won(tax)}원"
    else:                                           # 11명 초과 (별표 2 제4호)
        tax = max(Fraction(0), per(11) - (per(10) - per(11)) * (family - 11))
        text = (f"월급여(비과세 제외) {monthly:,}원 → {where} · 가족 {family}명 = 11명 {num_won(per(11))}원 − "
                f"(10명 {num_won(per(10))} − 11명 {num_won(per(11))}) × {family - 11} = {num_won(tax)}원")

    cut = child_deduction(children)
    if cut:
        tax = max(Fraction(0), tax - cut)
        text += f" − 8~20세 자녀 {children}명 {cut:,}원 = {num_won(tax)}원"
    if pct != 100:                                  # 100% 세액을 먼저 절사한 뒤 비율을 곱한다 (홈택스 계산기와 같은 순서)
        if tax != won_down10(tax):
            tax = Fraction(won_down10(tax))
            text += f" → 10원 미만 절사 {num_won(tax)}원"
        tax = tax * pct / 100
        text += f" × 원천징수 비율 {pct}% = {num_won(tax)}원"
    income_tax = won_down10(tax)
    return income_tax, text + " → 10원 미만 절사"


def num_won(x):
    """세액 표시: 정수면 그대로, 아니면 소수 둘째 자리"""
    return f"{int(x):,}" if x == int(x) else f"{float(x):,.2f}"
