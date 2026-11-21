"""Editable settings (module 12; plan §5; RE-026 B1 and B6).

Only keys registered in SETTINGS can be read or written through the API, so nothing else stored
in the table is ever exposed. Module 12 registers delivery.free_delivery_threshold; module 16
the seller details printed on invoices (seller.legal_name, seller.tin, seller.address); module 19
the store contact (store.name, contact.*) and the announcement bar (announcement.*); the social
media links (social.*, owner 2026-11-18) follow, "" meaning no link. ADR-014 phase 1 adds
marketplace.default_commission_bps (whole basis points; unset means 1000, 10%). Note: the
seller.* invoice keys describe the platform as invoice issuer (ADR-014 decision 12), not a
marketplace seller. Only the
keys in PUBLIC_KEYS are served without signing in (GET /settings); everything else is staff only.
The announcement bar can be switched on only while both its messages are set.

Values are JSON and checked against their key's rule both when written (the
request schema) and when read (a stored value that breaks the rule is treated as not set and
logged, so a bad row can never price an order).

Writes: 'settings:manage' (administrators only, B6). Each change is an upsert committed with
one 'settings.update' audit record holding the old and new values; a request that changes
nothing is not audited. Changes are serialised by a transaction-scoped advisory lock (a row
that does not exist yet cannot be locked FOR UPDATE), so each audit record's old value is the
value that change really replaced; the insert also uses ON CONFLICT as a backstop.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import field_error
from app.core.identifiers import EMAIL_MAX_LENGTH, validate_email_format
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import Setting
from app.models.common import MAX_MONEY_RWF
from app.models.identity import User
from app.schemas.settings import (
    ADDRESS_MAX,
    ANNOUNCEMENT_ENABLED,
    ANNOUNCEMENT_MAX,
    ANNOUNCEMENT_TEXT_EN,
    ANNOUNCEMENT_TEXT_RW,
    COMMISSION_BPS_MAX,
    CONTACT_ADDRESS,
    CONTACT_ADDRESS_MAX,
    CONTACT_EMAIL,
    CONTACT_HOURS,
    CONTACT_HOURS_MAX,
    CONTACT_PHONE,
    CONTACT_WHATSAPP,
    DEFAULT_COMMISSION_BPS,
    FREE_DELIVERY_THRESHOLD,
    INTERNATIONAL_PHONE_PATTERN,
    LEGAL_NAME_MAX,
    MARKETPLACE_DEFAULT_COMMISSION,
    SELLER_ADDRESS,
    SELLER_LEGAL_NAME,
    SELLER_TIN,
    SOCIAL_KEYS,
    SOCIAL_NETWORKS,
    STORE_NAME,
    STORE_NAME_MAX,
    TIN_PATTERN,
    LocalizedAnnouncement,
    PublicSettingsResponse,
    SettingResponse,
    SettingsResponse,
    SocialLinks,
    has_control_characters,
    social_url_problem,
)
from app.services.audit_service import AuditService

logger = logging.getLogger("app.settings")

# pg_advisory_xact_lock(bigint) key; 7_302_116_001-004 are taken (staff, catalogue, products).
SETTINGS_CHANGE_LOCK_KEY = 7_302_116_005


def _is_amount(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_MONEY_RWF


def _text(minimum: int, maximum: int, *, multiline: bool = False) -> Callable[[Any], bool]:
    def valid(value: Any) -> bool:
        return (
            isinstance(value, str)
            and value == value.strip()
            and minimum <= len(value) <= maximum
            and not has_control_characters(value, allow_newlines=multiline)
        )

    return valid


def _pattern(pattern: str) -> Callable[[Any], bool]:
    def valid(value: Any) -> bool:
        return (
            isinstance(value, str)
            and value == value.strip()
            and re.fullmatch(pattern, value) is not None
        )

    return valid


_is_tin = _pattern(TIN_PATTERN)
_is_international_phone = _pattern(INTERNATIONAL_PHONE_PATTERN)


def _is_email(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > EMAIL_MAX_LENGTH:
        return False
    try:
        return validate_email_format(value) == value
    except ValueError:
        return False


def _is_flag(value: Any) -> bool:
    return isinstance(value, bool)


def _is_bps(value: Any) -> bool:
    """Whole basis points 0-10000; never a float or a bool."""
    return type(value) is int and 0 <= value <= COMMISSION_BPS_MAX


def _social(hosts: tuple[str, ...]) -> Callable[[Any], bool]:
    def valid(value: Any) -> bool:
        return isinstance(value, str) and social_url_problem(value, hosts) is None

    return valid


@dataclass(frozen=True)
class SettingRule:
    valid: Callable[[Any], bool]


SETTINGS: dict[str, SettingRule] = {
    FREE_DELIVERY_THRESHOLD: SettingRule(valid=_is_amount),
    SELLER_LEGAL_NAME: SettingRule(valid=_text(2, LEGAL_NAME_MAX)),
    SELLER_TIN: SettingRule(valid=_is_tin),
    SELLER_ADDRESS: SettingRule(valid=_text(3, ADDRESS_MAX, multiline=True)),
    STORE_NAME: SettingRule(valid=_text(2, STORE_NAME_MAX)),
    CONTACT_PHONE: SettingRule(valid=_is_international_phone),
    CONTACT_WHATSAPP: SettingRule(valid=_is_international_phone),
    CONTACT_EMAIL: SettingRule(valid=_is_email),
    CONTACT_ADDRESS: SettingRule(valid=_text(3, CONTACT_ADDRESS_MAX)),
    CONTACT_HOURS: SettingRule(valid=_text(3, CONTACT_HOURS_MAX)),
    ANNOUNCEMENT_ENABLED: SettingRule(valid=_is_flag),
    ANNOUNCEMENT_TEXT_EN: SettingRule(valid=_text(3, ANNOUNCEMENT_MAX)),
    ANNOUNCEMENT_TEXT_RW: SettingRule(valid=_text(3, ANNOUNCEMENT_MAX)),
    MARKETPLACE_DEFAULT_COMMISSION: SettingRule(valid=_is_bps),
    **{
        SOCIAL_KEYS[name]: SettingRule(valid=_social(hosts))
        for name, hosts in SOCIAL_NETWORKS.items()
    },
}

# Served by the public GET /settings (module 19). Every other key is staff only.
PUBLIC_KEYS = frozenset(
    {
        STORE_NAME,
        CONTACT_PHONE,
        CONTACT_WHATSAPP,
        CONTACT_EMAIL,
        CONTACT_ADDRESS,
        CONTACT_HOURS,
        ANNOUNCEMENT_ENABLED,
        ANNOUNCEMENT_TEXT_EN,
        ANNOUNCEMENT_TEXT_RW,
        *SOCIAL_KEYS.values(),
    }
)
ANNOUNCEMENT_NEEDS_TEXT = "Write the announcement in English and Kinyarwanda before showing it."


def _stored(db: Session, keys: list[str]) -> dict[str, Setting]:
    return {row.key: row for row in db.scalars(select(Setting).where(Setting.key.in_(keys)))}


def get_value(db: Session, key: str) -> Any:
    """The stored value of a registered key, or None when it is unset or invalid."""
    row = db.get(Setting, key)
    if row is None:
        return None
    if not SETTINGS[key].valid(row.value):
        logger.error("Setting %s holds an invalid value and is ignored", key)
        return None
    return row.value


def free_delivery_threshold(db: Session) -> int | None:
    value = get_value(db, FREE_DELIVERY_THRESHOLD)
    return int(value) if value is not None else None


def default_commission_bps(db: Session) -> int:
    """The platform commission in basis points: the stored setting, or DEFAULT_COMMISSION_BPS
    (10%) while it is unset or invalid (an invalid row is logged by get_value). ADR-014."""
    value = get_value(db, MARKETPLACE_DEFAULT_COMMISSION)
    return int(value) if value is not None else DEFAULT_COMMISSION_BPS


def seller_details(db: Session) -> dict[str, str] | None:
    """The seller's legal name, TIN and address for an invoice (module 16), or None when any of
    them is unset or invalid: an invoice is never issued with missing seller details."""
    values = {
        "legal_name": get_value(db, SELLER_LEGAL_NAME),
        "tin": get_value(db, SELLER_TIN),
        "address": get_value(db, SELLER_ADDRESS),
    }
    if any(value is None for value in values.values()):
        return None
    return {key: str(value) for key, value in values.items()}


def _valid_values(db: Session, keys: list[str]) -> dict[str, Any]:
    """{key: value} for the registered keys that hold a valid value."""
    values = {}
    for key, row in _stored(db, keys).items():
        if SETTINGS[key].valid(row.value):
            values[key] = row.value
        else:
            logger.error("Setting %s holds an invalid value and is ignored", key)
    return values


class SettingsService:
    @staticmethod
    def read_public(db: Session) -> PublicSettingsResponse:
        values = _valid_values(db, sorted(PUBLIC_KEYS))
        en, rw = values.get(ANNOUNCEMENT_TEXT_EN), values.get(ANNOUNCEMENT_TEXT_RW)
        announcement = None
        if values.get(ANNOUNCEMENT_ENABLED) is True and en is not None and rw is not None:
            announcement = LocalizedAnnouncement(en=en, rw=rw)
        return PublicSettingsResponse(
            store_name=values.get(STORE_NAME),
            phone=values.get(CONTACT_PHONE),
            whatsapp=values.get(CONTACT_WHATSAPP),
            email=values.get(CONTACT_EMAIL),
            address=values.get(CONTACT_ADDRESS),
            hours=values.get(CONTACT_HOURS),
            announcement=announcement,
            social=SocialLinks(
                **{name: values.get(key) or None for name, key in SOCIAL_KEYS.items()}
            ),
        )

    @staticmethod
    def read(db: Session) -> SettingsResponse:
        keys = sorted(SETTINGS)
        rows = _stored(db, keys)
        items = []
        for key in keys:
            row = rows.get(key)
            value = row.value if row is not None and SETTINGS[key].valid(row.value) else None
            items.append(
                SettingResponse(
                    key=key,
                    value=value,
                    updated_at=row.updated_at if row is not None else None,
                    updated_by_user_id=row.updated_by_user_id if row is not None else None,
                )
            )
        return SettingsResponse(items=items)

    @staticmethod
    def update(
        db: Session, actor: User, changes: dict[str, Any], ctx: RequestContext
    ) -> SettingsResponse:
        unknown = set(changes) - set(SETTINGS)
        if unknown:  # the request schema already refuses them; this guards other callers
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        with atomic(db):
            db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": SETTINGS_CHANGE_LOCK_KEY}
            )
            rows = _stored(db, sorted(changes))
            if changes.get(ANNOUNCEMENT_ENABLED) is True:
                SettingsService._check_announcement(db, changes)
            audited: dict[str, dict[str, Any]] = {}
            for key, new in sorted(changes.items()):
                if not SETTINGS[key].valid(new):
                    raise ValueError(f"invalid value for {key}")
                row = rows.get(key)
                old = row.value if row is not None else None
                if row is not None and old == new and type(old) is type(new):
                    continue
                db.execute(
                    insert(Setting)
                    .values(key=key, value=new, updated_by_user_id=actor.id)
                    .on_conflict_do_update(
                        index_elements=[Setting.key],
                        set_={
                            "value": new,
                            "updated_by_user_id": actor.id,
                            "updated_at": func.now(),
                        },
                    )
                )
                audited[key] = {"from": old, "to": new}
            if audited:
                AuditService.log_event(
                    db=db,
                    action="settings.update",
                    status="success",
                    actor=actor,
                    entity_type="settings",
                    entity_id=",".join(sorted(audited)),
                    context=ctx,
                    details={"changes": audited},
                )
        db.expire_all()
        return SettingsService.read(db)

    @staticmethod
    def _check_announcement(db: Session, changes: dict[str, Any]) -> None:
        """The bar is shown only with both messages: refuse switching it on while either message
        would be unset. Messages cannot be set to null, so only switching on can break the rule."""
        stored = _valid_values(db, [ANNOUNCEMENT_TEXT_EN, ANNOUNCEMENT_TEXT_RW])
        merged = {**stored, **changes}
        if merged.get(ANNOUNCEMENT_TEXT_EN) is None or merged.get(ANNOUNCEMENT_TEXT_RW) is None:
            raise field_error(("body", ANNOUNCEMENT_ENABLED), ANNOUNCEMENT_NEEDS_TEXT)
