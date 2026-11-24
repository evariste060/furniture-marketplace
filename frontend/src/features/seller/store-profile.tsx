"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { bodyFieldErrors, LoadError, must, PageHeader, postFiles } from "@/features/admin/ui";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { localPhone } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { checkStoreForm, storeForm, type StoreForm, type StoreFormErrors } from "./store-form";
import { percent } from "./store-context";

type Store = components["schemas"]["SellerStoreResponse"];
const STORE_KEY = ["seller", "store"] as const;
const IMAGE_TYPES = "image/jpeg,image/png,image/webp";
const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/** /seller/store: the approved store's public details, contact details, logo and cover. Only the
 * fields the seller changed are sent; status, slug and commission are the marketplace's. */
export function StoreProfileView() {
  const query = useQuery({ queryKey: STORE_KEY, queryFn: () => must(browserApi.GET("/api/v1/seller/store")) });
  if (query.isError) return <LoadError onRetry={() => query.refetch()} />;
  if (!query.data) return <Skeleton className="h-[520px] w-full" />;
  return <ProfileForm key={query.data.name + query.data.contact_email + (query.data.description ?? "")} store={query.data} />;
}

function ProfileForm({ store }: { store: Store }) {
  const t = useTranslations("admin");
  const ts = useTranslations("admin.seller.store");
  const toast = useToast();
  const client = useQueryClient();
  const router = useRouter();
  const [form, setForm] = useState<StoreForm>(() => storeForm(store));
  const [errors, setErrors] = useState<StoreFormErrors>({});
  const update = <K extends keyof StoreForm>(key: K, value: StoreForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const before = storeForm(store);
      const body: components["schemas"]["StoreProfileUpdate"] = {};
      if (form.name.trim() !== before.name) body.name = form.name.trim();
      if (form.description.trim() !== before.description) body.description = form.description.trim() || null;
      if (form.email.trim() !== before.email) body.contact_email = form.email.trim();
      if (localPhone(form.phone) !== localPhone(before.phone)) body.contact_phone = form.phone.trim();
      if (form.district.trim() !== before.district) body.district = form.district.trim();
      if (form.sector.trim() !== before.sector) body.sector = form.sector.trim() || null;
      if (form.street.trim() !== before.street) body.street_address = form.street.trim() || null;
      if (Object.keys(body).length === 0) return Promise.resolve(store);
      return must(browserApi.PATCH("/api/v1/seller/store", { body }));
    },
    onSuccess: (saved) => {
      client.setQueryData(STORE_KEY, saved);
      toast.show(t("common.saved"));
      // The shell shows the store's name: read it again on the server.
      router.refresh();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "store_name_taken") setErrors({ name: ts("errors.nameTaken") });
      else if (error instanceof ApiError && error.status === 422) setErrors(apiFieldErrors(bodyFieldErrors(error)));
      else toast.show(t("common.saveError"), "error");
    },
  });

  const submit = () => {
    const found = checkStoreForm(form);
    setErrors(Object.fromEntries(Object.entries(found).map(([key, code]) => [key, ts(`errors.${code}`)])));
    if (Object.keys(found).length === 0) save.mutate();
  };

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
        title={ts("title")}
        description={ts("description")}
        actions={
          <Button type="submit" size="sm" disabled={save.isPending}>
            {t("common.saveChanges")}
          </Button>
        }
      />
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <Card padding={24} className="flex flex-col gap-4">
            <h2 className="t-h3">{ts("details")}</h2>
            <Field label={ts("name")} error={errors.name}>
              {(c) => <Input {...c} maxLength={120} value={form.name} onChange={(e) => update("name", e.target.value)} />}
            </Field>
            <Field label={ts("about")} error={errors.description}>
              {(c) => <Textarea {...c} rows={4} maxLength={2000} value={form.description} onChange={(e) => update("description", e.target.value)} />}
            </Field>
          </Card>
          <Card padding={24} className="flex flex-col gap-4">
            <h2 className="t-h3">{ts("contact")}</h2>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label={ts("email")} error={errors.email}>
                {(c) => <Input {...c} type="email" maxLength={254} value={form.email} onChange={(e) => update("email", e.target.value)} />}
              </Field>
              <Field label={ts("phone")} error={errors.phone}>
                {(c) => <Input {...c} type="tel" inputMode="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} />}
              </Field>
            </div>
          </Card>
          <Card padding={24} className="flex flex-col gap-4">
            <h2 className="t-h3">{ts("location")}</h2>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label={ts("district")} error={errors.district}>
                {(c) => <Input {...c} maxLength={120} value={form.district} onChange={(e) => update("district", e.target.value)} />}
              </Field>
              <Field label={ts("sector")} error={errors.sector} help={t("common.optional")}>
                {(c) => <Input {...c} maxLength={120} value={form.sector} onChange={(e) => update("sector", e.target.value)} />}
              </Field>
            </div>
            <Field label={ts("street")} error={errors.street} help={t("common.optional")}>
              {(c) => <Input {...c} maxLength={240} value={form.street} onChange={(e) => update("street", e.target.value)} />}
            </Field>
          </Card>
        </div>
        <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
          <Card padding={20} className="flex flex-col gap-4">
            <div className="flex flex-col gap-0.5">
              <h2 className="t-h4">{ts("images")}</h2>
              <span className="text-cap text-tx2">{ts("imageHelp")}</span>
            </div>
            <StoreImage field="logo" store={store} />
            <StoreImage field="cover" store={store} />
          </Card>
          <Card padding={20} className="flex flex-col gap-1.5">
            <h2 className="t-h4">{ts("commission")}</h2>
            <p className="m-0 text-sm text-tx2">{ts("commissionRate", { rate: percent(store.effective_commission_rate_bps) })}</p>
          </Card>
        </div>
      </div>
    </form>
  );
}

