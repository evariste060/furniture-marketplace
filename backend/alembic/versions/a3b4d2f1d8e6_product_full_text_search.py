"""Product full-text search (module 9; plan §7 Q5).

Adds products.search_vector (tsvector, 'simple' configuration) over the product name (weight A),
model (B) and brand name (C), kept current by triggers, with a GIN index.

- product_search_document(name, model, brand) builds the vector. Each field is indexed as
  written; every word that contains punctuation is also indexed with the punctuation turned into
  spaces and with it removed, so a model such as "GX-10" matches the searches "GX-10", "GX 10",
  "gx10" and "10". (The 'simple' parser alone reads "GX-10" as the words "gx" and "-10".) Plain
  words are indexed once, so quoted phrases keep their word order.
- products_search_vector (BEFORE INSERT OR UPDATE on products) recomputes the vector of the row on
  every insert and update, so it cannot drift or be set by hand.
- brands_search_vector (AFTER UPDATE OF name on brands, only when the name really changed)
  recomputes the vectors of that brand's products. Updating search_vector does not re-fire the
  brand trigger, so there is no recursion.

Existing rows are backfilled; no data is changed or removed. Downgrade drops the triggers,
functions, index and column.

Revision ID: a3b4d2f1d8e6
Revises: 9d820b74f718
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a3b4d2f1d8e6"
down_revision: str | Sequence[str] | None = "9d820b74f718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_products_search_vector"


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            server_default=sa.text("''::tsvector"),
            nullable=False,
        ),
    )
    op.execute(
        r"""
        CREATE FUNCTION product_search_text(value text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT coalesce(value, '') || coalesce(' ' || (
                SELECT string_agg(
                    regexp_replace(word[1], '[^[:alnum:]]+', ' ', 'g')
                        || ' ' || regexp_replace(word[1], '[^[:alnum:]]+', '', 'g'),
                    ' '
                )
                FROM regexp_matches(
                    coalesce(value, ''), '(\S*[^[:alnum:][:space:]]\S*)', 'g'
                ) AS word
            ), '')
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION product_search_document(name text, model text, brand text)
        RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
            SELECT setweight(to_tsvector('simple', product_search_text(name)), 'A')
                || setweight(to_tsvector('simple', product_search_text(model)), 'B')
                || setweight(to_tsvector('simple', product_search_text(brand)), 'C')
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION products_search_vector_refresh() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search_vector := product_search_document(
                NEW.name,
                NEW.model,
                (SELECT b.name FROM brands b WHERE b.id = NEW.brand_id)
            );
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER products_search_vector
        BEFORE INSERT OR UPDATE ON products
        FOR EACH ROW EXECUTE FUNCTION products_search_vector_refresh()
        """
    )
    op.execute(
        """
        CREATE FUNCTION brands_search_vector_refresh() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE products p
               SET search_vector = product_search_document(p.name, p.model, NEW.name)
             WHERE p.brand_id = NEW.id;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER brands_search_vector
        AFTER UPDATE OF name ON brands
        FOR EACH ROW WHEN (OLD.name IS DISTINCT FROM NEW.name)
        EXECUTE FUNCTION brands_search_vector_refresh()
        """
    )
    # Backfill: the product trigger recomputes each row's vector.
    op.execute("UPDATE products SET search_vector = ''::tsvector")
    op.create_index(INDEX, "products", ["search_vector"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index(INDEX, table_name="products")
    op.execute("DROP TRIGGER brands_search_vector ON brands")
    op.execute("DROP FUNCTION brands_search_vector_refresh()")
    op.execute("DROP TRIGGER products_search_vector ON products")
    op.execute("DROP FUNCTION products_search_vector_refresh()")
    op.execute("DROP FUNCTION product_search_document(text, text, text)")
    op.execute("DROP FUNCTION product_search_text(text)")
    op.drop_column("products", "search_vector")
