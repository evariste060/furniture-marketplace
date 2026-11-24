"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  ImagePlus,
  Pencil,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import {
  Checkbox,
  Field,
  Input,
  RadioOption,
  Select,
  Textarea,
} from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { Toggle } from "@/components/ui/toggle";
import { useToast } from "@/components/ui/toast";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import {
  ATTRIBUTE_KEYS,
  BOOLEAN_KEYS,
  CHOICES,
  isAttributeKey,
  NUMBER_KEYS,
  type AttributeKey,
  type ChoiceKey,
} from "@/lib/furniture";
import { useCatalogScope } from "./catalog-scope";
import {
  brandOptions,
  groupBrandOptions,
  mainOptions,
  splitCategory,
  subOptions,
  type CategoryNode,
  type Option,
} from "./category-options";
import { PRODUCT_TONE, type ProductStatus } from "./products";
import { groupDigits, parseAmount } from "./numbers";
import { bodyFieldErrors, LoadError, PageHeader, Thumb } from "./ui";

type Product = components["schemas"]["StaffProductDetail"];
type Variant = components["schemas"]["VariantResponse"];
type ProductImageRow = components["schemas"]["ImageResponse"];
type Row = { key: string; value: string };

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const IMAGE_TYPES = "image/jpeg,image/png,image/webp";
const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/** A SKU as the backend accepts it: no spaces, "/" or "__". */
export function skuOk(sku: string): boolean {
  return (
    sku.length > 0 &&
    sku.length <= 80 &&
    !/[\s/]/.test(sku) &&
    !sku.includes("__")
  );
}

/** Specification or attribute rows ↔ the API's flat object (empty rows dropped). */
export function rowsToObject(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of rows)
    if (key.trim() && value.trim()) out[key.trim()] = value.trim();
  return out;
}
function objectToRows(value: Record<string, unknown>): Row[] {
  return Object.entries(value)
    .filter(([key]) => !isAttributeKey(key))
    .map(([key, v]) => ({ key, value: String(v ?? "") }));
}

/** Furniture attributes (ADR-014 phase 6) as the form holds them: text per key, "" when unset.
 * A boolean is "true" or "false". */
export type AttributeValues = Partial<Record<AttributeKey, string>>;
const NUMBER_MAX = 100_000; // app/core/furniture.py NUMBER_MAX

export function attributeValues(
  specifications: Record<string, unknown>,
): AttributeValues {
  const out: AttributeValues = {};
  for (const [key, value] of Object.entries(specifications))
    if (isAttributeKey(key) && value !== null && value !== undefined)
      out[key] = String(value);
  return out;
}

function isNumberKey(key: AttributeKey): boolean {
  return (NUMBER_KEYS as readonly string[]).includes(key);
}

/** A measurement as typed ("92.5" or "92,5"), or null when it is not a positive number up to
 * the backend's limit. */
export function parseMeasure(text: string): number | null {
  const value = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(value)) return null;
  const n = Number(value);
  return n > 0 && n <= NUMBER_MAX ? n : null;
}

/** The attributes as the API stores them: numbers, booleans and choice codes; unset ones left out. */
export function attributesToObject(
  values: AttributeValues,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const key of ATTRIBUTE_KEYS) {
    const value = values[key]?.trim();
    if (!value) continue;
    if (isNumberKey(key)) {
      const n = parseMeasure(value);
      if (n !== null) out[key] = n;
    } else if ((BOOLEAN_KEYS as readonly string[]).includes(key))
      out[key] = value === "true";
    else out[key] = value;
  }
  return out;
}

/** The product's specifications: the attributes first, then the free rows. */
function specificationsOf(
  form: Pick<FormState, "attrs" | "specs">,
): Record<string, unknown> {
  return { ...attributesToObject(form.attrs), ...rowsToObject(form.specs) };
}

/** Moves one item of a list to another index (the image drag and the move buttons). */
export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(to, next.length)), 0, item);
  return next;
}

/** ProductEditor.dc.html: /admin/products/new and /admin/products/[id], and the seller's
 * /seller/products/new and /seller/products/[id] (ADR-014 phase 4, the seller's own store). */
export function ProductEditorView({ productId }: { productId?: string }) {
  const t = useTranslations("admin");
  const scope = useCatalogScope();
  const query = useQuery({
    queryKey: [scope.key, "product", productId],
    queryFn: () => scope.api.product(productId!),
    enabled: Boolean(productId),
    retry: (count, error) =>
      !(error instanceof ApiError && [404, 422].includes(error.status)) &&
      count < 2,
  });
  if (productId && query.isError) {
    if (
      query.error instanceof ApiError &&
      [404, 422].includes(query.error.status)
    )
      return (
        <Card padding={32} className="flex flex-col items-start gap-3">
          <h1 className="t-h2">{t("editor.notFound")}</h1>
          <NextLink
            href={`${scope.base}/products`}
            className={buttonClasses({ variant: "neutral", size: "sm" })}
          >
            {t("editor.back")}
          </NextLink>
        </Card>
      );
    return <LoadError onRetry={() => query.refetch()} />;
  }
  if (productId && !query.data) return <EditorSkeleton />;
  // A new key per loaded version resets the form after each save.
  return (
    <EditorForm
      key={query.data?.updated_at ?? "new"}
      product={query.data ?? null}
    />
  );
}

