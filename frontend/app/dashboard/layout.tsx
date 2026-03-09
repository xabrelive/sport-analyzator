"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { useEffect } from "react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] text-slate-500">
        Загрузка…
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[var(--bg)] px-4">
        <p className="text-slate-400">Войдите, чтобы открыть кабинет.</p>
        <Link
          href="/login"
          className="rounded-lg bg-cyan-500 px-4 py-2 font-medium text-white hover:bg-cyan-400"
        >
          Войти
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--bg)] flex">
      <DashboardSidebar />
      <main className="flex-1 pl-56 min-h-screen">
        {children}
      </main>
    </div>
  );
}
