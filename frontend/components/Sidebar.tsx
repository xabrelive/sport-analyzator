"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SPORTS } from "@/lib/sports";

const SPORT_LINKS = [
  { href: "/line", label: "Линия" },
  { href: "/live", label: "Лайв" },
  { href: "/signals", label: "Сигналы" },
  { href: "/stats", label: "Статистика" },
  { href: "/results", label: "Результаты" },
  { href: "/leagues", label: "Лиги" },
  { href: "/players", label: "Игроки" },
] as const;

function NavLink({
  href,
  label,
  isActive,
}: {
  href: string;
  label: string;
  isActive: boolean;
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      className={`block px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
        isActive
          ? "bg-teal-500/20 text-teal-400 border-l-2 border-teal-500"
          : "text-slate-400 hover:text-white hover:bg-slate-800/80"
      }`}
    >
      {label}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [expandedSlug, setExpandedSlug] = useState<string | null>("table-tennis");

  return (
    <aside className="w-56 shrink-0 border-r border-slate-700/80 bg-slate-900/40 flex flex-col min-h-[calc(100vh-3.5rem)]">
      <nav className="p-3 space-y-1">
        <NavLink
          href="/dashboard"
          label="Дашборд"
          isActive={pathname === "/dashboard"}
        />
        <NavLink
          href="/me"
          label="Кабинет"
          isActive={pathname === "/me"}
        />
        <div className="pt-4 space-y-0.5">
          {SPORTS.map((sport) => {
            const isExpanded = expandedSlug === sport.slug;
            const isSportPage = pathname === `/sports/${sport.slug}`;
            const hasSubLinks = sport.available;

            return (
              <div key={sport.slug} className="rounded-lg">
                <div className="flex items-center gap-1 min-w-0">
                  <button
                    type="button"
                    onClick={() => setExpandedSlug(isExpanded ? null : sport.slug)}
                    className="shrink-0 p-1.5 rounded text-slate-500 hover:text-slate-400 hover:bg-slate-800/80 transition-colors"
                    aria-expanded={hasSubLinks ? isExpanded : undefined}
                  >
                    <span
                      className="block transition-transform"
                      style={{ transform: isExpanded ? "rotate(0deg)" : "rotate(-90deg)" }}
                      aria-hidden
                    >
                      ▼
                    </span>
                  </button>
                  {sport.available ? (
                    <Link
                      href={`/sports/${sport.slug}`}
                      prefetch={false}
                      className={`flex-1 min-w-0 py-2 pr-2 rounded-lg text-xs font-semibold uppercase tracking-wider truncate transition-colors ${
                        isSportPage
                          ? "text-teal-400 bg-teal-500/10"
                          : "text-slate-500 hover:text-slate-400 hover:bg-slate-800/80"
                      }`}
                    >
                      {sport.name}
                    </Link>
                  ) : (
                    <span className="flex-1 min-w-0 py-2 pr-2 text-xs font-semibold text-slate-500 uppercase tracking-wider truncate">
                      {sport.name}
                    </span>
                  )}
                  {!sport.available && (
                    <span className="shrink-0 text-[10px] text-slate-500 font-normal normal-case">
                      Скоро
                    </span>
                  )}
                </div>
                {hasSubLinks && isExpanded && (
                  <div className="mt-0.5 pl-5 space-y-0.5">
                    {SPORT_LINKS.map(({ href, label }) => {
                      const isActive = pathname === href || pathname.startsWith(href + "/");
                      return (
                        <NavLink key={href} href={href} label={label} isActive={isActive} />
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>
    </aside>
  );
}