type FormState = {
  name: string;
  description: string;
  brandId: string;
  categoryId: string;
  model: string;
  warranty: string;
  slug: string;
  status: ProductStatus;
  featured: boolean;
  attrs: AttributeValues;
  specs: Row[];
};

type VariantEdit = {
  price: string;
  compare: string;
  threshold: string;
  active: boolean;
};

function initialForm(product: Product | null): FormState {
  return {
    name: product?.name ?? "",
    description: product?.description ?? "",
    brandId: product?.brand_id ?? "",
    categoryId: product?.category_id ?? "",
    model: product?.model ?? "",
    warranty: product?.warranty_text ?? "",
    slug: product?.slug ?? "",
    status: product?.status ?? "draft",
    featured: product?.is_featured ?? false,
    attrs: product ? attributeValues(product.specifications) : {},
    specs: product
      ? objectToRows(product.specifications)
      : [{ key: "", value: "" }],
  };
}

function variantEdit(v: Variant): VariantEdit {
  return {
    price: groupDigits(v.price),
    compare: v.compare_at_price == null ? "" : groupDigits(v.compare_at_price),
    threshold: String(v.low_stock_threshold),
    active: v.is_active,
  };
}

function EditorForm({ product }: { product: Product | null }) {
  const t = useTranslations("admin");
  const router = useRouter();
  const client = useQueryClient();
  const toast = useToast();
  const scope = useCatalogScope();
  const { manage, moderate } = scope;
  const [form, setForm] = useState<FormState>(() => initialForm(product));
  const [variants, setVariants] = useState<Record<string, VariantEdit>>(() =>
    Object.fromEntries(
      (product?.variants ?? []).map((v) => [v.id, variantEdit(v)]),
    ),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const categories = useQuery({
    queryKey: [scope.key, "categories"],
    queryFn: scope.api.categories,
    staleTime: 60_000,
  });
  const brands = useQuery({
    queryKey: [scope.key, "brands"],
    queryFn: scope.api.brands,
    staleTime: 60_000,
  });
  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const validate = (): Record<string, string> => {
    const found: Record<string, string> = {};
    if (!form.name.trim()) found.name = t("editor.errors.name");
    if (!form.categoryId) found.category_id = t("editor.errors.category");
    if (form.slug.trim() && !SLUG.test(form.slug.trim()))
      found.slug = t("editor.errors.slug");
    for (const [id, v] of Object.entries(variants)) {
      if (parseAmount(v.price) === null)
        found[`price-${id}`] = t("editor.errors.price");
      if (v.compare.trim() && parseAmount(v.compare) === null)
        found[`compare-${id}`] = t("editor.errors.price");
      if (parseAmount(v.threshold) === null)
        found[`threshold-${id}`] = t("editor.errors.threshold");
    }
    for (const key of NUMBER_KEYS) {
      const value = form.attrs[key]?.trim();
      if (value && parseMeasure(value) === null)
        found[`attr-${key}`] = t("editor.errors.measure");
    }
    return found;
  };

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        brand_id: form.brandId || null,
        category_id: form.categoryId,
        model: form.model.trim() || null,
        warranty_text: form.warranty.trim() || null,
        specifications: specificationsOf(form),
        status: form.status,
        // Platform merchandising only; the seller routes never receive it.
        ...(scope.merchandising ? { is_featured: form.featured } : {}),
      };
      const slug = form.slug.trim();
      if (!product) {
        return scope.api.createProduct({ ...body, slug: slug || null });
      }
      if (!manage) {
        // Moderation (SC-06): only the visibility and the featured flag; the backend refuses the rest.
        const moderation: { status?: ProductStatus; is_featured?: boolean } =
          {};
        if (form.status !== product.status) moderation.status = form.status;
        if (scope.merchandising && form.featured !== product.is_featured)
          moderation.is_featured = form.featured;
        if (Object.keys(moderation).length > 0)
          await scope.api.updateProduct(product.id, moderation);
        return product;
      }
      // Only what changed, so a slug or status rule is checked only when it is edited.
      const before = initialForm(product);
      const changes: components["schemas"]["SellerProductUpdateRequest"] & {
        is_featured?: boolean;
      } = {};
      if (body.name !== product.name) changes.name = body.name;
      if (form.description !== before.description)
        changes.description = body.description;
      if (form.brandId !== before.brandId) changes.brand_id = body.brand_id;
      if (form.categoryId !== before.categoryId)
        changes.category_id = body.category_id;
      if (form.model !== before.model) changes.model = body.model;
      if (form.warranty !== before.warranty)
        changes.warranty_text = body.warranty_text;
      if (
        JSON.stringify(body.specifications) !==
        JSON.stringify(specificationsOf(before))
      )
        changes.specifications = body.specifications;
      if (scope.merchandising && form.featured !== before.featured)
        changes.is_featured = form.featured;
      if (slug && slug !== product.slug) changes.slug = slug;
      // Variant prices first: publishing checks the product as it will be.
      for (const variant of product.variants) {
        const edit = variants[variant.id];
        const was = variantEdit(variant);
        if (!edit || JSON.stringify(edit) === JSON.stringify(was)) continue;
        await scope.api.updateVariant(product.id, variant.id, {
          price: parseAmount(edit.price),
          compare_at_price: edit.compare.trim()
            ? parseAmount(edit.compare)
            : null,
          low_stock_threshold: parseAmount(edit.threshold),
          is_active: edit.active,
        });
      }
      if (form.status !== product.status) changes.status = form.status;
      if (Object.keys(changes).length === 0) return product;
      await scope.api.updateProduct(product.id, changes);
      return product;
    },
    onSuccess: (saved) => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: [scope.key] });
      if (!product) router.replace(`${scope.base}/products/${saved.id}`);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "slug_taken")
        setErrors({ slug: t("editor.errors.slugTaken") });
      else if (
        error instanceof ApiError &&
        error.code === "product_has_no_images"
      )
        setErrors({ status: t("editor.errors.noImages") });
      else if (error instanceof ApiError && error.status === 422)
        setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
      // Variant changes may have been saved before the product failed.
      if (product)
        void client.invalidateQueries({
          queryKey: [scope.key, "product", product.id],
        });
    },
  });

  const submit = () => {
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  const title = product ? product.name : t("editor.newTitle");
  const disabled = !(manage || moderate) || save.isPending;
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col gap-5"
    >
      <PageHeader
        title={title}
        back={{ label: t("editor.back"), href: `${scope.base}/products` }}
        badges={
          product && (
            <Badge tone={PRODUCT_TONE[product.status]}>
              {t(`products.status.${product.status}`)}
            </Badge>
          )
        }
        actions={
          <>
            {product?.status === "active" && (
              <a
                href={`/product/${product.slug}`}
                target="_blank"
                rel="noopener noreferrer"
                className={buttonClasses({ variant: "neutral", size: "sm" })}
              >
                {t("editor.viewOnStore")}
              </a>
            )}
            <NextLink
              href={`${scope.base}/products`}
              className={buttonClasses({ variant: "neutral", size: "sm" })}
            >
              {t("common.cancel")}
            </NextLink>
            {(manage || moderate) && (
              <Button type="submit" size="sm" disabled={disabled}>
                {product ? t("common.saveChanges") : t("editor.create")}
              </Button>
            )}
          </>
        }
      />
      {Object.keys(errors).length > 0 && (
        <p
          role="alert"
          className="rounded-xl border border-err-bd bg-err-bg px-5 py-3 text-sm text-err-tx"
        >
          {t("editor.fixErrors")}
        </p>
      )}
      {!manage && moderate && (
        <p className="rounded-xl border border-pri/20 bg-light px-5 py-3 text-sm text-tx">
          {t("editor.moderationNote")}
        </p>
      )}
      <div className="m-0 flex min-w-0 flex-wrap items-start gap-5 border-0 p-0">
        <fieldset
          disabled={!manage}
          className="m-0 flex min-w-0 flex-[999_1_560px] flex-col gap-5 border-0 p-0"
        >
          <Card padding={24} className="flex flex-col gap-4">
            <h2 className="t-h3">{t("editor.details")}</h2>
            <Field label={t("editor.name")} error={errors.name}>
              {(c) => (
                <Input
                  {...c}
                  maxLength={240}
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                />
              )}
            </Field>
            <Field label={t("editor.description")} error={errors.description}>
              {(c) => (
                <Textarea
                  {...c}
                  rows={4}
                  value={form.description}
                  onChange={(e) => update("description", e.target.value)}
                />
              )}
            </Field>
            <div className="grid gap-4 md:grid-cols-2">
              <CategoryFields
                categories={categories.data}
                brands={brands.data}
                categoryId={form.categoryId}
                brandId={form.brandId}
                savedCategoryId={product?.category_id ?? ""}
                savedBrandId={product?.brand_id ?? ""}
                errors={errors}
                onCategory={(id) => update("categoryId", id)}
                onBrand={(id) => update("brandId", id)}
              />
              <Field label={t("editor.model")} error={errors.model}>
                {(c) => (
                  <Input
                    {...c}
                    maxLength={160}
                    value={form.model}
                    onChange={(e) => update("model", e.target.value)}
                  />
                )}
              </Field>
            </div>
            <Field
              label={t("editor.warranty")}
              error={errors.warranty_text}
              className="max-w-[420px]"
            >
              {(c) => (
                <Input
                  {...c}
                  placeholder={t("editor.warrantyPlaceholder")}
                  value={form.warranty}
                  onChange={(e) => update("warranty", e.target.value)}
                />
              )}
            </Field>
          </Card>

          {product ? (
            <Images product={product} manage={manage} />
          ) : (
            <Card padding={24} className="flex flex-col gap-2">
              <h2 className="t-h3">{t("editor.images")}</h2>
              <p className="text-sm text-tx2">{t("editor.saveFirst")}</p>
            </Card>
          )}

          {product && (
            <Variants
              product={product}
              edits={variants}
              setEdits={setVariants}
              errors={errors}
              manage={manage}
            />
          )}

          <FurnitureFields
            categories={categories.data}
            categoryId={form.categoryId}
            values={form.attrs}
            errors={errors}
            onChange={(attrs) => update("attrs", attrs)}
          />

          <Card padding={24} className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="t-h3">{t("editor.specs")}</h2>
              <Button
                variant="ghost"
                size="sm"
                className="px-0"
                onClick={() =>
                  update("specs", [...form.specs, { key: "", value: "" }])
                }
              >
                {t("editor.addRow")}
              </Button>
            </div>
            <PairRows
              rows={form.specs}
              onChange={(rows) => update("specs", rows)}
              nameLabel={t("editor.specName")}
              valueLabel={t("editor.specValue")}
            />
            {errors.specifications && (
              <span className="text-cap text-err-fg">{errors.specifications}</span>
            )}
          </Card>
        </fieldset>

        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <fieldset
            disabled={!(manage || moderate)}
            className="m-0 min-w-0 border-0 p-0"
          >
            <Card padding={20} className="flex flex-col gap-3">
              <h2 className="t-h4">{t("editor.visibility")}</h2>
              <div
                role="radiogroup"
                aria-label={t("editor.visibility")}
                className="flex flex-col gap-2.5"
              >
                {(
                  [
                    "active",
                    "hidden",
                    "draft",
                    ...(product?.status === "archived" || (!manage && moderate)
                      ? (["archived"] as const)
                      : []),
                  ] as ProductStatus[]
                ).map((s) => (
                  <RadioOption
                    key={s}
                    name="status"
                    checked={form.status === s}
                    onChange={() => update("status", s)}
                    className="p-3 has-checked:p-[11px]"
                    label={
                      <span className="flex flex-col">
                        <b className="text-sm font-semibold">
                          {t(`products.status.${s}`)}
                        </b>
                        <span className="text-cap text-tx2">
                          {t(`editor.statusHint.${s}`)}
                        </span>
                      </span>
                    }
                  />
                ))}
              </div>
              {errors.status && (
                <span className="text-cap text-err-fg">{errors.status}</span>
              )}
              {scope.merchandising && (
                <Checkbox
                  label={t("editor.featured")}
                  checked={form.featured}
                  onChange={(e) => update("featured", e.target.checked)}
                />
              )}
            </Card>
          </fieldset>
          {product && <StockSummary product={product} />}
          <fieldset disabled={!manage} className="m-0 min-w-0 border-0 p-0">
            <Card padding={20} className="flex flex-col gap-2.5">
              <h2 className="t-h4">{t("editor.seo")}</h2>
              <Field
                label={t("editor.slug")}
                error={errors.slug}
                help={product ? undefined : t("editor.slugHelp")}
              >
                {(c) => (
                  <Input
                    {...c}
                    maxLength={260}
                    value={form.slug}
                    onChange={(e) =>
                      update("slug", e.target.value.toLowerCase())
                    }
                  />
                )}
              </Field>
            </Card>
          </fieldset>
        </div>
      </div>
    </form>
  );
}

