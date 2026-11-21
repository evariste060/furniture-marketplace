"use client";

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Inbox, Package, PackageCheck, PackageOpen, Truck, X, XCircle, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/dialog";
import { Select } from "@/components/ui/form";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { browserApi } from "@/lib/api/client";
import { cx } from "@/lib/cx";
import { formatDate, formatMoney, formatPhone } from "@/lib/format";
import { Avatar, ListHeading, RowActions, rowClass, StatusCards } from "./inbox";
import { OrderPanel, whatsappLink } from "./order-detail";
import { ORDER_STATUSES, OrderStatusBadge, PAYMENT_METHODS, PaymentStatusBadge, type OrderStatus, type PaymentMethod } from "./status";
import { timeAgo } from "./time";
import { ListFooter, LoadError, must, PageHeader, SearchBox, useListParams } from "./ui";

const PAGE_SIZE = 20;
const DAY = 24 * 60 * 60 * 1000;
const PERIODS = ["all", "7", "30", "90"] as const;

/** The status cards: an icon and its colours per status ("" is All), in the order an order moves. */
const STAGE: Record<OrderStatus | "", { Icon: LucideIcon; chip: string; ring: string }> = {
  "": { Icon: ClipboardList, chip: "bg-navy text-white", ring: "ring-navy" },
  received: { Icon: Inbox, chip: "bg-warn-bg text-warn-tx", ring: "ring-warn" },
  confirmed: { Icon: CheckCircle2, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
  processing: { Icon: Package, chip: "bg-light text-pri-h", ring: "ring-pri" },
  dispatched: { Icon: Truck, chip: "bg-pur-bg text-pur", ring: "ring-pur" },
  delivered: { Icon: PackageCheck, chip: "bg-ok-bg text-ok-tx", ring: "ring-ok" },
  cancelled: { Icon: XCircle, chip: "bg-err-bg text-err-tx", ring: "ring-err" },
};

function isStatus(value: string): value is OrderStatus {
  return (ORDER_STATUSES as string[]).includes(value);
}
function isMethod(value: string): value is PaymentMethod {
  return (PAYMENT_METHODS as string[]).includes(value);
}

/** Orders.dc.html (layout owner 2026-11-18, like Service requests). Filters live in the URL: status,
 * q, days, method, page. Status cards (toggle buttons) show each status's count under the other
 * filters; each row can call or WhatsApp the customer and opens the order in a drawer with its
 * details and actions. The full page /admin/orders/[id] stays, linked from the drawer. */
export function OrdersView() {
  const t = useTranslations("admin");
  const { get, page, set, hrefWith } = useListParams();
  const status = isStatus(get("status")) ? (get("status") as OrderStatus) : "";
  const method = isMethod(get("method")) ? (get("method") as PaymentMethod) : "";
  const days = (PERIODS as readonly string[]).includes(get("days")) ? get("days") : "all";
  const q = get("q");
  const [now] = useState(() => Math.floor(Date.now() / 60_000) * 60_000);
  const [openId, setOpenId] = useState<string | null>(null);
  const from = days === "all" ? undefined : new Date(now - Number(days) * DAY).toISOString();
  const shared = {
    from,
    q: q || undefined,
    payment_method: method || undefined,
  };

  const list = useQuery({
    queryKey: ["admin", "orders", { status, ...shared, page }],
    queryFn: () =>
      must(
        browserApi.GET("/api/v1/staff/orders", {
          params: {
            query: {
              ...shared,
              status: status || undefined,
              page,
              size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const stages = ["", ...ORDER_STATUSES] as const;
  const counts = useQueries({
    queries: stages.map((s) => ({
      queryKey: ["admin", "orders", "count", s, shared],
      queryFn: async () =>
        (
          await must(
            browserApi.GET("/api/v1/staff/orders", {
              params: { query: { ...shared, status: s || undefined, size: 1 } },
            }),
          )
        ).total,
    })),
  });
  const filtered = Boolean(q || method || days !== "all");
  const opened = list.data?.items.find((o) => o.id === openId);

  return (
    <>
      <PageHeader title={t("orders.title")} description={t("orders.description")} />

      {/* Each card filters the list by status. */}
      <StatusCards
        label={t("orders.tabsLabel")}
        className="grid-cols-2 sm:grid-cols-4 xl:grid-cols-7"
        value={status}
        onChange={(s) => set({ status: s })}
        cards={stages.map((s, i) => ({
          key: s,
          ...STAGE[s],
          label: s ? t(`status.order.${s}`) : t("orders.all"),
          hint: t(`orders.hints.${s || "all"}`),
          count: counts[i]!.data,
          pulse: s === "received" && (counts[i]!.data ?? 0) > 0,
        }))}
      />

      <section aria-label={t("orders.listLabel")} className="overflow-hidden rounded-xl border border-bd bg-white shadow-sh">
        <ListHeading Icon={STAGE[status].Icon} chip={STAGE[status].chip} title={status ? t(`status.order.${status}`) : t("orders.all")} total={list.data?.total}>
          {list.data && (
            <span aria-live="polite" className="sr-only">
              {t("orders.count", { count: list.data.total })}
            </span>
          )}
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => set({ q: null, method: null, days: null })} className="gap-1.5">
              <X size={14} aria-hidden="true" />
              {t("orders.clearFilters")}
            </Button>
          )}
        </ListHeading>
        <div className="flex flex-wrap items-end gap-3 border-b border-bd px-5 py-4 max-sm:px-4">
          <Filter label={t("orders.searchLabel")} className="flex-[1_1_260px] sm:max-w-[360px]">
            {() => <SearchBox label={t("orders.searchLabel")} placeholder={t("orders.searchPlaceholder")} value={q} onSearch={(value) => set({ q: value })} className="h-10 max-w-none flex-none" />}
          </Filter>
          <Filter label={t("orders.periodLabel")} className="sm:w-44">
            {(id) => (
              <Select id={id} value={days} onChange={(e) => set({ days: e.target.value === "all" ? null : e.target.value })} className="h-10 text-sm">
                {PERIODS.map((p) => (
                  <option key={p} value={p}>
                    {t(`orders.periods.${p}`)}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
          <Filter label={t("orders.methodLabel")} className="sm:w-52">
            {(id) => (
              <Select id={id} value={method} onChange={(e) => set({ method: e.target.value })} className="h-10 text-sm">
                <option value="">{t("orders.allMethods")}</option>
                {PAYMENT_METHODS.map((m) => (
                  <option key={m} value={m}>
                    {t(`status.method.${m}`)}
                  </option>
                ))}
              </Select>
            )}
          </Filter>
        </div>

        {list.isError ? (
          <LoadError onRetry={() => list.refetch()} className="m-5" />
        ) : list.data && list.data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
            <span aria-hidden="true" className="flex size-14 items-center justify-center rounded-full bg-light text-pri-h">
              <PackageOpen size={26} />
            </span>
            <p className="m-0 max-w-80 text-tx2">{t("orders.empty")}</p>
          </div>
        ) : (
          <Table aria-busy={list.isFetching}>
            <thead>
              <tr>
                <Th>{t("orders.columns.order")}</Th>
                <Th>{t("orders.columns.customer")}</Th>
                <Th>{t("orders.columns.date")}</Th>
                <Th className="text-right">{t("orders.columns.total")}</Th>
                <Th>{t("orders.columns.payment")}</Th>
                <Th>{t("orders.columns.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("common.actions")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {!list.data
                ? Array.from({ length: 6 }, (_, i) => (
                    <tr key={i}>
                      <Td colSpan={7}>
                        <Skeleton className="h-11 w-full" />
                      </Td>
                    </tr>
                  ))
                : list.data.items.map((order) => (
                    <tr key={order.id} className={rowClass(order.id === openId, order.status === "received")}>
                      <Td>
                        <span className="flex flex-col">
                          <button
                            type="button"
                            onClick={() => setOpenId(order.id)}
                            className="cursor-pointer border-0 bg-transparent p-0 text-left font-mono text-sm font-semibold whitespace-nowrap text-pri-h hover:underline"
                          >
                            {order.order_number}
                          </button>
                          <span className="text-cap text-tx2">{t("orders.items", { count: order.item_count })}</span>
                        </span>
                      </Td>
                      <Td>
                        <span className="flex items-center gap-2.5">
                          <Avatar name={order.customer_name} />
                          <span className="flex min-w-0 flex-col">
                            <b className="font-semibold">{order.customer_name}</b>
                            <span className="text-cap whitespace-nowrap text-tx2">{formatPhone(order.customer_phone)}</span>
                          </span>
                        </span>
                      </Td>
                      <Td className="whitespace-nowrap">
                        <span className="flex flex-col">
                          <span className="font-medium">{timeAgo(order.created_at, now)}</span>
                          <span className="text-cap text-tx2">{formatDate(order.created_at, "dateTime")}</span>
                        </span>
                      </Td>
                      <Td className="text-right whitespace-nowrap">
                        <span className="flex flex-col items-end">
                          <b className="font-semibold tabular-nums">{formatMoney(order.total)}</b>
                          {order.payment_method && <span className="text-cap text-tx2">{t(`status.method.${order.payment_method}`)}</span>}
                        </span>
                      </Td>
                      <Td>
                        {order.payment_method && order.payment_status ? (
                          <PaymentStatusBadge status={order.payment_status} method={order.payment_method} />
                        ) : (
                          <span className="text-tx2 italic">{t("orders.noPayment")}</span>
                        )}
                      </Td>
                      <Td>
                        <OrderStatusBadge status={order.status} />
                      </Td>
                      <Td className="pl-1">
                        <RowActions
                          whatsapp={whatsappLink(order.customer_phone)}
                          whatsappLabel={t("orders.whatsappName", { name: order.customer_name })}
                          openLabel={t("orders.open", { number: order.order_number })}
                          onOpen={() => setOpenId(order.id)}
                        />
                      </Td>
                    </tr>
                  ))}
            </tbody>
          </Table>
        )}
        {list.data && <ListFooter page={page} size={PAGE_SIZE} total={list.data.total} hrefFor={(n) => hrefWith({ page: n })} />}
      </section>

      <Drawer
        open={openId !== null}
        onClose={() => setOpenId(null)}
        title={opened ? t("order.title", { number: opened.order_number }) : t("orders.title")}
        closeLabel={t("common.close")}
        className="max-w-[min(560px,100%)]!"
      >
        {openId && <OrderPanel key={openId} orderId={openId} now={now} />}
      </Drawer>
    </>
  );
}

/** A labelled filter control. */
function Filter({ label, className, children }: { label: string; className?: string; children: (id: string) => ReactNode }) {
  const id = `orders-filter-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className={cx("flex min-w-0 flex-col gap-1 max-sm:flex-1", className)}>
      <label htmlFor={id} className="text-cap font-semibold text-tx2">
        {label}
      </label>
      {children(id)}
    </div>
  );
}
