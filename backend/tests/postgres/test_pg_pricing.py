"""RE-026 S1 merchandise pricing on the least-privilege runtime role (no new grants needed)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.inventory import InsufficientStock
from app.services.pricing import quote_merchandise
from tests.postgres.conftest import Stack
from tests.postgres.test_pg_inventory import seed_sku


@pytest.fixture(scope="module")
def runtime_sessions(stack: Stack):
    engine = create_engine(stack.runtime_url)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_runtime_role_can_quote_from_catalogue_and_stock_reads_only(stack: Stack, runtime_sessions):
    variant_id, _, _ = seed_sku(stack, on_hand=2)  # price 1000 RWF
    with runtime_sessions() as s:
        result = quote_merchandise(s, [(variant_id, 2)])
        assert result.merchandise_subtotal == 2000
        with pytest.raises(InsufficientStock):
            quote_merchandise(s, [(variant_id, 3)])