/** The backend's 422 field names → the form's. */
function apiFieldErrors(found: Record<string, string>): StoreFormErrors {
  const map: Record<string, keyof StoreForm> = { contact_email: "email", contact_phone: "phone", street_address: "street" };
  return Object.fromEntries(Object.entries(found).map(([key, message]) => [map[key] ?? key, message]));
}

function StoreImage({ field, store }: { field: "logo" | "cover"; store: Store }) {
  const t = useTranslations("admin.seller.store");
  const toast = useToast();
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const image = store[field];
  const onDone = (saved: Store, message: string) => {
    client.setQueryData(STORE_KEY, saved);
    toast.show(message);
  };
  const upload = useMutation({
    mutationFn: (file: File) => postFiles<Store>(`seller/store/${field}`, "file", [file]),
    onSuccess: (saved) => onDone(saved, t("imageSaved")),
    onError: () => toast.show(t("imageFailed"), "error"),
  });
  const remove = useMutation({
    mutationFn: () =>
      field === "logo" ? must(browserApi.DELETE("/api/v1/seller/store/logo")) : must(browserApi.DELETE("/api/v1/seller/store/cover")),
    onSuccess: (saved) => onDone(saved, t("imageRemoved")),
    onError: () => toast.show(t("imageFailed"), "error"),
  });
  const busy = upload.isPending || remove.isPending;
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">{t(field)}</span>
      <span className={cx("flex items-center justify-center overflow-hidden rounded-[10px] border border-bd bg-card", field === "logo" ? "size-[112px]" : "aspect-[3/1] w-full")}>
        {image ? (
          <ProductImage image={image} sizes="300px" alt={image.alt} iconSize={28} className="size-full bg-card" />
        ) : (
          <span className="px-3 text-center text-cap text-tx2">{t("noImage")}</span>
        )}
      </span>
      <span className="flex gap-2">
        <Button variant="neutral" size="sm" disabled={busy} onClick={() => input.current?.click()} className="gap-1.5">
          <ImagePlus size={14} aria-hidden="true" />
          {upload.isPending ? t("uploading") : image ? t("replace") : t("upload")}
          <span className="sr-only"> {t(field)}</span>
        </Button>
        {image && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => remove.mutate()} className="gap-1.5 text-err-tx">
            <Trash2 size={14} aria-hidden="true" />
            {t("remove")}
            <span className="sr-only"> {t(field)}</span>
          </Button>
        )}
      </span>
      <input
        ref={input}
        type="file"
        accept={IMAGE_TYPES}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          if (file.size > IMAGE_MAX_BYTES || !IMAGE_TYPES.split(",").includes(file.type)) toast.show(t("imageFailed"), "error");
          else upload.mutate(file);
        }}
      />
    </div>
  );
}
