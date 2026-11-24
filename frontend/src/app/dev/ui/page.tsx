import {
  Bell,
  Box,
  ChartColumn,
  ChartPie,
  CreditCard,
  Download,
  Headset,
  Heart,
  Lock,
  Package,
  Pencil,
  Phone,
  Search,
  Settings,
  ShieldCheck,
  ShoppingCart,
  Star,
  Tag,
  Trash2,
  Truck,
  Upload,
  User,
  Users,
} from "lucide-react";
import { Logo } from "@/components/store/logo";
import { MARKETPLACE_NAME } from "@/lib/marketplace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, Field, Input, PhoneInput, Radio, Select } from "@/components/ui/form";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, Td, Th } from "@/components/ui/table";
import { formatMoney } from "@/lib/format";
import { Interactive } from "./interactive";
import { ProductCards } from "./product-cards";
import { Suspense } from "react";
import { WhatsAppIcon } from "@/components/ui/whatsapp-icon";

/** /dev/ui: the components of StyleGuide.dc.html, built from the real React components. It shows
 * the style guide's own sample text; nothing here is product data. */

const COLOURS = [
  ["Brand Navy", "#0D2D52", "Announcement bar, footer, headings"],
  ["Deep Navy", "#071F42", "Admin sidebar, business band"],
  ["Primary Blue", "#0866F5", "Primary buttons, active nav, links, admin active item, sales chart"],
  ["Light Blue", "#EAF3FF", "Home hero, selected filter chips, info boxes"],
  ["White", "#FFFFFF", "Store header, product cards, admin KPI cards & tables"],
  ["Page Background", "#F5F8FC", "Admin content area, store section backgrounds"],
  ["Border", "#E2E8F0", "Filter panel, cards, inputs, table rows"],
  ["Text", "#0F172A", "Main text"],
  ["Text secondary", "#475569", "Descriptions, labels"],
  ["Muted", "#64748B", "Helper text, meta, placeholders"],
  ["Green", "#16A34A", "In stock, paid, delivered, success"],
  ["Amber", "#F59E0B", "Low stock, pending payment, warnings"],
  ["Red", "#DC2626", "Out of stock, failed payment, discounts, errors"],
  ["Purple", "#7C3AED", "Customers KPI, Ready status"],
  ["Star", "#F5A524", "Ratings only"],
  ["WhatsApp", "#25D366", "WhatsApp button only"],
] as const;

const ICONS = [
  Search, ShoppingCart, User, Heart, Truck, ShieldCheck, Headset, Phone, WhatsAppIcon, CreditCard,
  Package, Box, ChartColumn, ChartPie, Bell, Settings, Users, Tag, Upload, Download, Pencil, Trash2,
  Lock,
];

