"""Promotion rules without a database (module 13; RE-026 B3; ADR-007)."""

import uuid
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.kigali_time import (
    KIGALI,
    AmbiguousLocalTime,
    NonexistentLocalTime,
    local_to_utc,
    to_kigali,
)
from app.schemas.promotions import (
    ApplyCodeRequest,
    PromotionCreateRequest,
    PromotionTarget,
    PromotionUpdateRequest,
)
from app.services.promotion_service import (
    EXPIRED,
    NOT_STARTED,
    allocate,
    discount_amount,
    round_half_down,
    window_problem,
)

A, B, C = (uuid.UUID(int=i) for i in range(1, 4))


# ---- ADR-007 rounding ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(9045, 10), 904),  # exact half: down, in the customer's favour
        (Fraction(9046, 10), 905),
        (Fraction(9044, 10), 904),
        (Fraction(1, 2), 0),
        (Fraction(3, 2), 1),
        (Fraction(7), 7),
        (Fraction(0), 0),
    ],
)
def test_round_half_down(value, expected):
    assert round_half_down(value) == expected


def test_round_half_down_refuses_negative_amounts():
    with pytest.raises(ValueError):
        round_half_down(Fraction(-1, 2))


def test_adr_007_example_10_percent_off_1005_pays_904():
    discount = discount_amount("percent", 10, None, None, 1005)
    assert discount == 101 and 1005 - discount == 904


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("percent", 100, None, None, 1005), 1005),  # 100%: pays 0, never negative
        (("percent", 1, None, None, 50), 1),  # payable round_half_down(49.5) = 49
        (("percent", 15, None, 100, 10_000), 100),  # max_discount caps a percentage
        (("fixed", None, 5_000, None, 3_000), 3_000),  # never more than the eligible subtotal
        (("fixed", None, 5_000, 4_000, 10_000), 4_000),  # max_discount caps a fixed amount
        (("fixed", None, 500, None, 0), 0),  # nothing eligible
        (("percent", 10, None, None, 0), 0),
    ],
)
def test_discount_amount(args, expected):
    result = discount_amount(*args)
    assert result == expected
    assert 0 <= result <= args[4]


# ---- proportional allocation ---------------------------------------------------------------
def test_allocation_is_proportional_with_the_remainder_on_the_largest_line():
    lines = [(A, 1000), (B, 3000), (C, 2000)]
    shares = allocate(101, lines)
    assert shares == {A: 16, B: 52, C: 33}  # floors 16, 50, 33; the remainder 2 goes to B
    assert sum(shares.values()) == 101


def test_allocation_remainder_ties_go_to_the_earliest_largest_line():
    shares = allocate(7, [(A, 3), (B, 3), (C, 3)])  # floors 2, 2, 2; remainder 1
    assert shares == {A: 3, B: 2, C: 2}


def test_allocation_never_exceeds_a_lines_amount():
    shares = allocate(2, [(A, 1), (B, 1), (C, 1)])
    assert shares == {A: 1, B: 1, C: 0}
    assert all(shares[k] <= 1 for k in shares)


@pytest.mark.parametrize("total", [0, 1, 7, 333, 999, 1000])
def test_allocation_always_sums_to_the_discount(total):
    lines = [(A, 101), (B, 299), (C, 600)]
    shares = allocate(total, lines)
    assert sum(shares.values()) == total
    assert all(0 <= shares[k] <= amount for k, amount in lines)


def test_allocation_refuses_a_discount_above_the_subtotal():
    with pytest.raises(ValueError):
        allocate(11, [(A, 10)])


# ---- window boundaries ---------------------------------------------------------------------
def test_the_window_starts_inclusive_and_ends_exclusive():
    start = datetime(2026, 10, 31, 22, 0, tzinfo=UTC)  # 2026-11-01 00:00 in Kigali
    end = datetime(2026, 11, 30, 22, 0, tzinfo=UTC)
    tick = timedelta(microseconds=1)
    assert window_problem(start, end, start - tick) == NOT_STARTED
    assert window_problem(start, end, start) is None
    assert window_problem(start, end, end - tick) is None
    assert window_problem(start, end, end) == EXPIRED
    assert window_problem(None, None, start) is None


