"""SQL building blocks for the category tree (category hierarchy, approved 2026-11-16).

The tree is at most MAX_CATEGORY_DEPTH levels deep (main category, then subcategory); the
catalogue service refuses anything deeper. These queries are recursive anyway, so a deeper tree
created before the cap still behaves: a subtree is every level below, and a category is hidden
when it or any ancestor is inactive.

Each CTE is nested in the statement that uses it, so one statement may use several of them.
This module imports only the models: the catalogue repository, inventory and inventory admin
all use it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Integer, Select, func, literal, select
from sqlalchemy.orm import Session

from app.models import Category

# Main category (level 1) and subcategory (level 2).
MAX_CATEGORY_DEPTH = 2


def hidden_category_ids() -> Select[Any]:
    """Every category that is inactive or below an inactive one. Deactivating a category hides
    its whole subtree, the same rule as the public category tree."""
    tree = (
        select(Category.id.label("id"))
        .where(Category.is_active.is_(False))
        .cte("hidden_categories", recursive=True, nesting=True)
    )
    tree = tree.union(select(Category.id).where(Category.parent_id == tree.c.id))
    return select(tree.c.id)


def category_visible(category_id: Any) -> Any:
    """Condition: the category in this column is active and so is every ancestor."""
    return category_id.not_in(hidden_category_ids())


def subtree_ids_by_slug(slug: str) -> Select[Any]:
    """The category with this slug and every category below it (nothing for an unknown slug)."""
    tree = (
        select(Category.id.label("id"))
        .where(Category.slug == slug)
        .cte("category_subtree", recursive=True, nesting=True)
    )
    tree = tree.union(select(Category.id).where(Category.parent_id == tree.c.id))
    return select(tree.c.id)


def category_roots() -> Any:
    """(id, root_id) for every category: root_id is its main category (itself for a main one)."""
    tree = (
        select(Category.id.label("id"), Category.id.label("root_id"))
        .where(Category.parent_id.is_(None))
        .cte("category_roots", recursive=True, nesting=True)
    )
    return tree.union(select(Category.id, tree.c.root_id).where(Category.parent_id == tree.c.id))


def category_depth(db: Session, category_id: uuid.UUID) -> int:
    """Level of an existing category: 1 for a main category, 2 for a subcategory, ..."""
    depth = 0
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = category_id
    while current is not None and current not in seen:
        seen.add(current)
        depth += 1
        current = db.scalar(select(Category.parent_id).where(Category.id == current))
    return depth


def subtree_height(db: Session, category_id: uuid.UUID) -> int:
    """Levels in the category's subtree: 1 without subcategories, 2 with children, ..."""
    tree = (
        select(Category.id.label("id"), literal(1, Integer).label("level"))
        .where(Category.id == category_id)
        .cte("category_height", recursive=True)
    )
    tree = tree.union_all(
        select(Category.id, tree.c.level + 1).where(
            Category.parent_id == tree.c.id,
            tree.c.level < 32,  # guard against a cycle
        )
    )
    return int(db.scalar(select(func.max(tree.c.level))) or 0)
