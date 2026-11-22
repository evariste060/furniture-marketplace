import { SellerDashboardView } from "@/features/seller/dashboard";
import { SellerPage, sellerMetadata } from "@/features/seller/page";
import { getSellerVisitor } from "@/lib/seller";

export const generateMetadata = sellerMetadata("dashboard");

export default function SellerDashboardPage() {
  return (
    <SellerPage>
      <Dashboard />
    </SellerPage>
  );
}

async function Dashboard() {
  const visitor = await getSellerVisitor();
  return <SellerDashboardView name={visitor.kind === "seller" ? visitor.fullName.split(" ")[0] : ""} />;
}