# ---- Kigali time ---------------------------------------------------------------------------
def test_kigali_local_time_is_stored_in_utc():
    assert KIGALI.key == "Africa/Kigali"  # needs tzdata on Windows
    assert local_to_utc(datetime(2026, 11, 1, 0, 0)) == datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
    assert local_to_utc(datetime(2026, 11, 1, 23, 59, 59)) == datetime(
        2026, 11, 1, 21, 59, 59, tzinfo=UTC
    )
    aware = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    assert local_to_utc(aware) == aware  # an explicit offset is taken as given
    shown = to_kigali(datetime(2026, 10, 31, 22, 0, tzinfo=UTC))
    assert shown is not None and shown.isoformat() == "2026-11-01T00:00:00+02:00"


def test_ambiguous_and_missing_local_times_are_refused_not_guessed():
    berlin = ZoneInfo("Europe/Berlin")  # Kigali has no such times; a DST zone proves the check
    with pytest.raises(AmbiguousLocalTime):
        local_to_utc(datetime(2026, 10, 25, 2, 30), berlin)
    with pytest.raises(NonexistentLocalTime):
        local_to_utc(datetime(2026, 3, 29, 2, 30), berlin)


# ---- request schemas -----------------------------------------------------------------------
BASE = {"code": "welcome10", "name": "Welcome", "kind": "percent", "percent_off": 10}


def test_codes_are_trimmed_and_upper_cased():
    assert PromotionCreateRequest.model_validate({**BASE, "code": "  wel-come_10 "}).code == (
        "WEL-COME_10"
    )
    assert ApplyCodeRequest.model_validate({"code": " welcome10 "}).code == "WELCOME10"


@pytest.mark.parametrize(
    "change",
    [
        {"code": "ab"},
        {"code": "has space"},
        {"code": "-LEADING"},
        {"code": "x" * 41},
        {"code": "CAFÉ"},
        {"kind": "bogo"},
        {"percent_off": 0},
        {"percent_off": 101},
        {"percent_off": 10.0},
        {"percent_off": "10"},
        {"percent_off": True},
        {"percent_off": None},
        {"amount_off": 500},  # a percent promotion takes no amount_off
        {"kind": "fixed", "amount_off": 0, "percent_off": None},
        {"min_subtotal": -1},
        {"max_discount": 0},
        {"usage_limit_total": 0},
        {"usage_limit_per_customer": -2},
        {"status": "expired"},
        {"applies_to": "targets"},  # needs targets
        {"targets": [{"product_id": str(A)}]},  # 'all' takes none
        {"starts_at": "2026-11-02T00:00:00", "ends_at": "2026-11-01T00:00:00"},
        {"starts_at": "2026-11-01T00:00:00", "ends_at": "2026-11-01T00:00:00"},
        {"value": 10},
        {"rules": {}},
    ],
)
def test_create_request_refuses_invalid_input(change):
    with pytest.raises(ValidationError):
        PromotionCreateRequest.model_validate({**BASE, **change})


def test_targets_name_exactly_one_thing_and_are_not_repeated():
    with pytest.raises(ValidationError):
        PromotionTarget.model_validate({})
    with pytest.raises(ValidationError):
        PromotionTarget.model_validate({"product_id": str(A), "brand_id": str(B)})
    with pytest.raises(ValidationError):
        PromotionTarget.model_validate({"variant_id": str(A)})
    with pytest.raises(ValidationError):
        PromotionCreateRequest.model_validate(
            {
                **BASE,
                "applies_to": "targets",
                "targets": [{"product_id": str(A)}, {"product_id": str(A)}],
            }
        )


def test_window_dates_are_read_as_kigali_time():
    req = PromotionCreateRequest.model_validate(
        {**BASE, "starts_at": "2026-11-01T00:00:00", "ends_at": "2026-11-01T08:00:00+02:00"}
    )
    assert req.starts_at == datetime(2026, 10, 31, 22, 0, tzinfo=UTC)
    assert req.ends_at == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


def test_update_request_rules():
    assert PromotionUpdateRequest.model_validate({"max_discount": None}).max_discount is None
    for body in ({}, {"code": None}, {"status": None}, {"targets": None}, {"code": "x"}):
        with pytest.raises(ValidationError):
            PromotionUpdateRequest.model_validate(body)