/** The attribute set for a category: its own, else its main category's, else the default. */
export function attributeSetFor(
  definitions: { default_set: string[]; sets: Record<string, string[]> },
  categories: readonly CategoryNode[],
  categoryId: string,
): string[] {
  const category = categories.find((c) => c.id === categoryId);
  const parent = category?.parent_id
    ? categories.find((c) => c.id === category.parent_id)
    : undefined;
  for (const slug of [category?.slug, parent?.slug])
    if (slug && definitions.sets[slug]) return definitions.sets[slug];
  return definitions.default_set;
}

/** Furniture details (ADR-014 decision 14): the attributes of the category's set (from GET
 * /catalog/attributes, never hard-coded per category), plus any other attribute the product
 * already has, so a change of category loses nothing. The backend checks every value again. */
function FurnitureFields({
  categories,
  categoryId,
  values,
  errors,
  onChange,
}: {
  categories: CategoryNode[] | undefined;
  categoryId: string;
  values: AttributeValues;
  errors: Record<string, string>;
  onChange: (values: AttributeValues) => void;
}) {
  const t = useTranslations("admin");
  const tf = useTranslations("furniture");
  const definitions = useQuery({
    queryKey: ["catalog-attributes"],
    staleTime: Infinity,
    queryFn: async () => {
      const { data, error, response } = await browserApi.GET(
        "/api/v1/catalog/attributes",
      );
      if (!data) throw ApiError.from(response.status, error);
      return data;
    },
  });
  if (!definitions.data || !categoryId) return null;
  const set = attributeSetFor(definitions.data, categories ?? [], categoryId);
  const keys = ATTRIBUTE_KEYS.filter((key) => set.includes(key) || values[key]);
  if (keys.length === 0) return null;
  const put = (key: AttributeKey, value: string) =>
    onChange({ ...values, [key]: value });
  return (
    <Card padding={24} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 className="t-h3">{t("editor.furniture")}</h2>
        <p className="text-sm text-tx2">{t("editor.furnitureHelp")}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {keys.map((key) => {
          const label = tf(`names.${key}`);
          const value = values[key] ?? "";
          if (isNumberKey(key))
            return (
              <Field
                key={key}
                label={`${label} (${key.endsWith("_kg") ? "kg" : "cm"})`}
                error={errors[`attr-${key}`]}
              >
                {(c) => (
                  <Input
                    {...c}
                    inputMode="decimal"
                    maxLength={12}
                    value={value}
                    onChange={(e) => put(key, e.target.value)}
                  />
                )}
              </Field>
            );
          if ((BOOLEAN_KEYS as readonly string[]).includes(key))
            return (
              <Field key={key} label={label}>
                {(c) => (
                  <Select
                    {...c}
                    value={value}
                    onChange={(e) => put(key, e.target.value)}
                  >
                    <option value="">{t("editor.notSet")}</option>
                    <option value="true">{tf("yes")}</option>
                    <option value="false">{tf("no")}</option>
                  </Select>
                )}
              </Field>
            );
          const codes: readonly string[] = CHOICES[key as ChoiceKey];
          return (
            <Field key={key} label={label}>
              {(c) => (
                <Select
                  {...c}
                  value={value}
                  onChange={(e) => put(key, e.target.value)}
                >
                  <option value="">{t("editor.notSet")}</option>
                  {codes.map((code) => (
                    <option key={code} value={code}>
                      {tf(`${key}.${code}`)}
                    </option>
                  ))}
                  {value && !codes.includes(value) && (
                    <option value={value}>{value}</option>
                  )}
                </Select>
              )}
            </Field>
          );
        })}
      </div>
    </Card>
  );
}

