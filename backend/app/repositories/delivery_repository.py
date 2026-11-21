"""Delivery zone and fee-rule queries (module 12). Repositories only flush; services commit."""

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import DeliveryFeeRule, DeliveryZone


def zones(db: Session, *, active_only: bool) -> list[DeliveryZone]:
    query = select(DeliveryZone).order_by(DeliveryZone.sort_order, DeliveryZone.name)
    if active_only:
        query = query.where(DeliveryZone.is_active.is_(True))
    return list(db.scalars(query))


def zone(db: Session, zone_id: uuid.UUID, *, lock: bool = False) -> DeliveryZone | None:
    query = select(DeliveryZone).where(DeliveryZone.id == zone_id)
    if lock:  # and refresh a copy already loaded in this session
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def zone_by_code(db: Session, code: str) -> DeliveryZone | None:
    return db.scalar(select(DeliveryZone).where(DeliveryZone.code == code))


def zone_by_district(db: Session, district: str) -> DeliveryZone | None:
    return db.scalar(select(DeliveryZone).where(DeliveryZone.district == district))


def code_taken(db: Session, code: str) -> bool:
    return db.scalar(select(DeliveryZone.id).where(DeliveryZone.code == code)) is not None


def district_taken(db: Session, district: str) -> bool:
    return db.scalar(select(DeliveryZone.id).where(DeliveryZone.district == district)) is not None


def active_rule(db: Session, zone_id: uuid.UUID, *, lock: bool = False) -> DeliveryFeeRule | None:
    """The zone's active rule (at most one, by the partial unique index), in force or not."""
    query = select(DeliveryFeeRule).where(
        DeliveryFeeRule.zone_id == zone_id, DeliveryFeeRule.is_active.is_(True)
    )
    if lock:  # and refresh a copy already loaded in this session
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def current_fees(db: Session, zone_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Fee of each zone's active rule whose window includes this statement's start time.

    statement_timestamp(), not now(): under READ COMMITTED a statement sees rules committed after
    its transaction began, whose starts_at (taken after the writer's lock) can be later than
    now(), but never later than the start of a statement that can see them."""
    if not zone_ids:
        return {}
    now = func.statement_timestamp()
    query = select(DeliveryFeeRule.zone_id, DeliveryFeeRule.fee).where(
        DeliveryFeeRule.zone_id.in_(zone_ids),
        DeliveryFeeRule.is_active.is_(True),
        or_(DeliveryFeeRule.starts_at.is_(None), DeliveryFeeRule.starts_at <= now),
        or_(DeliveryFeeRule.ends_at.is_(None), DeliveryFeeRule.ends_at > now),
    )
    return {zone_id: fee for zone_id, fee in db.execute(query)}


def fee_history(db: Session, zone_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DeliveryFeeRule]]:
    """Every rule of each zone, newest first: by starts_at, the instant read after the zone lock
    (created_at is the transaction start, so it can disagree under concurrency)."""
    history: dict[uuid.UUID, list[DeliveryFeeRule]] = defaultdict(list)
    if not zone_ids:
        return history
    query = (
        select(DeliveryFeeRule)
        .where(DeliveryFeeRule.zone_id.in_(zone_ids))
        .order_by(
            DeliveryFeeRule.starts_at.desc().nulls_last(),
            DeliveryFeeRule.created_at.desc(),
            DeliveryFeeRule.id,
        )
    )
    for rule in db.scalars(query):
        history[rule.zone_id].append(rule)
    return history
