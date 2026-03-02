"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { BlurOverlay, isProtectedPath } from "./BlurOverlay";

export function ProtectedBlur({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();
  const showBlur = !isLoading && !isAuthenticated && pathname != null && isProtectedPath(pathname);

  return (
    <>
      {children}
      {showBlur && <BlurOverlay />}
    </>
  );
}
