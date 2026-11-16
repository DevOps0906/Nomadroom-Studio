"""판정 엔진 단위 테스트. 규칙 정본 `docs/01_PRD.md#9`, 해석 `tasks/task-005.md#구현 결정`."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.verdict import Candidate, Observation, Profile, Verdict, judge, pick_representative

T0 = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
PROFILE_ID = uuid.UUID("00000000-0000-4000-8000-000000000101")
CANDIDATE_ID = uuid.UUID("00000000-0000-4000-8000-000000000201")


def make_profile(**kw) -> Profile:
    base = dict(
        id=PROFILE_ID,
        market="KR",
        format="all",
        category=None,
        min_views=100_000,
        max_growth_pct=Decimal("5"),
        keywords=(),
        cc_only=False,
        include_broadcast=True,
    )
    return Profile(**(base | kw))


def make_candidate(**kw) -> Candidate:
    base = dict(
        id=CANDIDATE_ID,
        title="한마디에 분위기가 바뀐 순간",
        category="예능",
        format="long",
        market="KR",
        license_cc=True,
        is_broadcaster=False,
    )
    return Candidate(**(base | kw))


def obs(views: int, at: datetime) -> Observation:
    return Observation(id=uuid.uuid4(), observed_at=at, view_count=views)


def run(
    profile_kw=None,
    candidate_kw=None,
    prev_views: int | None = 200_000,
    curr_views: int = 201_000,
    gap: timedelta = timedelta(days=7),
) -> Verdict:
    prev = None if prev_views is None else obs(prev_views, T0)
    curr = obs(curr_views, T0 + gap)
    return judge(
        make_profile(**(profile_kw or {})), make_candidate(**(candidate_kw or {})), prev, curr
    )


# --- 순서 1: 조건 제외 -------------------------------------------------------


def test_market_mismatch():
    v = run(candidate_kw={"market": "JP"})
    assert (v.status, v.reason, v.growth_pct) == ("excluded", "market", None)


def test_category_mismatch():
    v = run(profile_kw={"category": "스포츠"})
    assert (v.status, v.reason) == ("excluded", "category")


def test_category_null_passes():
    assert run(profile_kw={"category": None}).status == "producible"


def test_category_match_passes():
    assert run(profile_kw={"category": "예능"}).status == "producible"


def test_format_mismatch():
    v = run(profile_kw={"format": "short"})
    assert (v.status, v.reason) == ("excluded", "format")


def test_format_match_and_all_pass():
    assert run(profile_kw={"format": "long"}).status == "producible"
    assert run(profile_kw={"format": "all"}).status == "producible"


def test_views_min_below():
    v = run(prev_views=99_000, curr_views=99_999)
    assert (v.status, v.reason) == ("excluded", "views_min")


def test_views_min_equal_passes():
    assert run(prev_views=100_000, curr_views=100_000).status == "producible"


def test_not_cc():
    v = run(profile_kw={"cc_only": True}, candidate_kw={"license_cc": False})
    assert (v.status, v.reason) == ("excluded", "not_cc")


def test_not_cc_ignored_when_not_cc_only():
    assert run(candidate_kw={"license_cc": False}).status == "producible"


def test_broadcaster_excluded():
    v = run(profile_kw={"include_broadcast": False}, candidate_kw={"is_broadcaster": True})
    assert (v.status, v.reason) == ("excluded", "broadcaster")


def test_broadcaster_allowed_when_included():
    assert run(candidate_kw={"is_broadcaster": True}).status == "producible"


def test_non_broadcaster_passes_when_excluding():
    assert run(profile_kw={"include_broadcast": False}).status == "producible"


def test_keyword_missing():
    v = run(profile_kw={"keywords": ("축구", "야구")})
    assert (v.status, v.reason) == ("excluded", "keyword")


def test_keyword_any_match_passes():
    assert run(profile_kw={"keywords": ("축구", "분위기")}).status == "producible"


def test_keyword_case_insensitive_and_nfkc():
    # 전각 "ＡＢＣ"는 NFKC로 "ABC", 대소문자 무시
    v = run(profile_kw={"keywords": ("abc",)}, candidate_kw={"title": "오늘의 ＡＢＣ 장면"})
    assert v.status == "producible"


def test_condition_reason_order_top_row_wins():
    v = run(
        profile_kw={
            "category": "스포츠",
            "format": "short",
            "cc_only": True,
            "include_broadcast": False,
            "keywords": ("없음",),
        },
        candidate_kw={"market": "JP", "license_cc": False, "is_broadcaster": True},
        curr_views=1,
        prev_views=1,
    )
    assert v.reason == "market"
    v = run(
        profile_kw={"cc_only": True, "include_broadcast": False, "keywords": ("없음",)},
        candidate_kw={"license_cc": False, "is_broadcaster": True},
        curr_views=1,
        prev_views=1,
    )
    assert v.reason == "views_min"


_BOTH_VIEWS_LOW = {"prev_views": 1, "curr_views": 1}


@pytest.mark.parametrize(
    ("profile_kw", "candidate_kw", "run_kw", "expected"),
    [
        ({"category": "스포츠"}, {"market": "JP"}, {}, "market"),
        ({"category": "스포츠", "format": "short"}, {}, {}, "category"),
        ({"format": "short"}, {}, _BOTH_VIEWS_LOW, "format"),
        ({"cc_only": True}, {"license_cc": False}, _BOTH_VIEWS_LOW, "views_min"),
        (
            {"cc_only": True, "include_broadcast": False},
            {"license_cc": False, "is_broadcaster": True},
            {},
            "not_cc",
        ),
        (
            {"include_broadcast": False, "keywords": ("없음",)},
            {"is_broadcaster": True},
            {},
            "broadcaster",
        ),
    ],
    ids=[
        "market>category",
        "category>format",
        "format>views_min",
        "views_min>not_cc",
        "not_cc>broadcaster",
        "broadcaster>keyword",
    ],
)
def test_condition_reason_adjacent_pair_order(profile_kw, candidate_kw, run_kw, expected):
    v = run(profile_kw=profile_kw, candidate_kw=candidate_kw, **run_kw)
    assert (v.status, v.reason) == ("excluded", expected)


def test_candidate_category_null_mismatches_set_category():
    v = run(profile_kw={"category": "예능"}, candidate_kw={"category": None})
    assert (v.status, v.reason) == ("excluded", "category")


def test_candidate_format_null_mismatches_set_format():
    v = run(profile_kw={"format": "long"}, candidate_kw={"format": None})
    assert (v.status, v.reason) == ("excluded", "format")


def test_condition_excluded_before_no_prev():
    v = run(candidate_kw={"market": "JP"}, prev_views=None)
    assert v.reason == "market"


# --- 순서 2: 근거 대기 -------------------------------------------------------


def test_no_prev():
    v = run(prev_views=None)
    assert (v.status, v.reason, v.growth_pct) == ("pending", "no_prev", None)


def test_license_unknown():
    v = run(profile_kw={"cc_only": True}, candidate_kw={"license_cc": None})
    assert (v.status, v.reason, v.growth_pct) == ("pending", "license_unknown", None)


def test_license_unknown_allowed_when_not_cc_only():
    assert run(candidate_kw={"license_cc": None}).status == "producible"


def test_no_prev_wins_over_license_unknown():
    v = run(profile_kw={"cc_only": True}, candidate_kw={"license_cc": None}, prev_views=None)
    assert v.reason == "no_prev"


@pytest.mark.parametrize(
    ("gap", "valid"),
    [
        (timedelta(hours=24), True),
        (timedelta(days=7), True),
        (timedelta(hours=24) - timedelta(seconds=1), False),
        (timedelta(days=7) + timedelta(seconds=1), False),
        (timedelta(0), False),
        (timedelta(days=-1), False),
    ],
)
def test_observation_interval_bounds(gap, valid):
    v = run(gap=gap)
    if valid:
        assert v.status == "producible"
    else:
        assert (v.status, v.reason) == ("pending", "no_prev")


# --- 순서 3: 증가율 ----------------------------------------------------------


def test_growth_zero_is_producible():
    v = run(prev_views=200_000, curr_views=200_000)
    assert (v.status, v.reason, v.growth_pct) == ("producible", None, Decimal("0.00"))


def test_growth_equal_to_max_is_producible():
    v = run(prev_views=200_000, curr_views=210_000)  # 정확히 5%
    assert (v.status, v.reason, v.growth_pct) == ("producible", None, Decimal("5.00"))


def test_growth_above_max_excluded():
    v = run(prev_views=200_000, curr_views=210_002)  # 5.001%
    assert (v.status, v.reason, v.growth_pct) == (
        "excluded",
        "growth_out_of_range",
        Decimal("5.00"),
    )


def test_growth_negative_excluded():
    v = run(prev_views=200_000, curr_views=199_990)  # -0.005%
    assert (v.status, v.reason, v.growth_pct) == (
        "excluded",
        "growth_out_of_range",
        Decimal("-0.01"),
    )


def test_growth_comparison_uses_unrounded_value():
    # 5.004% → 반올림 5.00이지만 비교는 반올림 전 값
    v = run(prev_views=100_000, curr_views=105_004)
    assert (v.status, v.growth_pct) == ("excluded", Decimal("5.00"))


def test_prev_zero_views_out_of_range():
    v = run(profile_kw={"min_views": 0}, prev_views=0, curr_views=10)
    assert (v.status, v.reason, v.growth_pct) == ("excluded", "growth_out_of_range", None)


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        Observation(id=uuid.uuid4(), observed_at=datetime(2026, 11, 9), view_count=1)


# --- 순서 4: 대표 판정 -------------------------------------------------------

P1, P2, P3 = (uuid.UUID(int=i) for i in (1, 2, 3))


def vd(profile_id: uuid.UUID, status: str) -> Verdict:
    reason = {"producible": None, "pending": "no_prev", "excluded": "market"}[status]
    return Verdict(
        candidate_id=CANDIDATE_ID,
        profile_id=profile_id,
        status=status,
        reason=reason,
        growth_pct=None,
        prev_observation_id=None,
        curr_observation_id=uuid.UUID(int=0),
    )


def test_rep_producible_first():
    r = pick_representative([vd(P1, "excluded"), vd(P2, "pending"), vd(P3, "producible")], False)
    assert (r.rep_status, r.rep_profile_id, r.used) == ("producible", P3, False)


def test_rep_pending_over_excluded():
    r = pick_representative([vd(P1, "excluded"), vd(P2, "pending"), vd(P3, "pending")], False)
    assert (r.rep_status, r.rep_profile_id) == ("pending", P2)


def test_rep_first_profile_when_all_excluded():
    r = pick_representative([vd(P1, "excluded"), vd(P2, "excluded")], False)
    assert (r.rep_status, r.rep_profile_id) == ("excluded", P1)


def test_rep_used_flag_kept_with_computed_status():
    r = pick_representative([vd(P1, "excluded"), vd(P2, "producible")], True)
    assert (r.rep_status, r.rep_profile_id, r.used) == ("producible", P2, True)


def test_rep_empty_raises():
    with pytest.raises(ValueError):
        pick_representative([], False)


# --- 시드 판정과 일치 (supabase/seed.sql 값을 상수로 옮김) ------------------------


def _u(n: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-{n:012d}")


SEED_PROFILES = [
    make_profile(id=_u(101), market="KR", min_views=100_000, max_growth_pct=Decimal("5"),
                 cc_only=True, include_broadcast=True),
    make_profile(id=_u(102), market="JP", min_views=100_000, max_growth_pct=Decimal("20"),
                 cc_only=False, include_broadcast=True),
]  # fmt: skip
SEED_PREV_AT = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
SEED_CURR_AT = datetime(2026, 11, 16, 3, 0, tzinfo=UTC)
# (candidate id, title, category, market, license_cc, used, prev views, curr views)
SEED_CANDIDATES = [
    (201, "한마디에 분위기가 바뀐 순간", "예능", "KR", True, False, 450_000, 452_700),
    (202, "마지막 동작이 갈랐던 승부", "스포츠", "KR", True, False, 710_000, 714_260),
    (203, "한 장면으로 설명하는 반전의 구조", "영화·드라마", "KR", None, False, None, 270_000),
    (204, "도시 산책 중 발견한 작은 반전", "일상", "JP", False, False, 200_000, 225_000),
    (205, "대화의 흐름이 바뀐 두 번째 장면", "예능", "KR", True, True, 300_000, 301_800),
]
# observations: candidate id → (prev observation id, curr observation id)
SEED_OBS_IDS = {
    201: (301, 302),
    202: (303, 304),
    203: (None, 306),
    204: (307, 308),
    205: (309, 310),
}
# candidate_verdicts: (candidate, profile) → (status, reason, growth_pct, prev obs, curr obs)
SEED_VERDICTS = {
    (201, 101): ("producible", None, Decimal("0.60"), 301, 302),
    (201, 102): ("excluded", "market", None, None, 302),
    (202, 101): ("producible", None, Decimal("0.60"), 303, 304),
    (202, 102): ("excluded", "market", None, None, 304),
    (203, 101): ("pending", "no_prev", None, None, 306),
    (203, 102): ("excluded", "market", None, None, 306),
    (204, 101): ("excluded", "market", None, None, 308),
    (204, 102): ("producible", None, Decimal("12.50"), 307, 308),
    (205, 101): ("producible", None, Decimal("0.60"), 309, 310),
    (205, 102): ("excluded", "market", None, None, 310),
}
# candidates: rep_status, rep_profile_id, used
SEED_REPS = {
    201: ("producible", 101, False),
    202: ("producible", 101, False),
    203: ("pending", 101, False),
    204: ("producible", 102, False),
    205: ("producible", 101, True),
}


def seed_obs(n: int, views: int, at: datetime) -> Observation:
    return Observation(id=_u(n), observed_at=at, view_count=views)


def test_matches_seed_verdicts():
    for cid, title, category, market, license_cc, used, prev_v, curr_v in SEED_CANDIDATES:
        c = make_candidate(
            id=_u(cid), title=title, category=category, format="long", market=market,
            license_cc=license_cc, is_broadcaster=False,
        )  # fmt: skip
        prev_id, curr_id = SEED_OBS_IDS[cid]
        prev = None if prev_v is None else seed_obs(prev_id, prev_v, SEED_PREV_AT)
        curr = seed_obs(curr_id, curr_v, SEED_CURR_AT)
        verdicts = [judge(p, c, prev, curr) for p in SEED_PROFILES]
        for p, v in zip(SEED_PROFILES, verdicts, strict=True):
            pid = int(str(p.id)[-3:])
            status, reason, growth, want_prev, want_curr = SEED_VERDICTS[(cid, pid)]
            expected = (status, reason, growth, want_prev and _u(want_prev), _u(want_curr))
            actual = (
                v.status, v.reason, v.growth_pct, v.prev_observation_id, v.curr_observation_id,
            )  # fmt: skip
            assert actual == expected, (cid, pid)
        rep = pick_representative(verdicts, used)
        status, rep_pid, rep_used = SEED_REPS[cid]
        assert (rep.rep_status, rep.rep_profile_id, rep.used) == (status, _u(rep_pid), rep_used)


def test_observation_ids_follow_prev_usage():
    prev, curr = obs(200_000, T0), obs(201_000, T0 + timedelta(days=7))
    ok = judge(make_profile(), make_candidate(), prev, curr)
    assert (ok.prev_observation_id, ok.curr_observation_id) == (prev.id, curr.id)
    unknown = judge(make_profile(cc_only=True), make_candidate(license_cc=None), prev, curr)
    assert (unknown.reason, unknown.prev_observation_id) == ("license_unknown", prev.id)
    far = obs(200_000, T0 - timedelta(days=1))
    no_prev = judge(make_profile(), make_candidate(), far, curr)
    assert (no_prev.reason, no_prev.prev_observation_id) == ("no_prev", None)
    cond = judge(make_profile(), make_candidate(market="JP"), prev, curr)
    assert (cond.reason, cond.prev_observation_id, cond.curr_observation_id) == (
        "market",
        None,
        curr.id,
    )