/** Name/value rows for specifications and variant attributes. */
/** Main category, then its subcategory (optional), then brand: loaded from the staff lists,
 * never hard-coded. Changing the main category clears the subcategory; the product stores the
 * subcategory when one is picked, otherwise the main category (category hierarchy, 2026-11-16). */
function CategoryFields({
  categories,
  brands,
  categoryId,
  brandId,
  savedCategoryId,
  savedBrandId,
  errors,
  onCategory,
  onBrand,
}: {
  categories: CategoryNode[] | undefined;
  brands:
    | {
        id: string;
        name: string;
        is_active: boolean;
        category_ids?: string[];
      }[]
    | undefined;
  categoryId: string;
  brandId: string;
  savedCategoryId: string;
  savedBrandId: string;
  errors: Record<string, string>;
  onCategory: (id: string) => void;
  onBrand: (id: string) => void;
}) {
  const t = useTranslations("admin");
  const all = categories ?? [];
  const { mainId, subId } = splitCategory(all, categoryId);
  const mains = mainOptions(all, savedCategoryId);
  const subs = subOptions(all, mainId, savedCategoryId);
  const label = (o: Option) =>
    o.hidden ? t("editor.hiddenOption", { name: o.name }) : o.name;
  // A server error about the category belongs to the picker that holds the stored value.
  const categoryError = errors.category_id;
  return (
    <>
      <Field
        label={t("editor.mainCategory")}
        error={subId ? undefined : categoryError}
      >
        {(c) => (
          <Select
            {...c}
            value={mainId}
            disabled={!categories}
            onChange={(e) => onCategory(e.target.value)}
          >
            <option value="" disabled>
              {categories
                ? t("editor.chooseCategory")
                : t("editor.loadingCategories")}
            </option>
            {mains.map((o) => (
              <option key={o.id} value={o.id}>
                {label(o)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field
        label={t("editor.subcategory")}
        error={subId ? categoryError : undefined}
        help={
          mainId && subs.length > 0 && !subId
            ? t("editor.subcategoryHelp")
            : undefined
        }
      >
        {(c) => (
          <Select
            {...c}
            value={subId}
            disabled={!mainId || subs.length === 0}
            onChange={(e) => onCategory(e.target.value || mainId)}
          >
            <option value="">
              {!mainId
                ? t("editor.chooseMainFirst")
                : subs.length === 0
                  ? t("editor.noSubcategories")
                  : t("editor.noSubcategory")}
            </option>
            {subs.map((o) => (
              <option key={o.id} value={o.id}>
                {label(o)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={t("editor.brand")} error={errors.brand_id}>
        {(c) => (
          <Select
            {...c}
            value={brandId}
            onChange={(e) => onBrand(e.target.value)}
          >
            <option value="">{t("editor.noBrand")}</option>
            {(() => {
              // The main category's brands first, as a suggestion; every brand stays available.
              const { own, other } = groupBrandOptions(
                brandOptions(brands ?? [], savedBrandId),
                brands ?? [],
                mainId,
              );
              const opts = (list: Option[]) =>
                list.map((o) => (
                  <option key={o.id} value={o.id}>
                    {label(o)}
                  </option>
                ));
              if (own.length === 0) return opts(other);
              const main = all.find((c) => c.id === mainId);
              return (
                <>
                  <optgroup
                    label={t("editor.brandsIn", { name: main?.name ?? "" })}
                  >
                    {opts(own)}
                  </optgroup>
                  {other.length > 0 && (
                    <optgroup label={t("editor.otherBrands")}>
                      {opts(other)}
                    </optgroup>
                  )}
                </>
              );
            })()}
          </Select>
        )}
      </Field>
    </>
  );
}

function PairRows({
  rows,
  onChange,
  nameLabel,
  valueLabel,
}: {
  rows: Row[];
  onChange: (rows: Row[]) => void;
  nameLabel: string;
  valueLabel: string;
}) {
  const t = useTranslations("admin.editor");
  const set = (i: number, patch: Partial<Row>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="flex flex-col gap-2.5">
      {rows.map((row, i) => (
        <div key={i} className="flex gap-2.5">
          <Input
            aria-label={`${nameLabel} ${i + 1}`}
            value={row.key}
            maxLength={120}
            onChange={(e) => set(i, { key: e.target.value })}
            className="flex-1"
          />
          <Input
            aria-label={`${valueLabel} ${i + 1}`}
            value={row.value}
            maxLength={500}
            onChange={(e) => set(i, { value: e.target.value })}
            className="flex-[2]"
          />
          <button
            type="button"
            aria-label={t("removeRow", { n: i + 1 })}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="flex size-11 flex-none cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-tx2 hover:bg-page"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ---- Images ------------------------------------------------------------------------------------

/** Product photos: the first is the cover; drag (or the arrow buttons) to reorder, which saves at
 * once. Each photo shows its bulk-upload file name. */
function Images({ product, manage }: { product: Product; manage: boolean }) {
  const t = useTranslations("admin.editor");
  const scope = useCatalogScope();
  const client = useQueryClient();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const saved = product.images
    .filter((i) => i.variant_id === null)
    .sort((a, b) => a.sort_order - b.sort_order);
  const [order, setOrder] = useState<string[] | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [editing, setEditing] = useState<ProductImageRow | null>(null);
  const images = order
    ? order
        .map((id) => saved.find((i) => i.id === id))
        .filter((i): i is ProductImageRow => Boolean(i))
    : saved;
  const fileNames = new Map(
    product.photo_file_names.map((f) => [f.image_id, f.file_name]),
  );
  const refresh = () =>
    client.invalidateQueries({ queryKey: [scope.key, "product", product.id] });

  const reorder = useMutation({
    mutationFn: (ids: string[]) => scope.api.reorderImages(product.id, ids),
    onSuccess: () => toast.show(t("orderSaved")),
    onError: () => {
      setOrder(null);
      toast.show(t("orderFailed"), "error");
    },
    onSettled: () => void refresh(),
  });
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let failed = 0;
      for (const file of files) {
        if (
          file.size > IMAGE_MAX_BYTES ||
          !IMAGE_TYPES.split(",").includes(file.type)
        ) {
          failed += 1;
          continue;
        }
        await scope.api
          .uploadImage(product.id, file)
          .catch(() => (failed += 1));
      }
      return { done: files.length - failed, failed };
    },
    onSuccess: ({ done, failed }) =>
      toast.show(
        failed
          ? t("uploadPartly", { done, failed })
          : t("uploaded", { count: done }),
        failed ? "error" : "success",
      ),
    onSettled: () => void refresh(),
  });
  const remove = useMutation({
    mutationFn: (id: string) => scope.api.deleteImage(id),
    onSuccess: () => toast.show(t("imageDeleted")),
    onError: (error) =>
      toast.show(
        error instanceof ApiError && error.code === "last_product_image"
          ? t("lastImage")
          : t("deleteFailed"),
        "error",
      ),
    onSettled: () => void refresh(),
  });

  const move = (from: number, to: number) => {
    if (to < 0 || to >= images.length || from === to) return;
    const ids = moveItem(
      images.map((i) => i.id),
      from,
      to,
    );
    setOrder(ids);
    reorder.mutate(ids);
  };

  return (
    <Card padding={24} className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="t-h3">{t("images")}</h2>
        <span className="text-cap text-tx2">{t("imagesHint")}</span>
      </div>
      <ol className="m-0 flex list-none flex-wrap gap-3 p-0">
        {images.map((image, i) => (
          // Dragging is a pointer shortcut; the move buttons below do the same from the keyboard.
          // eslint-disable-next-line jsx-a11y-x/no-noninteractive-element-interactions
          <li
            key={image.id}
            draggable={manage}
            onDragStart={() => setDragging(i)}
            onDragOver={(e) => {
              if (dragging !== null) e.preventDefault();
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (dragging !== null) move(dragging, i);
              setDragging(null);
            }}
            onDragEnd={() => setDragging(null)}
            className={cx(
              "flex w-[112px] flex-col gap-1.5",
              manage && "cursor-grab",
              dragging === i && "opacity-50",
            )}
          >
            <span
              className={cx(
                "relative flex size-[112px] items-center justify-center rounded-[10px] bg-card",
                i === 0 ? "border-2 border-pri" : "border border-bd",
              )}
            >
              <Thumb
                image={{
                  url: image.thumbnail_url,
                  width: image.width,
                  height: image.height,
                  alt: image.alt_text ?? "",
                  position: i,
                }}
                size={96}
                alt={image.alt_text ?? ""}
              />
              {i === 0 && (
                <span className="absolute bottom-1.5 left-1.5">
                  <Badge tone="info">{t("cover")}</Badge>
                </span>
              )}
            </span>
            <span
              className="truncate text-cap text-tx2"
              title={fileNames.get(image.id)}
            >
              {fileNames.get(image.id)}
            </span>
            {manage && (
              <span className="flex items-center justify-between">
                <span className="flex">
                  <IconAction
                    label={t("moveEarlier", { n: i + 1 })}
                    disabled={i === 0 || reorder.isPending}
                    onClick={() => move(i, i - 1)}
                  >
                    <ChevronLeft size={14} aria-hidden="true" />
                  </IconAction>
                  <IconAction
                    label={t("moveLater", { n: i + 1 })}
                    disabled={i === images.length - 1 || reorder.isPending}
                    onClick={() => move(i, i + 1)}
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                  </IconAction>
                </span>
                <span className="flex">
                  <IconAction
                    label={t("altOf", { n: i + 1 })}
                    onClick={() => setEditing(image)}
                  >
                    <Pencil size={14} aria-hidden="true" />
                  </IconAction>
                  <IconAction
                    label={t("deletePhoto", { n: i + 1 })}
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(image.id)}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </IconAction>
                </span>
              </span>
            )}
          </li>
        ))}
        {manage && (
          <li>
            <button
              type="button"
              disabled={upload.isPending}
              onClick={() => input.current?.click()}
              className="flex size-[112px] cursor-pointer flex-col items-center justify-center gap-1 rounded-[10px] border-[1.5px] border-dashed border-bd2 bg-page text-tx2 disabled:opacity-60"
            >
              <ImagePlus size={20} aria-hidden="true" />
              <span className="text-cap font-medium">
                {upload.isPending ? t("uploading") : t("upload")}
              </span>
            </button>
            <input
              ref={input}
              type="file"
              accept={IMAGE_TYPES}
              multiple
              hidden
              onChange={(e) => {
                const files = [...(e.target.files ?? [])];
                e.target.value = "";
                if (files.length) upload.mutate(files);
              }}
            />
          </li>
        )}
      </ol>
      {editing && (
        <AltTextDialog
          image={editing}
          onClose={() => setEditing(null)}
          onSaved={() => void refresh()}
        />
      )}
    </Card>
  );
}

function IconAction({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex size-7 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-tx2 hover:bg-page disabled:cursor-default disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function AltTextDialog({
  image,
  onClose,
  onSaved,
}: {
  image: ProductImageRow;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("admin");
  const scope = useCatalogScope();
  const toast = useToast();
  const [alt, setAlt] = useState(image.alt_text ?? "");
  const save = useMutation({
    mutationFn: () => scope.api.updateImage(image.id, alt.trim() || null),
    onSuccess: () => {
      toast.show(t("common.saved"));
      onSaved();
      onClose();
    },
    onError: () => toast.show(t("common.saveError"), "error"),
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("editor.altTitle")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Field label={t("editor.altLabel")} help={t("editor.altHelp")}>
        {(c) => (
          <Input
            {...c}
            maxLength={300}
            value={alt}
            onChange={(e) => setAlt(e.target.value)}
          />
        )}
      </Field>
    </Dialog>
  );
}

// ---- Variants ----------------------------------------------------------------------------------

function Variants({
  product,
  edits,
  setEdits,
  errors,
  manage,
}: {
  product: Product;
  edits: Record<string, VariantEdit>;
  setEdits: (
    fn: (prev: Record<string, VariantEdit>) => Record<string, VariantEdit>,
  ) => void;
  errors: Record<string, string>;
  manage: boolean;
}) {
  const t = useTranslations("admin.editor");
  const stock = useVariantStock(product);
  const [adding, setAdding] = useState(false);
  const set = (id: string, patch: Partial<VariantEdit>) =>
    setEdits((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  const small = "h-9 text-sm";
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-bd px-5 py-[18px]">
        <h2 className="t-h3">{t("variants")}</h2>
        {manage && (
          <Button
            variant="secondary"
            size="sm"
            className="gap-1.5"
            onClick={() => setAdding(true)}
          >
            <Plus size={14} aria-hidden="true" />
            {t("addVariant")}
          </Button>
        )}
      </div>
      {product.variants.length === 0 ? (
        <p className="px-5 py-6 text-sm text-tx2">{t("noVariants")}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t("columns.variant")}</Th>
              <Th>{t("columns.sku")}</Th>
              <Th>{t("columns.price")}</Th>
              <Th>{t("columns.compare")}</Th>
              <Th>{t("columns.lowAt")}</Th>
              <Th>{t("columns.stock")}</Th>
              <Th>{t("columns.active")}</Th>
            </tr>
          </thead>
          <tbody>
            {product.variants.map((v) => {
              const edit = edits[v.id] ?? variantEdit(v);
              const attrs = Object.values(v.attributes).map(String).join(" · ");
              const available = stock.get(v.id);
              return (
                <tr key={v.id}>
                  <Td>
                    <span className="flex flex-col">
                      <b className="font-medium whitespace-nowrap">{v.name}</b>
                      {attrs && (
                        <span className="text-cap text-tx2">{attrs}</span>
                      )}
                    </span>
                  </Td>
                  <Td className="whitespace-nowrap text-tx2">{v.sku}</Td>
                  <Td>
                    <Input
                      aria-label={t("priceOf", { name: v.name })}
                      aria-invalid={errors[`price-${v.id}`] ? true : undefined}
                      inputMode="numeric"
                      value={edit.price}
                      onChange={(e) => set(v.id, { price: e.target.value })}
                      className={small}
                      style={{ width: 120 }}
                    />
                  </Td>
                  <Td>
                    <Input
                      aria-label={t("compareOf", { name: v.name })}
                      aria-invalid={
                        errors[`compare-${v.id}`] ? true : undefined
                      }
                      inputMode="numeric"
                      placeholder="—"
                      value={edit.compare}
                      onChange={(e) => set(v.id, { compare: e.target.value })}
                      className={small}
                      style={{ width: 110 }}
                    />
                  </Td>
                  <Td>
                    <Input
                      aria-label={t("lowAtOf", { name: v.name })}
                      aria-invalid={
                        errors[`threshold-${v.id}`] ? true : undefined
                      }
                      inputMode="numeric"
                      value={edit.threshold}
                      onChange={(e) => set(v.id, { threshold: e.target.value })}
                      className={small}
                      style={{ width: 80 }}
                    />
                  </Td>
                  <Td
                    className={cx("font-medium", available === 0 && "text-err-fg")}
                  >
                    {available ?? "—"}
                  </Td>
                  <Td>
                    <Toggle
                      checked={edit.active}
                      disabled={!manage}
                      onChange={(next) => set(v.id, { active: next })}
                      label={
                        <span className="sr-only">
                          {t("activeOf", { name: v.name })}
                        </span>
                      }
                    />
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {adding && (
        <AddVariantDialog product={product} onClose={() => setAdding(false)} />
      )}
    </Card>
  );
}

/** Each variant's available stock, from the inventory list (stock changes only through Inventory). */
function useVariantStock(product: Product): Map<string, number> {
  const scope = useCatalogScope();
  const query = useQuery({
    queryKey: [scope.key, "inventory", "product", product.id],
    queryFn: () =>
      scope.api.inventory({ q: product.name.slice(0, 160), size: 100 }),
    enabled: scope.stock,
  });
  return new Map(
    (query.data?.items ?? [])
      .filter((i) => i.product_id === product.id)
      .map((i) => [i.variant_id, i.available_quantity]),
  );
}

function StockSummary({ product }: { product: Product }) {
  const t = useTranslations("admin.editor");
  const scope = useCatalogScope();
  const stock = useVariantStock(product);
  if (!scope.stock) return null;
  const total = [...stock.values()].reduce((a, b) => a + b, 0);
  const thresholds = [
    ...new Set(product.variants.map((v) => v.low_stock_threshold)),
  ];
  return (
    <Card padding={20} className="flex flex-col gap-2.5">
      <h2 className="t-h4">{t("stock")}</h2>
      <div className="kv">
        <span>{t("totalStock")}</span>
        <b className="font-semibold">{total}</b>
      </div>
      {thresholds.length > 0 && (
        <div className="kv">
          <span>{t("lowAlert")}</span>
          <span>
            {thresholds.length === 1
              ? t("units", { count: thresholds[0] })
              : t("perVariant")}
          </span>
        </div>
      )}
      <NextLink
        href={`${scope.base}/inventory?q=${encodeURIComponent(product.name.slice(0, 160))}`}
        className="text-sm font-medium"
      >
        {t("openInventory")}
      </NextLink>
    </Card>
  );
}

function AddVariantDialog({
  product,
  onClose,
}: {
  product: Product;
  onClose: () => void;
}) {
  const t = useTranslations("admin");
  const scope = useCatalogScope();
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [price, setPrice] = useState("");
  const [compare, setCompare] = useState("");
  const [threshold, setThreshold] = useState("5");
  const [attributes, setAttributes] = useState<Row[]>([{ key: "", value: "" }]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const create = useMutation({
    mutationFn: () =>
      scope.api.createVariant(product.id, {
        name: name.trim(),
        sku: sku.trim(),
        price: parseAmount(price) ?? 0,
        compare_at_price: compare.trim() ? parseAmount(compare) : null,
        low_stock_threshold: parseAmount(threshold) ?? 0,
        attributes: rowsToObject(attributes),
        is_active: true,
      }),
    onSuccess: () => {
      toast.show(t("editor.variantAdded"));
      void client.invalidateQueries({ queryKey: [scope.key] });
      onClose();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "sku_taken")
        setErrors({ sku: t("editor.errors.skuTaken") });
      else if (error instanceof ApiError && error.status === 422)
        setErrors(bodyFieldErrors(error));
      else toast.show(t("common.saveError"), "error");
    },
  });
  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = t("editor.errors.variantName");
    if (!skuOk(sku.trim())) found.sku = t("editor.errors.sku");
    if (parseAmount(price) === null) found.price = t("editor.errors.price");
    if (compare.trim() && parseAmount(compare) === null)
      found.compare_at_price = t("editor.errors.price");
    if (parseAmount(threshold) === null)
      found.low_stock_threshold = t("editor.errors.threshold");
    setErrors(found);
    if (Object.keys(found).length === 0) create.mutate();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("editor.addVariant")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={create.isPending} onClick={submit}>
            {t("editor.addVariant")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("editor.variantName")} error={errors.name}>
            {(c) => (
              <Input
                {...c}
                maxLength={180}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("editor.columns.sku")} error={errors.sku}>
            {(c) => (
              <Input
                {...c}
                maxLength={80}
                value={sku}
                onChange={(e) => setSku(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("editor.columns.price")} error={errors.price}>
            {(c) => (
              <Input
                {...c}
                inputMode="numeric"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            )}
          </Field>
          <Field
            label={t("editor.columns.compare")}
            error={errors.compare_at_price}
            help={t("common.optional")}
          >
            {(c) => (
              <Input
                {...c}
                inputMode="numeric"
                value={compare}
                onChange={(e) => setCompare(e.target.value)}
              />
            )}
          </Field>
          <Field
            label={t("editor.columns.lowAt")}
            error={errors.low_stock_threshold}
          >
            {(c) => (
              <Input
                {...c}
                inputMode="numeric"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
              />
            )}
          </Field>
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {t("editor.attributes")}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="px-0"
              onClick={() =>
                setAttributes([...attributes, { key: "", value: "" }])
              }
            >
              {t("editor.addRow")}
            </Button>
          </div>
          <PairRows
            rows={attributes}
            onChange={setAttributes}
            nameLabel={t("editor.attributeName")}
            valueLabel={t("editor.attributeValue")}
          />
          <span className="text-cap text-tx2">
            {t("editor.attributesHelp")}
          </span>
        </div>
        <p className="text-cap text-tx2">{t("editor.stockNote")}</p>
      </div>
    </Dialog>
  );
}

function EditorSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-busy="true">
      <Skeleton className="h-14 w-80" />
      <div className="flex flex-wrap gap-5">
        <Skeleton className="h-[520px] min-w-0 flex-[999_1_560px]" />
        <Skeleton className="h-80 min-w-0 flex-[1_1_300px]" />
      </div>
    </div>
  );
}
