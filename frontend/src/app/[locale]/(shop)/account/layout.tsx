import { Suspense } from "react";
import { AccountShell } from "@/features/account/account-shell";

/** The account area: the side navigation and the customer-only gate around every page. */
export default function AccountLayout({ children }: LayoutProps<"/[locale]/account">) {
  return (
    <main id="main" className="bg-page">
      <Suspense fallback={null}>
        <AccountShell>{children}</AccountShell>
      </Suspense>
    </main>
  );
}
