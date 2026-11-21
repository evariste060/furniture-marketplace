"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, Drawer } from "@/components/ui/dialog";
import { Field, Input, RadioOption, Select } from "@/components/ui/form";
import { ProductImage } from "@/components/ui/product-image";
import { Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";

/** The interactive parts of /dev/ui. */
export function Interactive({ part }: { part: "toggle" | "placeholder" | "overlays" }) {
  if (part === "toggle") return <ToggleDemo />;
  if (part === "placeholder") return <ProductImage image={null} sizes="80px" className="size-20" />;
  return <Overlays />;
}

function ToggleDemo() {
  const [on, setOn] = useState(true);
  return <Toggle checked={on} onChange={setOn} label="Toggle" />;
}

function Overlays() {
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const toast = useToast();
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        label="Product details"
        items={[
          { id: "specs", label: "Specifications", content: <p className="text-sm text-tx2">First panel.</p> },
          { id: "description", label: "Description", content: <p className="text-sm text-tx2">Second panel.</p> },
          { id: "delivery", label: "Delivery & Returns", content: <p className="text-sm text-tx2">Third panel.</p> },
        ]}
      />
      <div className="flex flex-wrap gap-2.5">
        <Button variant="neutral" onClick={() => setDialog(true)}>
          Open dialog
        </Button>
        <Button variant="neutral" onClick={() => setDrawer(true)}>
          Open drawer
        </Button>
        <Button variant="neutral" onClick={() => toast.show("Saved")}>
          Show toast
        </Button>
      </div>
      <Dialog
        open={dialog}
        onClose={() => setDialog(false)}
        title="Adjust stock"
        closeLabel="Close"
        footer={
          <>
            <Button variant="neutral" onClick={() => setDialog(false)}>
              Cancel
            </Button>
            <Button onClick={() => setDialog(false)}>Save adjustment</Button>
          </>
        }
      >
        <div role="radiogroup" aria-label="Adjustment type" className="grid grid-cols-2 gap-2.5">
          <RadioOption name="adjust" label={<span className="text-sm font-medium">Add stock</span>} defaultChecked className="px-3 py-2.5" />
          <RadioOption name="adjust" label={<span className="text-sm font-medium">Remove stock</span>} className="px-3 py-2.5" />
        </div>
        <Field label="Quantity">{(p) => <Input {...p} inputMode="numeric" defaultValue="20" />}</Field>
        <Field label="Reason">
          {(p) => (
            <Select {...p}>
              <option>New delivery from supplier</option>
              <option>Stock count correction</option>
            </Select>
          )}
        </Field>
      </Dialog>
      <Drawer
        open={drawer}
        onClose={() => setDrawer(false)}
        title="Added to your cart"
        closeLabel="Close"
        icon={<CheckCircle2 size={22} className="text-ok-tx" aria-hidden="true" />}
      >
        <div className="flex flex-col gap-2.5 px-6 py-5">
          <Button block onClick={() => setDrawer(false)}>
            View cart &amp; checkout
          </Button>
          <Button block variant="outline" onClick={() => setDrawer(false)}>
            Continue shopping
          </Button>
        </div>
      </Drawer>
    </div>
  );
}
