"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { useAuth } from "@/contexts/AuthContext";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Главная", icon: "🏠" },
  { href: "/dashboard/profile", label: "Профиль", icon: "👤" },
  { href: "/dashboard/settings", label: "Настройки", icon: "⚙️" },
];

export function DashboardSidebar() {
  const pathname = usePathname();
  const { logout } = useAuth();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-56 border-r border-slate-800/80 bg-slate-900/95 backdrop-blur-sm flex flex-col">
      <div className="p-4 border-b border-slate-800/80">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Image
            src="/pingwin-logo.png"
            alt="PingWin"
            width={32}
            height={32}
            className="rounded-lg"
          />
          <span className="font-display font-semibold text-white">PingWin</span>
        </Link>
      </div>
      <nav className="flex-1 p-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                isActive
                  ? "bg-cyan-500/20 text-cyan-400"
                  : "text-slate-400 hover:bg-slate-800/80 hover:text-white"
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="p-3 border-t border-slate-800/80">
        <Link
          href="/"
          className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-400 hover:bg-slate-800/80 hover:text-white transition"
        >
          <span>↩</span>
          На сайт
        </Link>
        <button
          type="button"
          onClick={() => logout()}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-400 hover:bg-slate-800/80 hover:text-rose-400 transition"
        >
          <span>🚪</span>
          Выйти
        </button>
      </div>
    </aside>
  );
}
