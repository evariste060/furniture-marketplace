"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/** Whether the category menu drawer is open. It is opened from the mobile header and the mobile
 * tab bar, and drawn inside the category nav (desktop "All Categories" links to /products). */
type MenuState = { open: boolean; setOpen: (open: boolean) => void };
const MenuContext = createContext<MenuState | null>(null);

export function MenuStateProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo(() => ({ open, setOpen }), [open]);
  return <MenuContext value={value}>{children}</MenuContext>;
}

export function useMenuState(): MenuState {
  const state = useContext(MenuContext);
  if (!state) throw new Error("useMenuState must be used inside <MenuStateProvider>");
  return state;
}
