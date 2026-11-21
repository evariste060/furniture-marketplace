import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.integrations.notifications import Channel, OutboundMessage


@dataclass
class SentMessage:
    channel: str
    recipient: str
    subject: str
    text: str
    idempotency_key: str = ""
    html: str | None = None


@dataclass
class RecordingSender:
    """NotificationProvider test double (the email capture service of the tests): keeps every
    message, HTML included, in memory instead of sending it."""

    name = "recording"
    reaches_recipient = True
    idempotent_delivery = False
    channels: tuple[Channel, ...] = ("sms", "email")
    messages: list[SentMessage] = field(default_factory=list)

    def send(self, message: OutboundMessage) -> str:
        self.messages.append(
            SentMessage(
                message.channel,
                message.recipient,
                message.subject,
                message.text,
                message.idempotency_key,
                message.html,
            )
        )
        return f"recorded-{len(self.messages)}"


class ScriptedProvider(RecordingSender):
    """Records every call, then answers with the next scripted outcome: None for success (an ID
    derived from the call number), or an exception instance to raise. Thread-safe; `delay`
    slows each call so concurrent workers overlap."""

    def __init__(self, outcomes: Iterable[BaseException | None] = (), delay: float = 0.0):
        super().__init__()
        self.outcomes = list(outcomes)
        self._delay = delay
        self._lock = threading.Lock()

    def send(self, message: OutboundMessage) -> str:
        with self._lock:
            message_id = super().send(message)
            outcome = self.outcomes.pop(0) if self.outcomes else None
        if self._delay:
            time.sleep(self._delay)
        if outcome is not None:
            raise outcome
        return message_id


def verification_token(sender: RecordingSender, email: str) -> str:
    """The token in the newest email verification link sent to `email`."""
    for message in reversed(sender.messages):
        if message.recipient == email:
            found = re.search(r"#token=([A-Za-z0-9_-]+)", message.text)
            if found:
                return found.group(1)
    raise AssertionError(f"no verification email for {email}")
