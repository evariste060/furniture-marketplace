"""Delivery zones, fees and quotes (module 12; plan §5; RE-026 B1, B5, B6).

Rules (B1):
- One zone per supported district: Gasabo, Kicukiro, Nyarugenge. An address in any other
  district cannot be delivered to. The district is matched exactly, ignoring letter case and
  surrounding spaces; nothing else is guessed.
- One flat, VAT-inclusive fee per zone. Delivery is free when the merchandise subtotal after
  discount is at least the free-delivery threshold (the delivery.free_delivery_threshold
  setting): 199 999 pays the fee and 200 000 is free at a 200 000 threshold.
- A quote needs an active zone, its current fee rule and the threshold. A missing fee or
  threshold is never replaced by a default: the quote is refused (DeliveryQuoteUnavailable).
- Fees, thresholds and totals come from the database only; callers pass the subtotal they got
  from the pricing service, never an amount from a client.

Fee history: changing a fee closes the active rule (is_active false) and adds a new rule, in
one transaction with the audit record. The zone row is locked FOR UPDATE first, so concurrent
changes are serialised, and the partial unique index (one active rule per zone) is the database
backstop. Rules are never edited in place or deleted.

Timestamps: the old rule's ends_at and the new rule's starts_at are one clock_timestamp() read
after the locks are held. now() would not do: it is fixed when the transaction starts, and a
request's transaction starts (authentication reads) before it waits for the zone lock, so a
request that started earlier but got the lock later would end the newer rule before it began.
If the active rule still starts at or after that instant (clock skew, or a legacy rule dated in
the future), nothing is written and the change is refused with 409 fee_change_conflict; a
valid_window violation is reported the same way. Other integrity errors are re-raised.

Staff changes ('delivery:manage', administrators only, B6) are audited as
'delivery.zone_create' and 'delivery.zone_update' (with old and new values); a request that
changes nothing is not audited. Code and district are fixed once a zone exists (D-D2).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import DeliveryFeeRule, DeliveryZone
from app.models.common import MAX_MONEY_RWF
from app.models.identity import User
from app.models.operations import DELIVERY_DISTRICTS
from app.repositories import delivery_repository as repo
from app.schemas.delivery import (
    DeliveryZoneCreateRequest,
    DeliveryZoneUpdateRequest,
    FeeRuleResponse,
    PublicDeliveryZone,
    PublicDeliveryZonesResponse,
    StaffDeliveryZone,
    StaffDeliveryZonesResponse,
)
from app.services.audit_service import AuditService
from app.services.settings_service import free_delivery_threshold

ZONE_NOT_FOUND = "Delivery zone not found."
CODE_TAKEN = "This code is already used by another delivery zone."
DISTRICT_TAKEN = "This district already has a delivery zone."
FEE_MISSING = "The zone has no current fee; send a fee to activate it."
FEE_CONFLICT = "The fee was changed at the same time by another request; try again."
FEE_WINDOW_CONSTRAINT = "ck_delivery_fee_rules_valid_window"


class DeliveryError(Exception):
    """Base class for delivery quote refusals; messages are safe to show."""


class DeliveryZoneUnavailable(DeliveryError):
    """Unknown or inactive zone, or a district outside the delivery area."""

    def __init__(self, message: str = "Delivery is not available for this zone.") -> None:
        super().__init__(message)


class DeliveryQuoteUnavailable(DeliveryError):
    """The zone exists but its fee or the free-delivery threshold is not configured."""

    def __init__(self) -> None:
        super().__init__("Delivery cannot be quoted right now: its configuration is incomplete.")


@dataclass(frozen=True)
class DeliveryQuote:
    zone_code: str
    zone_name: str
    district: str
    cod_available: bool
    zone_fee: int  # the zone's current fee
    delivery_fee: int  # what the customer pays: 0 at or above the threshold
    free_delivery: bool
    free_delivery_threshold: int


def normalise_district(value: str | None) -> str | None:
    """The supported district this text names (any letter case, trimmed), else None."""
    if value is None:
        return None
    wanted = value.strip().casefold()
    return next((d for d in DELIVERY_DISTRICTS if d.casefold() == wanted), None)


def delivery_fee(zone_fee: int, threshold: int, subtotal_after_discount: int) -> int:
    """B1: free when the subtotal after discount is at least the threshold."""
    return 0 if subtotal_after_discount >= threshold else zone_fee


def _check_subtotal(subtotal_after_discount: int) -> None:
    if (
        not isinstance(subtotal_after_discount, int)
        or isinstance(subtotal_after_discount, bool)
        or not 0 <= subtotal_after_discount <= MAX_MONEY_RWF
    ):
        raise ValueError("subtotal_after_discount must be whole RWF within the storable range")


def _quote(db: Session, zone: DeliveryZone | None, subtotal_after_discount: int) -> DeliveryQuote:
    _check_subtotal(subtotal_after_discount)
    if zone is None or not zone.is_active:
        raise DeliveryZoneUnavailable()
    fee = repo.current_fees(db, [zone.id]).get(zone.id)
    threshold = free_delivery_threshold(db)
    if fee is None or threshold is None:
        raise DeliveryQuoteUnavailable()
    charged = delivery_fee(fee, threshold, subtotal_after_discount)
    return DeliveryQuote(
        zone_code=zone.code,
        zone_name=zone.name,
        district=zone.district,
        cod_available=zone.cod_available,
        zone_fee=fee,
        delivery_fee=charged,
        free_delivery=subtotal_after_discount >= threshold,
        free_delivery_threshold=threshold,
    )


def quote_for_zone(db: Session, code: str, subtotal_after_discount: int) -> DeliveryQuote:
    """Quote by zone code (the cart estimate). Raises DeliveryZoneUnavailable or
    DeliveryQuoteUnavailable."""
    return _quote(db, repo.zone_by_code(db, code), subtotal_after_discount)


def quote_for_district(db: Session, district: str, subtotal_after_discount: int) -> DeliveryQuote:
    """Quote from a delivery address district (checkout, module 14). A district outside the
    three is refused with DeliveryZoneUnavailable."""
    name = normalise_district(district)
    if name is None:
        raise DeliveryZoneUnavailable("Delivery is not available in this district.")
    return _quote(db, repo.zone_by_district(db, name), subtotal_after_discount)


# ---- staff views and changes ---------------------------------------------------------------
def _staff_zone(zone: DeliveryZone, history: list[DeliveryFeeRule], fee: int | None):
    return StaffDeliveryZone(
        id=zone.id,
        code=zone.code,
        name=zone.name,
        district=zone.district,  # type: ignore[arg-type]
        cod_available=zone.cod_available,
        sort_order=zone.sort_order,
        is_active=zone.is_active,
        fee=fee,
        fee_history=[FeeRuleResponse.model_validate(rule) for rule in history],
        created_at=zone.created_at,
        updated_at=zone.updated_at,
    )


def _staff_view(db: Session, zone: DeliveryZone) -> StaffDeliveryZone:
    db.refresh(zone)
    return _staff_zone(
        zone,
        repo.fee_history(db, [zone.id]).get(zone.id, []),
        repo.current_fees(db, [zone.id]).get(zone.id),
    )


def _constraint(exc: IntegrityError) -> str:
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""


def _integrity_conflict(exc: IntegrityError) -> Conflict:
    name = _constraint(exc)
    if name == "delivery_zone_code":
        return Conflict(CODE_TAKEN, code="zone_code_taken")
    if name == "delivery_zone_district":
        return Conflict(DISTRICT_TAKEN, code="zone_district_taken")
    if name in ("uq_delivery_fee_rules_one_active_per_zone", FEE_WINDOW_CONSTRAINT):
        return Conflict(FEE_CONFLICT, code="fee_change_conflict")
    raise exc


def _audit(
    db: Session,
    action: str,
    zone_id: uuid.UUID,
    actor: User,
    ctx: RequestContext,
    details: dict[str, Any],
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="delivery_zone",
        entity_id=zone_id,
        context=ctx,
        details=details,
    )


def _locked_instant(db: Session) -> datetime:
    """The database's current time, read now: call it only once the locks are held."""
    return db.execute(select(func.clock_timestamp())).scalar_one()


