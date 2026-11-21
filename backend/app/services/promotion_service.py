"""Promotion codes (module 13; plan §5; RE-026 B3, B6; ADR-007).

Rules (B3, ADR-007):
- One code per cart and per order. A code is a whole percentage (1-100) or a fixed whole-RWF
  amount, and applies to eligible merchandise only, never to the delivery fee.
- Eligible lines: every priced line for applies_to = 'all'; otherwise lines whose product is a
  target, whose brand is a target, or whose category is a target category or any subcategory of
  one. Lines that are not priced (unavailable, out of stock, out of range) are never eligible.
- Percentage (ADR-007): payable = round_half_down(eligible × (100 − percent) / 100) and
  discount = eligible − payable, so 10% off 1 005 pays 904 (discount 101). Fixed: the amount,
  never more than the eligible subtotal. max_discount then caps either kind. A total can never
  go negative.
- The discount is split across eligible lines in proportion to their amounts (rounded down);
  the remainder goes to the largest line (the earliest in cart order on a tie). The line
  discounts always add up to the discount, and no line gets more than its own amount (D-P4).
- Applicable only while status is 'active' and starts_at <= now < ends_at (database time; the
  window is entered in Africa/Kigali time and stored in UTC), when the whole merchandise
  subtotal before discount (every priced line, eligible or not; delivery excluded) is at least
  min_subtotal (D-P2, owner's implementation decision 2026-10-25), and while the usage limits
  allow it.
- Usage counts active redemptions only. A redemption is created at checkout (module 14, through
  redeem()), never by applying a code to a cart; redeem() locks the discount row FOR UPDATE and
  re-checks the total and per-customer limits, so two checkouts cannot take the same last use.
  Per customer means by account or canonical phone for registered customers and by phone for
  guests (§7 Q26). release_for_order() releases an order's active redemption when the order is
  cancelled before dispatch or its reservation expires; it is idempotent.

Staff changes ('promotions:manage', administrators only, B6) are audited as 'promotion.create'
and 'promotion.update' (old and new values); a request that changes nothing is not audited.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, field_error
from app.core.identifiers import validate_rwanda_phone
from app.core.kigali_time import to_kigali
from app.core.money import round_half_down
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import Brand, Category, Discount, DiscountRedemption, DiscountTarget, Product
from app.models.common import MAX_MONEY_RWF
from app.models.identity import User
from app.repositories import promotion_repository as repo
from app.schemas.pagination import Page, page_offset
from app.schemas.promotions import (
    PromotionCreateRequest,
    PromotionResponse,
    PromotionTarget,
    PromotionTargetResponse,
    PromotionUpdateRequest,
    consistency_problem,
)
from app.services.audit_service import AuditService

logger = logging.getLogger("app.promotions")

PROMOTION_NOT_FOUND = "Promotion not found."
CODE_TAKEN = "This code is already used by another promotion."
BACK_TO_DRAFT = "A promotion that has been activated or disabled cannot return to draft."
RELEASE_REASONS = frozenset({"cancelled", "expired"})

# Why a code does not apply right now (shown to the customer; stable for clients).
NOT_ACTIVE = "not_active"
NOT_STARTED = "not_started"
EXPIRED = "expired"
NO_ELIGIBLE_ITEMS = "no_eligible_items"
MINIMUM_NOT_MET = "minimum_not_met"
USAGE_LIMIT_REACHED = "usage_limit_reached"
CUSTOMER_LIMIT_REACHED = "customer_limit_reached"


class PromotionNotApplicable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ---- calculation (pure) --------------------------------------------------------------------
def discount_amount(
    kind: str,
    percent_off: int | None,
    amount_off: int | None,
    max_discount: int | None,
    eligible_subtotal: int,
) -> int:
    """The discount on an eligible subtotal: never negative, never above the subtotal."""
    if eligible_subtotal <= 0:
        return 0
    if kind == "percent":
        assert percent_off is not None
        payable = round_half_down(Fraction(eligible_subtotal * (100 - percent_off), 100))
        discount = eligible_subtotal - payable
    else:
        assert amount_off is not None
        discount = min(amount_off, eligible_subtotal)
    if max_discount is not None:
        discount = min(discount, max_discount)
    return max(0, min(discount, eligible_subtotal))


def allocate(total: int, lines: list[tuple[uuid.UUID, int]]) -> dict[uuid.UUID, int]:
    """Split `total` across (key, amount) lines in proportion to their amounts, in whole RWF.

    Each line gets floor(total × amount / sum); the remainder goes to the largest line, the
    earliest on a tie, and only when that line cannot take all of it, on to the next largest, so
    no line is discounted beyond its own amount (D-P4)."""
    base = sum(amount for _, amount in lines)
    if total < 0 or total > base:
        raise ValueError("the discount must be between 0 and the eligible subtotal")
    if base == 0:
        return {key: 0 for key, _ in lines}
    shares = {key: total * amount // base for key, amount in lines}
    remainder = total - sum(shares.values())
    order = sorted(range(len(lines)), key=lambda i: (-lines[i][1], i))
    for index in order:
        if remainder == 0:
            break
        key, amount = lines[index]
        extra = min(remainder, amount - shares[key])
        shares[key] += extra
        remainder -= extra
    return shares


def window_problem(
    starts_at: datetime | None, ends_at: datetime | None, at: datetime
) -> str | None:
    """None inside [starts_at, ends_at); the start is inclusive and the end exclusive (D-P3)."""
    if starts_at is not None and at < starts_at:
        return NOT_STARTED
    if ends_at is not None and at >= ends_at:
        return EXPIRED
    return None


def database_now(db: Session) -> datetime:
    return db.execute(select(func.statement_timestamp())).scalar_one()


# ---- eligibility and quotes ----------------------------------------------------------------
@dataclass(frozen=True)
class DiscountQuote:
    discount: Discount
    applied: bool
    reason: str | None
    amount: int = 0
    eligible_subtotal: int = 0
    allocations: dict[uuid.UUID, int] = field(default_factory=dict)


def eligible_variants(
    db: Session, discount: Discount, variant_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if discount.applies_to == "all":
        return set(variant_ids)
    found = repo.targets(db, [discount.id]).get(discount.id, [])
    products = {t.product_id for t in found if t.product_id is not None}
    brands = {t.brand_id for t in found if t.brand_id is not None}
    categories = repo.category_with_descendants(
        db, {t.category_id for t in found if t.category_id is not None}
    )
    facts = repo.variant_facts(db, variant_ids)
    return {
        variant_id
        for variant_id, (product_id, brand_id, category_id) in facts.items()
        if product_id in products or brand_id in brands or category_id in categories
    }


def _customer_phones(db: Session, user_id: uuid.UUID | None, phone: str | None) -> set[str]:
    """The phones that identify a customer: the order's, and a registered customer's own
    (so a guest checkout with the account's phone counts against the account, §7 Q26)."""
    phones = {phone} if phone else set()
    if user_id is not None:
        account_phone = db.scalar(select(User.phone).where(User.id == user_id))
        if account_phone:
            phones.add(account_phone)
    return phones


def _limit_problem(
    db: Session, discount: Discount, *, user_id: uuid.UUID | None, phone: str | None
) -> str | None:
    if discount.usage_limit_total is not None:
        used = repo.active_redemption_counts(db, [discount.id]).get(discount.id, 0)
        if used >= discount.usage_limit_total:
            return USAGE_LIMIT_REACHED
    phones = _customer_phones(db, user_id, phone)
    if discount.usage_limit_per_customer is not None and (user_id or phones):
        used = repo.active_customer_redemptions(db, discount.id, user_id=user_id, phones=phones)
        if used >= discount.usage_limit_per_customer:
            return CUSTOMER_LIMIT_REACHED
    return None


def quote(
    db: Session,
    discount: Discount,
    lines: list[tuple[uuid.UUID, int]],
    *,
    user_id: uuid.UUID | None = None,
    phone: str | None = None,
    at: datetime | None = None,
) -> DiscountQuote:
    """The discount on priced (variant_id, line_subtotal) lines, in cart order, or why the
    code does not apply. Reads only; nothing is reserved."""
    if discount.status != "active":
        return DiscountQuote(discount, False, NOT_ACTIVE)
    problem = window_problem(discount.starts_at, discount.ends_at, at or database_now(db))
    if problem:
        return DiscountQuote(discount, False, problem)
    eligible_ids = eligible_variants(db, discount, [variant_id for variant_id, _ in lines])
    eligible = [(variant_id, amount) for variant_id, amount in lines if variant_id in eligible_ids]
    subtotal = sum(amount for _, amount in eligible)
    if subtotal == 0:
        return DiscountQuote(discount, False, NO_ELIGIBLE_ITEMS)
    # D-P2: the minimum is the whole merchandise subtotal before discount, whatever the targets.
    if sum(amount for _, amount in lines) < discount.min_subtotal:
        return DiscountQuote(discount, False, MINIMUM_NOT_MET, eligible_subtotal=subtotal)
    problem = _limit_problem(db, discount, user_id=user_id, phone=phone)
    if problem:
        return DiscountQuote(discount, False, problem, eligible_subtotal=subtotal)
    amount = discount_amount(
        discount.kind, discount.percent_off, discount.amount_off, discount.max_discount, subtotal
    )
    shares = allocate(amount, eligible)
    return DiscountQuote(discount, True, None, amount, subtotal, shares)


def find_usable_code(db: Session, code: str) -> Discount | None:
    """The promotion for a customer-entered code, or None for an unknown, draft or disabled
    code (all three look the same to the customer)."""
    discount = repo.by_code(db, code.strip().upper())
    if discount is None or discount.status != "active":
        return None
    return discount


# ---- redemptions (checkout, cancellation, expiry) ------------------------------------------
def redeem(
    db: Session,
    *,
    discount_id: uuid.UUID,
    order_id: uuid.UUID,
    user_id: uuid.UUID | None,
    customer_phone: str,
    amount: int,
) -> DiscountRedemption:
    """Record one use, inside the caller's (checkout's) transaction; the caller commits.

    The discount row is locked FOR UPDATE first, so concurrent checkouts of one code are
    serialised and the limits are counted after the previous use is visible. Raises
    PromotionNotApplicable (status, window or a usage limit) or ValueError (bad amount or a
    phone that is not a Rwandan mobile number; any accepted format is made canonical)."""
    if not 0 <= amount <= MAX_MONEY_RWF:
        raise ValueError("amount must be whole RWF within the storable range")
    customer_phone = validate_rwanda_phone(customer_phone)  # canonical, as users.phone (Q26)
    discount = repo.get(db, discount_id, lock=True)
    if discount is None or discount.status != "active":
        raise PromotionNotApplicable(NOT_ACTIVE)
    problem = window_problem(discount.starts_at, discount.ends_at, database_now(db))
    problem = problem or _limit_problem(db, discount, user_id=user_id, phone=customer_phone)
    if problem:
        raise PromotionNotApplicable(problem)
    redemption = DiscountRedemption(
        discount_id=discount.id,
        order_id=order_id,
        user_id=user_id,
        customer_phone=customer_phone,
        amount=amount,
        status="active",
    )
    db.add(redemption)
    db.flush()
    return redemption


def release_for_order(
    db: Session,
    order_id: uuid.UUID,
    *,
    reason: str,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> int:
    """Release the order's active redemption, in the caller's transaction. Idempotent: an
    already released (or absent) redemption changes nothing and returns 0."""
    if reason not in RELEASE_REASONS:
        raise ValueError(f"reason must be one of {sorted(RELEASE_REASONS)}")
    released = db.execute(
        update(DiscountRedemption)
        .where(DiscountRedemption.order_id == order_id, DiscountRedemption.status == "active")
        .values(status="released", released_at=func.now(), release_reason=reason)
        .returning(DiscountRedemption.id, DiscountRedemption.discount_id)
    ).all()
    for redemption_id, discount_id in released:
        AuditService.log_event(
            db=db,
            action="promotion.redemption_release",
            status="success",
            actor=actor,
            entity_type="order",
            entity_id=order_id,
            context=ctx,
            details={
                "redemption_id": str(redemption_id),
                "discount_id": str(discount_id),
                "reason": reason,
            },
        )
    if released:
        logger.info("Released %d promotion redemption(s) of an order (%s)", len(released), reason)
    return len(released)


# ---- staff ---------------------------------------------------------------------------------
TARGET_MODELS = {"category_id": Category, "brand_id": Brand, "product_id": Product}
SCALAR_FIELDS = (
    "code",
    "name",
    "kind",
    "percent_off",
    "amount_off",
    "applies_to",
    "status",
    "starts_at",
    "ends_at",
    "min_subtotal",
    "max_discount",
    "usage_limit_total",
    "usage_limit_per_customer",
)


def _response(discount: Discount, found: list[DiscountTarget], used: int) -> PromotionResponse:
    return PromotionResponse(
        id=discount.id,
        code=discount.code,
        name=discount.name,
        kind=discount.kind,  # type: ignore[arg-type]
        percent_off=discount.percent_off,
        amount_off=discount.amount_off,
        applies_to=discount.applies_to,  # type: ignore[arg-type]
        targets=[
            PromotionTargetResponse(
                id=t.id, category_id=t.category_id, brand_id=t.brand_id, product_id=t.product_id
            )
            for t in found
        ],
        status=discount.status,  # type: ignore[arg-type]
        starts_at=to_kigali(discount.starts_at),
        ends_at=to_kigali(discount.ends_at),
        min_subtotal=discount.min_subtotal,
        max_discount=discount.max_discount,
        usage_limit_total=discount.usage_limit_total,
        usage_limit_per_customer=discount.usage_limit_per_customer,
        active_redemptions=used,
        created_at=discount.created_at,
        updated_at=discount.updated_at,
    )


def _view(db: Session, discount: Discount) -> PromotionResponse:
    db.refresh(discount)
    return _response(
        discount,
        repo.targets(db, [discount.id]).get(discount.id, []),
        repo.active_redemption_counts(db, [discount.id]).get(discount.id, 0),
    )


def _check_targets_exist(db: Session, targets: list[PromotionTarget]) -> None:
    for index, target in enumerate(targets):
        field_name, target_id = target.key()
        if not repo.existing(db, TARGET_MODELS[field_name], {target_id}):
            raise field_error(("body", "targets", str(index), field_name), "Target not found.")


def _replace_targets(db: Session, discount: Discount, targets: list[PromotionTarget]) -> None:
    for old in repo.targets(db, [discount.id]).get(discount.id, []):
        db.delete(old)
    db.flush()
    for target in targets:
        field_name, target_id = target.key()
        db.add(DiscountTarget(discount_id=discount.id, **{field_name: target_id}))
    db.flush()


def _audit(
    db: Session, action: str, discount: Discount, actor: User, ctx: RequestContext, details: dict
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="promotion",
        entity_id=discount.id,
        context=ctx,
        details=details,
    )


def _audit_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _code_conflict(exc: IntegrityError) -> Conflict:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
    if constraint == "discount_code":
        return Conflict(CODE_TAKEN, code="promotion_code_taken")
    raise exc


class PromotionService:
    @staticmethod
    def list_page(
        db: Session, *, status: str | None, page: int, size: int
    ) -> Page[PromotionResponse]:
        rows, total = repo.page(db, status=status, offset=page_offset(page, size), limit=size)
        ids = [row.id for row in rows]
        found = repo.targets(db, ids)
        used = repo.active_redemption_counts(db, ids)
        return Page(
            items=[_response(row, found.get(row.id, []), used.get(row.id, 0)) for row in rows],
            total=total,
            page=page,
            size=size,
        )

    @staticmethod
    def get(db: Session, discount_id: uuid.UUID) -> PromotionResponse:
        discount = repo.get(db, discount_id)
        if discount is None:
            raise NotFound(PROMOTION_NOT_FOUND, code="promotion_not_found")
        return _view(db, discount)

    @staticmethod
    def create(
        db: Session, actor: User, req: PromotionCreateRequest, ctx: RequestContext
    ) -> PromotionResponse:
        try:
            with atomic(db):
                if repo.code_taken(db, req.code):
                    raise Conflict(CODE_TAKEN, code="promotion_code_taken")
                _check_targets_exist(db, req.targets)
                values = {f: getattr(req, f) for f in SCALAR_FIELDS}
                discount = Discount(**values)
                db.add(discount)
                db.flush()
                _replace_targets(db, discount, req.targets)
                _audit(
                    db,
                    "promotion.create",
                    discount,
                    actor,
                    ctx,
                    {
                        **{f: _audit_value(v) for f, v in values.items()},
                        "targets": len(req.targets),
                    },
                )
        except IntegrityError as exc:
            raise _code_conflict(exc) from None
        return _view(db, discount)

    @staticmethod
    def update(
        db: Session,
        actor: User,
        discount_id: uuid.UUID,
        req: PromotionUpdateRequest,
        ctx: RequestContext,
    ) -> PromotionResponse:
        sent = req.model_dump(exclude_unset=True)
        new_targets = req.targets if "targets" in sent else None
        try:
            with atomic(db):
                discount = repo.get(db, discount_id, lock=True)
                if discount is None:
                    raise NotFound(PROMOTION_NOT_FOUND, code="promotion_not_found")
                if sent.get("status") == "draft" and discount.status != "draft":
                    raise Conflict(BACK_TO_DRAFT, code="invalid_status_transition")
                merged = {f: sent[f] if f in sent else getattr(discount, f) for f in SCALAR_FIELDS}
                current_targets = repo.targets(db, [discount.id]).get(discount.id, [])
                target_count = len(new_targets) if new_targets is not None else len(current_targets)
                problem = consistency_problem(
                    merged["kind"],
                    merged["percent_off"],
                    merged["amount_off"],
                    merged["applies_to"],
                    target_count,
                    merged["starts_at"],
                    merged["ends_at"],
                )
                if problem:
                    raise field_error(("body",), problem)
                if "code" in sent and repo.code_taken(db, sent["code"], exclude_id=discount.id):
                    raise Conflict(CODE_TAKEN, code="promotion_code_taken")
                changes = {
                    f: {"from": _audit_value(getattr(discount, f)), "to": _audit_value(v)}
                    for f, v in merged.items()
                    if getattr(discount, f) != v
                }
                for f in changes:
                    setattr(discount, f, merged[f])
                if new_targets is not None:
                    _check_targets_exist(db, new_targets)
                    before = {(t.category_id, t.brand_id, t.product_id) for t in current_targets}
                    after = {(t.category_id, t.brand_id, t.product_id) for t in new_targets}
                    if before != after:
                        _replace_targets(db, discount, new_targets)
                        changes["targets"] = {"from": len(before), "to": len(after)}
                if changes:
                    db.flush()
                    _audit(db, "promotion.update", discount, actor, ctx, {"changes": changes})
        except IntegrityError as exc:
            raise _code_conflict(exc) from None
        return _view(db, discount)
