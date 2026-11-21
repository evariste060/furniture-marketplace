"""Public inventory rule checks shared by pricing, cart and checkout (implementation plan A5)."""

import pytest

from app.services import inventory
from app.services.inventory import MAX_QUANTITY, check_quantity


@pytest.mark.parametrize("quantity", [1, 7, MAX_QUANTITY])
def test_check_quantity_accepts_whole_quantities_in_range(quantity):
    assert check_quantity(quantity, "line quantity") == quantity


@pytest.mark.parametrize(
    ("quantity", "message"),
    [
        (0, "line quantity must be between 1 and"),
        (-3, "line quantity must be between 1 and"),
        (MAX_QUANTITY + 1, "line quantity must be between 1 and"),
        (2.0, "line quantity must be an integer"),
        ("2", "line quantity must be an integer"),
        (True, "line quantity must be an integer"),
        (None, "line quantity must be an integer"),
    ],
)
def test_check_quantity_rejects_everything_else(quantity, message):
    with pytest.raises(ValueError, match=message):
        check_quantity(quantity, "line quantity")


def test_the_checks_are_public_and_the_private_names_are_gone():
    assert callable(inventory.check_quantity) and callable(inventory.check_sellable)
    assert not hasattr(inventory, "_check_quantity")
    assert not hasattr(inventory, "_check_sellable")
