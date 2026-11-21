"""The per-request notification handle (module 17): endpoints that change an order schedule the
notifications their transaction recorded, to be sent after the response."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.notifications import NotificationProvider, get_notification_provider
from app.services.notification_service import HttpNotifier


def get_http_notifier(
    db: Annotated[Session, Depends(get_db)],
    provider: Annotated[NotificationProvider | None, Depends(get_notification_provider)],
) -> HttpNotifier:
    bind = db.get_bind()
    return HttpNotifier(engine=bind if isinstance(bind, Engine) else None, provider=provider)


Notifier = Annotated[HttpNotifier, Depends(get_http_notifier)]
