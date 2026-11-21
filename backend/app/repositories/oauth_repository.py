import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.identity import OAuthIdentity
from app.models.session import OAuthLoginFlow

# Expired flows are kept a day for investigation, then deleted when new flows start.
FLOW_RETENTION = timedelta(days=1)


class OAuthRepository:
    # ---- identities ------------------------------------------------------------------------
    @staticmethod
    def get_identity(db: Session, provider: str, subject: str) -> OAuthIdentity | None:
        return db.scalar(
            select(OAuthIdentity).where(
                OAuthIdentity.provider == provider, OAuthIdentity.subject == subject
            )
        )

    @staticmethod
    def get_user_identity(db: Session, user_id: uuid.UUID, provider: str) -> OAuthIdentity | None:
        return db.scalar(
            select(OAuthIdentity).where(
                OAuthIdentity.user_id == user_id, OAuthIdentity.provider == provider
            )
        )

    @staticmethod
    def create_identity(
        db: Session, user_id: uuid.UUID, provider: str, subject: str, email: str | None
    ) -> OAuthIdentity:
        """Stage a link in the caller's transaction (no commit). The unique constraints on
        (provider, subject) and (user_id, provider) are the source of truth for races."""
        identity = OAuthIdentity(
            user_id=user_id,
            provider=provider,
            subject=subject,
            email=email,
            last_login_at=datetime.now(UTC),
        )
        db.add(identity)
        db.flush()
        return identity

    # ---- sign-in flows ---------------------------------------------------------------------
    @staticmethod
    def create_flow(
        db: Session,
        *,
        provider: str,
        purpose: str,
        state_hash: str,
        flow_token_hash: str,
        nonce_hash: str,
        code_verifier: str,
        expires_at: datetime,
        user_id: uuid.UUID | None = None,
    ) -> OAuthLoginFlow:
        """Stage a new flow and delete flows that expired over a day ago (no commit)."""
        db.execute(
            delete(OAuthLoginFlow).where(
                OAuthLoginFlow.expires_at < datetime.now(UTC) - FLOW_RETENTION
            )
        )
        flow = OAuthLoginFlow(
            provider=provider,
            purpose=purpose,
            state_hash=state_hash,
            flow_token_hash=flow_token_hash,
            nonce_hash=nonce_hash,
            code_verifier=code_verifier,
            expires_at=expires_at,
            user_id=user_id,
        )
        db.add(flow)
        db.flush()
        return flow

    @staticmethod
    def consume_flow(
        db: Session, *, provider: str, state_hash: str, flow_token_hash: str
    ) -> OAuthLoginFlow | None:
        """Use a flow once: it must match the state and the browser's flow token, be unused and
        unexpired. The row is locked (SELECT ... FOR UPDATE), so of two concurrent callbacks the
        second waits, re-reads the row as consumed and gets None. Returns the flow with its code
        verifier detached for the caller, the stored copy erased; None when nothing matched, so
        a replayed, forged or expired callback never reaches Google. Stages the change in the
        caller's transaction (no commit)."""
        now = datetime.now(UTC)
        flow = db.scalar(
            select(OAuthLoginFlow)
            .where(
                OAuthLoginFlow.provider == provider,
                OAuthLoginFlow.state_hash == state_hash,
                OAuthLoginFlow.flow_token_hash == flow_token_hash,
                OAuthLoginFlow.consumed_at.is_(None),
                OAuthLoginFlow.expires_at > now,
            )
            .with_for_update()
        )
        if flow is None or not flow.code_verifier:
            return None
        verifier = flow.code_verifier
        db.execute(
            update(OAuthLoginFlow)
            .where(OAuthLoginFlow.id == flow.id)
            .values(consumed_at=now, code_verifier=None, updated_at=now)
        )
        db.expunge(flow)  # the caller keeps the verifier; the database no longer has it
        flow.code_verifier = verifier
        flow.consumed_at = now
        return flow

    @staticmethod
    def get_flow_by_state(db: Session, provider: str, state_hash: str) -> OAuthLoginFlow | None:
        """For telling apart why a callback was refused (audit only)."""
        return db.scalar(
            select(OAuthLoginFlow).where(
                OAuthLoginFlow.provider == provider, OAuthLoginFlow.state_hash == state_hash
            )
        )
