"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/dashboard", label: "Дашборд" },
  { href: "/me", label: "Кабинет" },
  { href: "/sports", label: "Виды спорта" },
  { href: "/line", label: "Линия" },
  { href: "/live", label: "Лайв" },
  { href: "/signals", label: "Сигналы" },
  { href: "/stats", label: "Статистика" },
  { href: "/results", label: "Результаты" },
  { href: "/leagues", label: "Лиги" },
  { href: "/players", label: "Игроки" },
  { href: "/pricing", label: "Тарифы" },
] as const;

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-wrap items-center gap-1">
      {navItems.map(({ href, label }) => {
        const isActive = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            prefetch={false}
            className={`px-4 py-2 rounded-xl font-medium text-sm transition-all ${
              isActive
                ? "text-white bg-teal-500 hover:bg-teal-400"
                : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
