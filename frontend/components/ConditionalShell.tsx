"use client";

import { usePathname } from "next/navigation";
import { AppShell } from "./AppShell";

export function ConditionalShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAdmin = pathname != null && pathname.startsWith("/admin");
  if (isAdmin) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
