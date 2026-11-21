import { Cctv, Cpu, Fence, Fingerprint, GraduationCap, Network, Shield, Wrench, type LucideIcon } from "lucide-react";
import type { components } from "@/lib/api/schema";

/** The icons staff choose for a service (ADR-013: a fixed list of keys, checked by the backend). */
export type ServiceIconKey = components["schemas"]["PublicServiceWithItems"]["icon"];

export const SERVICE_ICONS: Record<ServiceIconKey, LucideIcon> = {
  cctv: Cctv,
  gate: Fence,
  fingerprint: Fingerprint,
  network: Network,
  wrench: Wrench,
  "graduation-cap": GraduationCap,
  shield: Shield,
  cpu: Cpu,
};

export const SERVICE_ICON_KEYS = Object.keys(SERVICE_ICONS) as ServiceIconKey[];

export function ServiceIcon({ icon, size = 20, className }: { icon: ServiceIconKey; size?: number; className?: string }) {
  const Icon = SERVICE_ICONS[icon] ?? Wrench;
  return <Icon size={size} aria-hidden="true" className={className} />;
}
