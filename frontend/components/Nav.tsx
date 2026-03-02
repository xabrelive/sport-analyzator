"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const nav = [
  { href: "/dashboard", label: "Дашборд" },
  { href: "/sports", label: "Виды спорта" },
  { href: "/line", label: "Линия" },
  { href: "/live", label: "Лайв" },
  { href: "/results", label: "Результаты" },
  { href: "/stats", label: "Статистика" },
  { href: "/leagues", label: "Лиги" },
  { href: "/pricing", label: "Тарифы" },
] as const;

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1">
      {nav.map(({ href, label }) => {
        const isActive = pathname === href || (href !== "/" && pathname.startsWith(href + "/"));
        return (
          <Link
            key={href}
            href={href}
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