export default function StyleGuidePage() {
  return (
    <main id="main" className="mx-auto flex max-w-[1440px] flex-col gap-10 px-4 py-14 sm:px-16">
      <div className="flex flex-wrap items-center justify-between gap-6">
        <div className="flex flex-col gap-1.5">
          <span className="t-over text-pri-fg">Design system</span>
          <h1 className="t-display text-head">{MARKETPLACE_NAME} UI</h1>
          <p className="max-w-[640px] text-lg text-tx2">
            One set of tokens and components for the storefront and the admin panel. Font: Inter. Every screen on this
            canvas is built from these parts.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Card padding={16}>
            <Logo height={56} alt={`${MARKETPLACE_NAME} logo on light`} />
          </Card>
          <div className="rounded-xl bg-navy p-4">
            <div className="rounded-lg bg-card px-2.5 py-1.5">
              <Logo height={40} alt="Logo on dark, in a white plate" />
            </div>
          </div>
        </div>
      </div>

      <section className="flex flex-col gap-4">
        <h2 className="t-h2">Colours and where they go</h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {COLOURS.map(([name, hex, use]) => (
            <Card key={name} className="overflow-hidden">
              <div className="h-16 border-b border-bd" style={{ background: hex }} />
              <div className="flex flex-col gap-0.5 px-3.5 py-3">
                <b className="text-sm font-semibold">
                  {name} · {hex}
                </b>
                <span className="text-cap text-tx2">{use}</span>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <div className="flex flex-wrap items-start gap-10">
        <section className="flex flex-[1_1_520px] flex-col gap-3">
          <h2 className="t-h2">Type scale — Inter</h2>
          <Card padding={24} className="flex flex-col gap-3.5">
            <Row left={<span className="t-display">Display 44</span>} right="800 · hero" />
            <Row left={<span className="t-h1">Heading 1 · 32</span>} right="700 · page titles" />
            <Row left={<span className="t-h2">Heading 2 · 24</span>} right="700 · sections" />
            <Row left={<span className="t-h3">Heading 3 · 18</span>} right="600 · cards, panels" />
            <Row left={<span className="t-price">{formatMoney(520000)}</span>} right="Price · 18 / 700" />
            <Row left={<span>Body 14 — default text across the store and admin.</span>} right="400" />
            <div className="flex items-center justify-between gap-3">
              <span className="text-cap text-mut">Caption 12 — helper text, meta, table headers</span>
              <span className="t-over text-pri-fg">Overline</span>
            </div>
          </Card>
        </section>
        <section className="flex flex-[1_1_520px] flex-col gap-3">
          <h2 className="t-h2">Buttons</h2>
          <Card padding={24} className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2.5">
              <Button>
                <ShoppingCart size={18} aria-hidden="true" />
                Primary
              </Button>
              <Button variant="outline">Outline</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="ghost">Ghost</Button>
              <Button variant="dark">Dark</Button>
            </div>
            <div className="flex flex-wrap gap-2.5">
              <Button variant="danger">Danger</Button>
              <Button variant="danger-outline">Danger outline</Button>
              <Button variant="whatsapp">
                <WhatsAppIcon size={18} aria-hidden="true" />
                WhatsApp
              </Button>
              <Button variant="neutral">Neutral</Button>
              <Button disabled>Disabled</Button>
            </div>
            <div className="flex flex-wrap gap-2.5">
              <Button size="sm">Small 36</Button>
              <Button>Medium 44</Button>
              <Button size="lg">Large 52</Button>
            </div>
            <p className="text-cap text-mut">
              Radius 8 · one primary action per area · Outline for the second action on cards (Add to Cart beside View
              Details).
            </p>
          </Card>
        </section>
      </div>

      <div className="flex flex-wrap items-start gap-10">
        <section className="flex flex-[1_1_520px] flex-col gap-3">
          <h2 className="t-h2">Status badges</h2>
          <Card padding={24} className="flex flex-col gap-3.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="ok">In Stock</Badge>
              <Badge tone="warn">Low Stock</Badge>
              <Badge tone="err">Out of Stock</Badge>
              <Badge tone="err">10% OFF</Badge>
              <Badge tone="ok">New</Badge>
              <span className="text-cap text-mut">Solid — on product images</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="soft-ok">Delivered · Paid</Badge>
              <Badge tone="soft-warn">Pending payment</Badge>
              <Badge tone="soft-err">Failed · Cancelled</Badge>
              <Badge tone="soft-info">Processing</Badge>
              <Badge tone="soft-purple">Ready</Badge>
              <Badge tone="soft-neutral">Draft</Badge>
              <span className="text-cap text-mut">Soft — tables &amp; admin</span>
            </div>
          </Card>
          <h2 className="t-h2 pt-4">Form fields</h2>
          <Card padding={24} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Default" help="Helper text">
              {(p) => <Input {...p} placeholder="Placeholder" />}
            </Field>
            <Field label="Focus">{(p) => <Input {...p} defaultValue="Kimironko" className="border-pri shadow-focus" />}</Field>
            <Field label="Error" error="Enter a valid Rwandan phone number">
              {(p) => <Input {...p} defaultValue="0788" />}
            </Field>
            <Field label="Phone">{(p) => <PhoneInput {...p} placeholder="7XX XXX XXX" />}</Field>
            <Field label="Select">
              {(p) => (
                <Select {...p} defaultValue="gasabo">
                  <option value="gasabo">Kigali — Gasabo</option>
                </Select>
              )}
            </Field>
            <div className="flex flex-col gap-2.5 pt-6">
              <Checkbox label="Checkbox" defaultChecked />
              <Radio label="Radio" name="sg-radio" defaultChecked />
              <Interactive part="toggle" />
            </div>
          </Card>
        </section>
        <section className="flex flex-[1_1_520px] flex-col gap-3">
          <h2 className="t-h2">Product cards</h2>
          <Suspense fallback={<Skeleton className="h-[420px] rounded-xl" />}>
            <ProductCards />
          </Suspense>
          <h2 className="t-h2 pt-4">Icons &amp; spacing</h2>
          <Card padding={24} className="flex flex-col gap-3.5">
            <div className="flex flex-wrap gap-4 text-tx2">
              {ICONS.map((Icon, index) => (
                <Icon key={index} size={20} aria-hidden="true" />
              ))}
              <Star size={20} className="text-star" aria-hidden="true" />
            </div>
            <p className="text-cap text-mut">
              2px-stroke line icons (Lucide set) at 16 / 18 / 20 / 24. Spacing on a 4px grid: 4 · 8 · 12 · 16 · 20 · 24 ·
              32 · 56. Radius: 4 badges · 8 buttons &amp; inputs · 12 cards · 16 large media. Page content max width 1240px;
              mobile gutters 16px.
            </p>
          </Card>
        </section>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="t-h2">More components</h2>
        <p className="text-sm text-tx2">
          Not drawn in the style guide; taken from the screens that use them (named under each one).
        </p>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card padding={24} className="flex flex-col gap-4">
            <h3 className="t-h3">Breadcrumb · Category.dc.html</h3>
            <Breadcrumb
              label="Breadcrumb"
              items={[{ label: "Home", href: "/dev/ui" }, { label: "Phones", href: "/dev/ui" }, { label: "Galaxy A55 5G" }]}
            />
            <h3 className="t-h3">Pagination · Category.dc.html</h3>
            <Pagination
              total={45}
              page={2}
              size={9}
              hrefFor={(n) => `/dev/ui?page=${n}`}
              labels={{ nav: "Pagination", previous: "Previous", next: "Next", page: (n) => `Page ${n}` }}
            />
          </Card>
          <Card padding={24} className="flex flex-col gap-4">
            <h3 className="t-h3">Table · Orders.dc.html</h3>
            <Card className="overflow-hidden">
              <Table>
                <thead>
                  <tr>
                    <Th>Order</Th>
                    <Th>Status</Th>
                    <Th className="text-right">Total</Th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <Td className="font-semibold">Sample row</Td>
                    <Td>
                      <Badge tone="soft-ok">Delivered · Paid</Badge>
                    </Td>
                    <Td className="text-right">{formatMoney(520000)}</Td>
                  </tr>
                  <tr>
                    <Td className="font-semibold">Sample row</Td>
                    <Td>
                      <Badge tone="soft-warn">Pending payment</Badge>
                    </Td>
                    <Td className="text-right">{formatMoney(45000)}</Td>
                  </tr>
                </tbody>
              </Table>
            </Card>
          </Card>
          <Card padding={24} className="flex flex-col gap-4">
            <h3 className="t-h3">Skeleton and image placeholder</h3>
            <div className="flex items-start gap-4">
              <Interactive part="placeholder" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-7 w-1/3" />
              </div>
            </div>
          </Card>
          <Card padding={24} className="flex flex-col gap-4">
            <h3 className="t-h3">Tabs · Product.dc.html; Dialog · Inventory.dc.html; Drawer · MiniCart.dc.html; Toast</h3>
            <Interactive part="overlays" />
          </Card>
        </div>
      </section>
    </main>
  );
}

function Row({ left, right }: { left: React.ReactNode; right: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      {left}
      <span className="text-cap text-mut">{right}</span>
    </div>
  );
}
