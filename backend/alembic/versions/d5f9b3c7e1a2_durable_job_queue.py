"""jobs: durable job queue (jobs, job_items) for the background worker

Approved by the project owner on 2026-10-26 (checkpoint 1b, topic 4). FastAPI background tasks
are lost on restart, so long work (bulk image upload first) is queued in PostgreSQL and done by
the worker process (python -m app.worker):
- jobs: one request's work (type, state, creator, counts, finished_at);
- job_items: one unit of work each, claimed with SELECT ... FOR UPDATE SKIP LOCKED. (job_id,
  item_index) is unique, so an item exists once; attempts and locked_at let a crashed worker's
  item be requeued (after 10 minutes, at most 3 attempts). target names what the item changes
  (e.g. a product image position), so items for the same target run in order.
Both tables are new: no existing data is touched. The downgrade drops them.

Revision ID: d5f9b3c7e1a2
Revises: c4e8f2a6b9d1
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5f9b3c7e1a2"
down_revision: str | Sequence[str] | None = "c4e8f2a6b9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="queued", nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("total_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("succeeded_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("type IN ('bulk_image_upload')", name=op.f("ck_jobs_valid_type")),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'finished')", name=op.f("ck_jobs_valid_state")
        ),
        sa.CheckConstraint(
            "total_items >= 0 AND succeeded_items >= 0 AND failed_items >= 0 "
            "AND succeeded_items + failed_items <= total_items",
            name=op.f("ck_jobs_counts_valid"),
        ),
        sa.CheckConstraint(
            "(state = 'finished') = (finished_at IS NOT NULL)",
            name=op.f("ck_jobs_finished_when_final"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_jobs_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_created_by_created", "jobs", ["created_by_user_id", "created_at"])
    op.create_table(
        "job_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=12), server_default="queued", nullable=False),
        sa.Column("target", sa.String(length=120), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "state IN ('queued', 'processing', 'done', 'failed')",
            name=op.f("ck_job_items_valid_state"),
        ),
        sa.CheckConstraint("item_index >= 0", name=op.f("ck_job_items_index_nonnegative")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_job_items_attempts_nonnegative")),
        sa.CheckConstraint(
            "(state = 'processing') = (locked_at IS NOT NULL)",
            name=op.f("ck_job_items_locked_when_processing"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_items_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_items")),
        sa.UniqueConstraint("job_id", "item_index", name="uq_job_items_job_index"),
    )
    op.create_index("ix_job_items_state_created", "job_items", ["state", "created_at"])
    op.create_index("ix_job_items_target_state", "job_items", ["target", "state"])


def downgrade() -> None:
    op.drop_index("ix_job_items_target_state", table_name="job_items")
    op.drop_index("ix_job_items_state_created", table_name="job_items")
    op.drop_table("job_items")
    op.drop_index("ix_jobs_created_by_created", table_name="jobs")
    op.drop_table("jobs")
