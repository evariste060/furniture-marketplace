"use client";

import { createContext, useContext, type ReactNode } from "react";
import { browserApi } from "@/lib/api/client";
import type { components, operations } from "@/lib/api/schema";
import type { CategoryNode } from "./category-options";
import { must, postFiles } from "./ui";

/** Who the product list, product editor and stock screens work for (ADR-014 phase 4): platform
 * staff through /staff/* and /inventory, or an approved seller through /seller/*, which the
 * backend limits to the seller's own store. The screens are the same; only the routes, the
 * links and what may be changed differ. The flags only decide what is shown: the backend checks
 * every call again. */

export type ScopedProduct = components["schemas"]["StaffProductDetail"];
export type ScopedProductRow = components["schemas"]["StaffProductListItem"];
export type ScopedStockRow = components["schemas"]["InventoryListItem"];
type ProductPage = components["schemas"]["Page_StaffProductListItem_"];
type StockPage = components["schemas"]["Page_InventoryListItem_"];
type Image = components["schemas"]["ImageResponse"];
type Brand = { id: string; name: string; is_active: boolean; category_ids?: string[] };
export type ProductQuery = NonNullable<operations["list_my_products_api_v1_seller_products_get"]["parameters"]["query"]>;
export type StockQuery = NonNullable<operations["list_my_inventory_api_v1_seller_inventory_get"]["parameters"]["query"]>;
type ProductCreate = components["schemas"]["SellerProductCreateRequest"] & { is_featured?: boolean };
type ProductUpdate = components["schemas"]["SellerProductUpdateRequest"] & { is_featured?: boolean };
type VariantCreate = components["schemas"]["VariantCreateRequest"];
type VariantUpdate = components["schemas"]["VariantUpdateRequest"];
type Adjustment = components["schemas"]["StockAdjustmentRequest"];

export type CatalogScope = {
  kind: "staff" | "seller";
  /** The panel's root: "/admin" or "/seller". */
  base: string;
  /** The first part of every query key, so a save refreshes only this panel's data. */
  key: "admin" | "seller";
  /** Edit products, variants and photos. */
  manage: boolean;
  /** Read stock figures. */
  stock: boolean;
  /** Record stock changes. */
  adjust: boolean;
  /** Platform merchandising: the featured flag, bulk publishing and the catalogue import. A
   * seller's requests never carry them (the backend refuses them with 422). */
  merchandising: boolean;
  /** Add products (sellers only: administrators moderate, SC-05). */
  create: boolean;
  api: {
    categories: () => Promise<CategoryNode[]>;
    brands: () => Promise<Brand[]>;
    products: (query: ProductQuery) => Promise<ProductPage>;
    product: (id: string) => Promise<ScopedProduct>;
    createProduct: (body: ProductCreate) => Promise<{ id: string }>;
    updateProduct: (id: string, body: ProductUpdate) => Promise<unknown>;
    createVariant: (productId: string, body: VariantCreate) => Promise<unknown>;
    updateVariant: (productId: string, variantId: string, body: VariantUpdate) => Promise<unknown>;
    uploadImage: (productId: string, file: File) => Promise<Image>;
    reorderImages: (productId: string, ids: string[]) => Promise<unknown>;
    updateImage: (imageId: string, altText: string | null) => Promise<unknown>;
    deleteImage: (imageId: string) => Promise<unknown>;
    inventory: (query: StockQuery) => Promise<StockPage>;
    adjust: (sku: string, idempotencyKey: string, body: Adjustment) => Promise<unknown>;
  };
};

/** The public category tree, flattened into the editor's nodes (only visible categories). */
type PublicCategory = components["schemas"]["CatalogCategory"] & { children?: PublicCategory[] };
export function flattenCategories(tree: readonly PublicCategory[], parentId: string | null = null): CategoryNode[] {
  return tree.flatMap((c) => [
    { id: c.id, name: c.name, parent_id: c.parent_id ?? parentId, is_active: true, sort_order: c.sort_order },
    ...flattenCategories(c.children ?? [], c.id),
  ]);
}