def _new_rule(db: Session, zone_id: uuid.UUID, fee: int, starts_at: datetime) -> DeliveryFeeRule:
    rule = DeliveryFeeRule(zone_id=zone_id, fee=fee, starts_at=starts_at, is_active=True)
    db.add(rule)
    db.flush()
    return rule


class DeliveryService:
    @staticmethod
    def public_zones(db: Session) -> PublicDeliveryZonesResponse:
        """Active zones that have a current fee; the threshold, or null when unset."""
        active = repo.zones(db, active_only=True)
        fees = repo.current_fees(db, [z.id for z in active])
        return PublicDeliveryZonesResponse(
            items=[
                PublicDeliveryZone(
                    code=z.code,
                    name=z.name,
                    district=z.district,  # type: ignore[arg-type]
                    fee=fees[z.id],
                    cod_available=z.cod_available,
                )
                for z in active
                if z.id in fees
            ],
            free_delivery_threshold=free_delivery_threshold(db),
        )

    @staticmethod
    def staff_zones(db: Session) -> StaffDeliveryZonesResponse:
        every = repo.zones(db, active_only=False)
        ids = [z.id for z in every]
        history = repo.fee_history(db, ids)
        fees = repo.current_fees(db, ids)
        return StaffDeliveryZonesResponse(
            items=[_staff_zone(z, history.get(z.id, []), fees.get(z.id)) for z in every]
        )

    @staticmethod
    def create_zone(
        db: Session, actor: User, req: DeliveryZoneCreateRequest, ctx: RequestContext
    ) -> StaffDeliveryZone:
        try:
            with atomic(db):
                if repo.code_taken(db, req.code):
                    raise Conflict(CODE_TAKEN, code="zone_code_taken")
                if repo.district_taken(db, req.district):
                    raise Conflict(DISTRICT_TAKEN, code="zone_district_taken")
                zone = DeliveryZone(
                    code=req.code,
                    name=req.name,
                    district=req.district,
                    cod_available=req.cod_available,
                    sort_order=req.sort_order,
                    is_active=req.is_active,
                )
                db.add(zone)
                db.flush()
                rule = _new_rule(db, zone.id, req.fee, _locked_instant(db))
                _audit(
                    db,
                    "delivery.zone_create",
                    zone.id,
                    actor,
                    ctx,
                    {
                        "code": zone.code,
                        "district": zone.district,
                        "fee": req.fee,
                        "fee_rule_id": str(rule.id),
                        "cod_available": zone.cod_available,
                        "is_active": zone.is_active,
                    },
                )
        except IntegrityError as exc:
            raise _integrity_conflict(exc) from None
        return _staff_view(db, zone)

    @staticmethod
    def update_zone(
        db: Session,
        actor: User,
        zone_id: uuid.UUID,
        req: DeliveryZoneUpdateRequest,
        ctx: RequestContext,
    ) -> StaffDeliveryZone:
        sent = req.model_dump(exclude_unset=True)
        try:
            with atomic(db):
                zone = repo.zone(db, zone_id, lock=True)
                if zone is None:
                    raise NotFound(ZONE_NOT_FOUND, code="delivery_zone_not_found")
                changes: dict[str, Any] = {}
                for field in ("name", "cod_available", "sort_order", "is_active"):
                    if field in sent and getattr(zone, field) != sent[field]:
                        changes[field] = {"from": getattr(zone, field), "to": sent[field]}
                        setattr(zone, field, sent[field])
                current = repo.active_rule(db, zone.id, lock=True)
                if "fee" in sent and (current is None or current.fee != sent["fee"]):
                    instant = _locked_instant(db)  # after the zone and rule locks
                    if current is not None:  # close it first: one active rule per zone
                        if current.starts_at is not None and current.starts_at >= instant:
                            raise Conflict(FEE_CONFLICT, code="fee_change_conflict")
                        current.is_active = False
                        current.ends_at = instant
                        db.flush()
                    rule = _new_rule(db, zone.id, sent["fee"], instant)
                    changes["fee"] = {
                        "from": current.fee if current is not None else None,
                        "to": sent["fee"],
                        "closed_rule_id": str(current.id) if current is not None else None,
                        "new_rule_id": str(rule.id),
                    }
                    current = rule
                if zone.is_active and current is None:
                    raise Conflict(FEE_MISSING, code="zone_fee_missing")
                if changes:
                    db.flush()
                    _audit(db, "delivery.zone_update", zone.id, actor, ctx, {"changes": changes})
        except IntegrityError as exc:
            raise _integrity_conflict(exc) from None
        return _staff_view(db, zone)
