"""reviews part 1: review tables and product rating totals (module 20)

Approved by the project owner on 2026-10-27 (scope change SC-01). Part 1 creates the tables and
the product rating fields; part 2 adds review links, submission and moderation.

- review_tokens: one single-use review link per order item (SHA-256 hash only; expires 90 days
  after delivery; used_at once the review is sent).
- product_reviews: one review per delivered order item, rating 1-5, optional title (80) and
  body (2,000), plain text; pending until moderated (approved or rejected).
- products: rating_count, rating_average (one decimal, null with no reviews) and the 5-to-1
  distribution, counting approved reviews only; checks keep them consistent. Existing products
  get zero and null.

Revision ID: e5c9a2f7b3d1
Revises: d3b8e6f1a4c7
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5c9a2f7b3d1"
down_revision: str | None = "d3b8e6f1a4c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_reviews",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=True),
        sa.Column("body", sa.String(length=2000), nullable=True),
        sa.Column("author_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("moderation_reason", sa.String(length=500), nullable=True),
        sa.Column("moderated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (moderated_at IS NULL)",
            name=op.f("ck_product_reviews_moderated_unless_pending"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_product_reviews_valid_status"),
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_product_reviews_rating_range")),
        sa.ForeignKeyConstraint(
            ["moderated_by_user_id"],
            ["users.id"],
            name=op.f("fk_product_reviews_moderated_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name=op.f("fk_product_reviews_order_item_id_order_items"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_reviews_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_product_reviews_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_reviews")),
        sa.UniqueConstraint("order_item_id", name="review_order_item"),
    )
    op.create_index(
        "ix_product_reviews_product_status_created",
        "product_reviews",
        ["product_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_product_reviews_status_created",
        "product_reviews",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_reviews_user_id"), "product_reviews", ["user_id"], unique=False
    )
    op.create_table(
        "review_tokens",
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name=op.f("fk_review_tokens_order_item_id_order_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_tokens")),
        sa.UniqueConstraint("order_item_id", name="review_token_order_item"),
        sa.UniqueConstraint("token_hash", name="review_token_hash"),
    )
    op.add_column(
        "products", sa.Column("rating_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "products", sa.Column("rating_average", sa.Numeric(precision=2, scale=1), nullable=True)
    )
    op.add_column(
        "products", sa.Column("rating_1_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "products", sa.Column("rating_2_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "products", sa.Column("rating_3_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "products", sa.Column("rating_4_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "products", sa.Column("rating_5_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_products_rating_counts_nonnegative"),
        "products",
        "rating_1_count >= 0 AND rating_2_count >= 0 AND rating_3_count >= 0 "
        "AND rating_4_count >= 0 AND rating_5_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_products_rating_count_matches_distribution"),
        "products",
        "rating_count = rating_1_count + rating_2_count + rating_3_count "
        "+ rating_4_count + rating_5_count",
    )
    op.create_check_constraint(
        op.f("ck_products_rating_average_valid"),
        "products",
        "(rating_count = 0 AND rating_average IS NULL) OR "
        "(rating_count > 0 AND rating_average IS NOT NULL "
        "AND rating_average BETWEEN 1 AND 5)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_products_rating_average_valid"), "products", type_="check")
    op.drop_constraint(
        op.f("ck_products_rating_count_matches_distribution"), "products", type_="check"
    )
    op.drop_constraint(op.f("ck_products_rating_counts_nonnegative"), "products", type_="check")
    op.drop_column("products", "rating_5_count")
    op.drop_column("products", "rating_4_count")
    op.drop_column("products", "rating_3_count")
    op.drop_column("products", "rating_2_count")
    op.drop_column("products", "rating_1_count")
    op.drop_column("products", "rating_average")
    op.drop_column("products", "rating_count")
    op.drop_table("review_tokens")
    op.drop_index(op.f("ix_product_reviews_user_id"), table_name="product_reviews")
    op.drop_index("ix_product_reviews_status_created", table_name="product_reviews")
    op.drop_index("ix_product_reviews_product_status_created", table_name="product_reviews")
    op.drop_table("product_reviews")