const STAFF_API: CatalogScope["api"] = {
  categories: async () => (await must(browserApi.GET("/api/v1/staff/categories"))).items,
  brands: async () => (await must(browserApi.GET("/api/v1/staff/brands"))).items,
  products: (query) => must(browserApi.GET("/api/v1/staff/products", { params: { query } })),
  product: (id) => must(browserApi.GET("/api/v1/staff/products/{product_id}", { params: { path: { product_id: id } } })),
  createProduct: (body) => must(browserApi.POST("/api/v1/staff/products", { body: { ...body, is_featured: body.is_featured ?? false } })),
  updateProduct: (id, body) => must(browserApi.PATCH("/api/v1/staff/products/{product_id}", { params: { path: { product_id: id } }, body })),
  createVariant: (productId, body) => must(browserApi.POST("/api/v1/staff/products/{product_id}/variants", { params: { path: { product_id: productId } }, body })),
  updateVariant: (productId, variantId, body) =>
    must(browserApi.PATCH("/api/v1/staff/products/{product_id}/variants/{variant_id}", { params: { path: { product_id: productId, variant_id: variantId } }, body })),
  uploadImage: (productId, file) => postFiles<Image>(`staff/products/${productId}/images`, "file", [file]),
  reorderImages: (productId, ids) => must(browserApi.PUT("/api/v1/staff/products/{product_id}/images/order", { params: { path: { product_id: productId } }, body: { image_ids: ids } })),
  updateImage: (imageId, altText) => must(browserApi.PATCH("/api/v1/staff/images/{image_id}", { params: { path: { image_id: imageId } }, body: { alt_text: altText } })),
  deleteImage: (imageId) => must(browserApi.DELETE("/api/v1/staff/images/{image_id}", { params: { path: { image_id: imageId } } })),
  inventory: (query) => must(browserApi.GET("/api/v1/inventory", { params: { query } })),
  adjust: (sku, key, body) => must(browserApi.POST("/api/v1/inventory/{sku}/adjustments", { params: { path: { sku }, header: { "Idempotency-Key": key } }, body })),
};

/** A product body without the platform's merchandising fields (the seller routes refuse them). */
export function withoutMerchandising<T extends { is_featured?: boolean }>(body: T): Omit<T, "is_featured"> {
  const copy = { ...body };
  delete copy.is_featured;
  return copy;
}

const SELLER_API: CatalogScope["api"] = {
  categories: async () => flattenCategories(await must(browserApi.GET("/api/v1/catalog/categories"))),
  brands: async () => (await must(browserApi.GET("/api/v1/catalog/brands"))).map((b) => ({ id: b.id, name: b.name, is_active: true })),
  products: (query) => must(browserApi.GET("/api/v1/seller/products", { params: { query } })),
  product: (id) => must(browserApi.GET("/api/v1/seller/products/{product_id}", { params: { path: { product_id: id } } })),
  // Never the merchandising fields: the seller routes refuse them.
  createProduct: (body) => must(browserApi.POST("/api/v1/seller/products", { body: withoutMerchandising(body) })),
  updateProduct: (id, body) => must(browserApi.PATCH("/api/v1/seller/products/{product_id}", { params: { path: { product_id: id } }, body: withoutMerchandising(body) })),
  createVariant: (productId, body) => must(browserApi.POST("/api/v1/seller/products/{product_id}/variants", { params: { path: { product_id: productId } }, body })),
  updateVariant: (productId, variantId, body) =>
    must(browserApi.PATCH("/api/v1/seller/products/{product_id}/variants/{variant_id}", { params: { path: { product_id: productId, variant_id: variantId } }, body })),
  uploadImage: (productId, file) => postFiles<Image>(`seller/products/${productId}/images`, "file", [file]),
  reorderImages: (productId, ids) => must(browserApi.PUT("/api/v1/seller/products/{product_id}/images/order", { params: { path: { product_id: productId } }, body: { image_ids: ids } })),
  updateImage: (imageId, altText) => must(browserApi.PATCH("/api/v1/seller/images/{image_id}", { params: { path: { image_id: imageId } }, body: { alt_text: altText } })),
  deleteImage: (imageId) => must(browserApi.DELETE("/api/v1/seller/images/{image_id}", { params: { path: { image_id: imageId } } })),
  inventory: (query) => must(browserApi.GET("/api/v1/seller/inventory", { params: { query } })),
  adjust: (sku, key, body) => must(browserApi.POST("/api/v1/seller/inventory/{sku}/adjustments", { params: { path: { sku }, header: { "Idempotency-Key": key } }, body })),
};

/** An approved seller's scope: everything in their own store, no platform merchandising. */
export const SELLER_SCOPE: CatalogScope = {
  kind: "seller",
  base: "/seller",
  key: "seller",
  manage: true,
  stock: true,
  adjust: true,
  merchandising: false,
  create: true,
  api: SELLER_API,
};

/** A staff member's scope, from their permissions (the admin's StaffAccessProvider gives it). */
export function staffScope(permissions: ReadonlySet<string>): CatalogScope {
  const manage = permissions.has("catalog:manage");
  return {
    kind: "staff",
    base: "/admin",
    key: "admin",
    manage,
    stock: permissions.has("inventory:read"),
    adjust: permissions.has("inventory:adjust"),
    merchandising: manage,
    create: false,
    api: STAFF_API,
  };
}

const ScopeContext = createContext<CatalogScope | null>(null);

export function CatalogScopeProvider({ scope, children }: { scope: CatalogScope; children: ReactNode }) {
  return <ScopeContext.Provider value={scope}>{children}</ScopeContext.Provider>;
}

/** The admin shell provides the staff scope, the seller dashboard the seller's. */
export function useCatalogScope(): CatalogScope {
  const scope = useContext(ScopeContext);
  if (!scope) throw new Error("useCatalogScope is used outside the admin or seller shell");
  return scope;
}
