"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { DashboardSidebar } from "@/components/DashboardSidebar";
import { DashboardBanner } from "@/components/DashboardBanner";
import { useEffect, useState } from "react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

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
    <div className="dashboard-theme min-h-screen bg-[var(--bg)] flex">
      <DashboardSidebar className="hidden md:flex" />

      {mobileSidebarOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
          aria-label="Закрыть меню"
        />
      )}
      <DashboardSidebar
        mobile
        className={`md:hidden ${mobileSidebarOpen ? "translate-x-0" : "-translate-x-full"}`}
        onNavigate={() => setMobileSidebarOpen(false)}
      />

      <main className="flex-1 min-h-screen flex flex-col md:pl-56">
        <header className="md:hidden sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur px-4 py-3">
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(true)}
              className="inline-flex items-center justify-center rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-slate-200"
              aria-label="Открыть меню"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <span className="font-display font-semibold text-white">PingWin</span>
            <div className="w-10" />
          </div>
        </header>
        <DashboardBanner />
        {children}
      </main>
    </div>
  );
}
