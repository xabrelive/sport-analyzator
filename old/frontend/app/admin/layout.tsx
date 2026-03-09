"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchMyProfile } from "@/lib/api";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [adminAllowed, setAdminAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    if (!isAuthenticated && !authLoading) {
      const returnUrl = "/admin" + (pathname === "/admin" ? "" : pathname?.slice(5) || "");
      router.replace(`/login?returnUrl=${encodeURIComponent(returnUrl)}`);
      return;
    }
    if (!isAuthenticated) return;
    let cancelled = false;
    fetchMyProfile()
      .then((p) => {
        if (!cancelled) setAdminAllowed(!!p.is_admin);
      })
      .catch(() => {
        if (!cancelled) setAdminAllowed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, authLoading, router, pathname]);

  useEffect(() => {
    if (adminAllowed === false) {
      router.replace("/");
    }
  }, [adminAllowed, router]);


  if (authLoading || adminAllowed === null) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <span className="text-slate-400">Загрузка…</span>
      </div>
    );
  }

  if (!adminAllowed) return null;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex">
      <aside className="w-56 border-r border-slate-700/50 bg-slate-900/50 flex flex-col">
        <div className="p-4 border-b border-slate-700/50">
          <Link href="/admin" className="font-semibold text-white hover:text-teal-400">
            Админка
          </Link>
        </div>
        <nav className="p-2 flex-1">
          <Link
            href="/admin/users"
            className={`block px-3 py-2 rounded-lg text-sm ${pathname?.startsWith("/admin/users") ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}
          >
            Пользователи
          </Link>
          <Link
            href="/admin/payment-methods"
            className={`block px-3 py-2 rounded-lg text-sm ${pathname?.startsWith("/admin/payment-methods") ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}
          >
            Способы оплаты
          </Link>
          <Link
            href="/admin/products"
            className={`block px-3 py-2 rounded-lg text-sm ${pathname?.startsWith("/admin/products") ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}
          >
            Услуги
          </Link>
          <Link
            href="/admin/scheduled-posts"
            className={`block px-3 py-2 rounded-lg text-sm ${pathname?.startsWith("/admin/scheduled-posts") ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}
          >
            Отложенные посты
          </Link>
        </nav>
        <div className="p-2 border-t border-slate-700/50 space-y-1">
          <Link href="/" className="block px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800">
            На сайт
          </Link>
          <button type="button" onClick={() => { logout(); router.replace("/login"); }} className="block w-full text-left px-3 py-2 rounded-lg text-sm text-slate-400 hover:text-white hover:bg-slate-800">
            Выйти
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}
