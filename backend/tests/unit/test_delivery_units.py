"""Delivery rules without a database (module 12; RE-026 B1)."""

import pytest
from pydantic import ValidationError

from app.models.operations import DELIVERY_DISTRICTS
from app.schemas.delivery import DeliveryZoneCreateRequest, DeliveryZoneUpdateRequest
from app.schemas.settings import SettingsUpdateRequest
from app.services.delivery_service import delivery_fee, normalise_district


@pytest.mark.parametrize(
    ("subtotal", "expected"),
    [(0, 2000), (1, 2000), (199_999, 2000), (200_000, 0), (200_001, 0), (10**12 - 1, 0)],
)
def test_free_at_or_above_the_threshold(subtotal, expected):
    assert delivery_fee(2000, 200_000, subtotal) == expected


def test_a_zero_threshold_makes_every_delivery_free():
    assert delivery_fee(1500, 0, 0) == 0


def test_only_the_three_kigali_districts_are_supported():
    assert DELIVERY_DISTRICTS == ("Gasabo", "Kicukiro", "Nyarugenge")
    assert normalise_district("  kIcUkIrO ") == "Kicukiro"
    for value in (None, "", "Musanze", "Gasabo district", "Nyarugenge,", "Kigali"):
        assert normalise_district(value) is None


def test_zone_requests_refuse_extra_and_immutable_fields():
    ok = {"code": "gasabo", "name": "Gasabo", "district": "Gasabo", "fee": 2000}
    assert DeliveryZoneCreateRequest.model_validate(ok).cod_available is True
    with pytest.raises(ValidationError):
        DeliveryZoneCreateRequest.model_validate({**ok, "coverage": {}})
    for body in ({}, {"code": "x"}, {"district": "Gasabo"}, {"fee": None}, {"fee": 1.0}):
        with pytest.raises(ValidationError):
            DeliveryZoneUpdateRequest.model_validate(body)


def test_settings_request_uses_the_dotted_key_only():
    req = SettingsUpdateRequest.model_validate({"delivery.free_delivery_threshold": 5})
    assert req.changes() == {"delivery.free_delivery_threshold": 5}
    for body in ({"free_delivery_threshold": 5}, {}, {"delivery.free_delivery_threshold": "5"}):
        with pytest.raises(ValidationError):
            SettingsUpdateRequest.model_validate(body)
