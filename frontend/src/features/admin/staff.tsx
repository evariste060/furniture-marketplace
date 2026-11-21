"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Phone, UserCog, UserPlus, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { browserApi } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { PASSWORD_MAX, passwordOk } from "@/lib/auth";
import { localPhone } from "@/lib/checkout";
import { cx } from "@/lib/cx";
import { formatDate, formatPhone } from "@/lib/format";
import { useStaffAccess } from "./access";
import type { StaffRole } from "./roles";
import { bodyFieldErrors, ListFooter, LoadError, must, PageHeader, useListParams } from "./ui";

type Staff = components["schemas"]["StaffResponse"];

const PAGE_SIZE = 50;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Staff.dc.html role badge colour. The Marketplace Administrator is the only staff role (SC-05). */
export const ROLE_TONE: Record<StaffRole, BadgeTone> = {
  administrator: "soft-info",
};

/** Initials for the avatar: the first letters of the first two words ("Jean Paul H" → "JP"). */
export function initials(name: string | null | undefined): string {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

/** Avatar colours of an active staff member. */
const AVATAR_TONE = "bg-light text-pri-h";
const STATUSES = ["", "active", "disabled"] as const;
type StatusFilter = (typeof STATUSES)[number];

/** Staff.dc.html. Filters live in the URL: status, page. Every staff member is a Marketplace
 * Administrator (SC-05), so there is no role filter or role picker. */
export function StaffView() {
  const t = useTranslations("admin");
  const { can, id: myId } = useStaffAccess();
  const { get, page, set, hrefWith } = useListParams();
  const manage = can("staff:manage");
  const status: StatusFilter = get("status") === "active" || get("status") === "disabled" ? (get("status") as StatusFilter) : "";
  const isActive = status === "" ? undefined : status === "active";
  const [editing, setEditing] = useState<Staff | "new" | null>(null);
  const list = useQuery({
    queryKey: ["admin", "staff", { status, page }],
    queryFn: () => must(browserApi.GET("/api/v1/staff", { params: { query: { is_active: isActive, page, size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title={t("staff.title")}
        description={t("staff.description")}
        actions={
          manage && (
            <Button size="sm" className="gap-2" onClick={() => setEditing("new")}>
              <UserPlus size={16} aria-hidden="true" />
              {t("staff.add")}
            </Button>
          )
        }
      />

      <section className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <div className="flex flex-wrap items-center gap-3 border-b border-bd p-4">
          <div role="group" aria-label={t("staff.statusLabel")} className="flex rounded-lg bg-page p-1">
            {STATUSES.map((s) => (
              <button
                key={s || "all"}
                type="button"
                aria-pressed={status === s}
                onClick={() => set({ status: s })}
                className={cx(
                  "h-8 cursor-pointer rounded-md border-0 px-3.5 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
                  status === s ? "bg-white text-tx shadow-sh" : "bg-transparent text-tx2 hover:text-tx",
                )}
              >
                {t(`staff.statuses.${s || "all"}`)}
              </button>
            ))}
          </div>
          {list.data && (
            <span aria-live="polite" className="ml-auto text-sm text-tx2 tabular-nums">
              {t("staff.count", { count: list.data.total })}
            </span>
          )}
        </div>

        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && list.data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-subtle text-tx2">
              <Users size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{status ? t("staff.noMatch") : t("staff.empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("staff.columns.name")}</Th>
                <Th>{t("staff.columns.role")}</Th>
                <Th>{t("staff.columns.contact")}</Th>
                <Th>{t("staff.columns.status")}</Th>
                <Th>{t("staff.columns.added")}</Th>
                {manage && (
                  <Th>
                    <span className="sr-only">{t("common.actions")}</span>
                  </Th>
                )}
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 5 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={manage ? 6 : 5}>
                        <Skeleton className="h-11 w-full" />
                      </Td>
                    </tr>
                  ))
                : list.data.items.map((s) => {
                    const name = s.full_name || s.email || s.phone || "—";
                    return (
                      <tr key={s.id} className={cx("transition-colors duration-150 hover:bg-page motion-reduce:transition-none", !s.is_active && "text-tx2")}>
                        <Td>
                          <span className="flex items-center gap-3">
                            <span aria-hidden="true" className={cx("flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold", s.is_active ? AVATAR_TONE : "bg-subtle text-tx2")}>
                              {initials(name)}
                            </span>
                            <span className="flex min-w-0 flex-col">
                              <span className="flex flex-wrap items-center gap-2">
                                <b className={cx("font-semibold", s.is_active ? "text-tx" : "text-tx2")}>{name}</b>
                                {s.id === myId && <Badge tone="soft-info">{t("staff.you")}</Badge>}
                              </span>
                            </span>
                          </span>
                        </Td>
                        <Td>
                          <Badge tone={ROLE_TONE[s.role]}>{t(`shell.roles.${s.role}`)}</Badge>
                        </Td>
                        <Td>
                          <span className="flex flex-col gap-1 text-sm text-tx2">
                            {s.phone && (
                              <span className="flex items-center gap-1.5 whitespace-nowrap">
                                <Phone size={13} aria-hidden="true" className="flex-none" />
                                {formatPhone(s.phone)}
                              </span>
                            )}
                            {s.email && (
                              <span className="flex items-center gap-1.5 break-all">
                                <Mail size={13} aria-hidden="true" className="flex-none" />
                                {s.email}
                              </span>
                            )}
                          </span>
                        </Td>
                        <Td>
                          <span className={cx("inline-flex items-center gap-1.5 text-sm font-medium whitespace-nowrap", s.is_active ? "text-ok-tx" : "text-tx2")}>
                            <span aria-hidden="true" className={cx("size-2 rounded-full", s.is_active ? "bg-ok" : "bg-bd2")} />
                            {t(s.is_active ? "staff.active" : "staff.disabled")}
                          </span>
                        </Td>
                        <Td className="text-sm whitespace-nowrap text-tx2">{formatDate(s.created_at, "date")}</Td>
                        {manage && (
                          <Td className="text-right">
                            <Button variant="outline" size="sm" aria-label={t("staff.manageOf", { name })} onClick={() => setEditing(s)} className="gap-1.5">
                              <UserCog size={14} aria-hidden="true" />
                              {t("staff.manageShort")}
                            </Button>
                          </Td>
                        )}
                      </tr>
                    );
                  })}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>
      {editing === "new" && <AddStaffDialog onClose={() => setEditing(null)} />}
      {editing && editing !== "new" && <ManageStaffDialog key={editing.id} member={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function staffError(error: unknown, t: ReturnType<typeof useTranslations<"admin">>): Record<string, string> {
  if (error instanceof ApiError && error.code === "last_administrator") return { form: t("staff.errors.lastAdmin") };
  if (error instanceof ApiError && error.code === "email_taken") return { email: t("staff.errors.emailTaken") };
  if (error instanceof ApiError && error.code === "phone_taken") return { phone: t("staff.errors.phoneTaken") };
  if (error instanceof ApiError && error.status === 422) return bodyFieldErrors(error);
  return { form: t("common.saveError") };
}

function AddStaffDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: () => {
      const local = localPhone(phone);
      return must(
        browserApi.POST("/api/v1/staff", {
          body: { full_name: name.trim(), email: email.trim() || null, phone: local ? `+250${local}` : null, role: "administrator", password },
        }),
      );
    },
    onSuccess: () => {
      toast.show(t("staff.added"));
      void client.invalidateQueries({ queryKey: ["admin", "staff"] });
      onClose();
    },
    onError: (error) => setErrors(staffError(error, t)),
  });

  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.full_name = t("catalogue.errors.name");
    if (!email.trim() && !phone.trim()) found.email = t("staff.errors.contact");
    if (email.trim() && !EMAIL.test(email.trim())) found.email = t("staff.errors.email");
    if (phone.trim() && !localPhone(phone)) found.phone = t("staff.errors.phone");
    if (!passwordOk(password)) found.password = t("staff.errors.password");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("staff.add")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {t("staff.create")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label={t("staff.name")} error={errors.full_name}>
          {(c) => <Input {...c} maxLength={120} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label={t("staff.email")} error={errors.email}>
          {(c) => <Input {...c} type="email" maxLength={254} autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />}
        </Field>
        <Field label={t("staff.phone")} error={errors.phone} help={t("staff.contactHelp")}>
          {(c) => <Input {...c} type="tel" inputMode="tel" autoComplete="off" placeholder="07XX XXX XXX" value={phone} onChange={(e) => setPhone(e.target.value)} />}
        </Field>
        <p className="m-0 text-sm text-tx2">{t("staff.roleNote")}</p>
        <Field label={t("staff.password")} error={errors.password} help={t("staff.passwordHelp")}>
          {(c) => <Input {...c} type="password" autoComplete="new-password" maxLength={PASSWORD_MAX} value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        {errors.form && (
          <p role="alert" className="text-sm text-err-tx">
            {errors.form}
          </p>
        )}
      </div>
    </Dialog>
  );
}

function ManageStaffDialog({ member, onClose }: { member: Staff; onClose: () => void }) {
  const t = useTranslations("admin");
  const client = useQueryClient();
  const toast = useToast();
  const { id: myId } = useStaffAccess();
  const [name, setName] = useState(member.full_name ?? "");
  const [phone, setPhone] = useState(member.phone ? formatPhone(member.phone) : "");
  const [active, setActive] = useState(member.is_active);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const self = member.id === myId;

  const save = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { staff_id: member.id } } };
      const local = localPhone(phone);
      const details: { full_name?: string; phone?: string } = {};
      if (name.trim() !== (member.full_name ?? "")) details.full_name = name.trim();
      if (local && `+250${local}` !== member.phone) details.phone = `+250${local}`;
      if (Object.keys(details).length > 0) await must(browserApi.PATCH("/api/v1/staff/{staff_id}", { ...path, body: details }));
      if (active !== member.is_active) await must(browserApi.PATCH("/api/v1/staff/{staff_id}/status", { ...path, body: { is_active: active } }));
    },
    onSuccess: () => {
      toast.show(t("common.saved"));
      void client.invalidateQueries({ queryKey: ["admin", "staff"] });
      onClose();
    },
    onError: (error) => {
      void client.invalidateQueries({ queryKey: ["admin", "staff"] });
      setErrors(staffError(error, t));
    },
  });

  const submit = () => {
    const found: Record<string, string> = {};
    if (!name.trim()) found.full_name = t("catalogue.errors.name");
    if (phone.trim() ? !localPhone(phone) : Boolean(member.phone)) found.phone = t("staff.errors.phone");
    setErrors(found);
    if (Object.keys(found).length === 0) save.mutate();
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("staff.manage")}
      closeLabel={t("common.close")}
      footer={
        <>
          <Button variant="neutral" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={save.isPending} onClick={submit}>
            {t("common.saveChanges")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {member.email && (
          <div className="flex flex-col rounded-xl bg-page p-3">
            <span className="text-cap text-tx2">{t("staff.email")}</span>
            <b className="text-sm font-medium break-all">{member.email}</b>
          </div>
        )}
        <Field label={t("staff.name")} error={errors.full_name}>
          {(c) => <Input {...c} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field label={t("staff.phone")} error={errors.phone}>
          {(c) => <Input {...c} type="tel" inputMode="tel" placeholder="07XX XXX XXX" value={phone} onChange={(e) => setPhone(e.target.value)} />}
        </Field>
        <Field label={t("staff.columns.status")} help={active !== member.is_active && !active ? t(self ? "staff.selfSignOut" : "staff.disableNote") : undefined}>
          {(c) => (
            <Select {...c} value={active ? "active" : "disabled"} onChange={(e) => setActive(e.target.value === "active")}>
              <option value="active">{t("staff.active")}</option>
              <option value="disabled">{t("staff.disabled")}</option>
            </Select>
          )}
        </Field>
        {errors.form && (
          <p role="alert" className="text-sm text-err-tx">
            {errors.form}
          </p>
        )}
      </div>
    </Dialog>
  );
}
