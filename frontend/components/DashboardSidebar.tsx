"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { useAuth } from "@/contexts/AuthContext";
import { useState } from "react";

// Иконки одного цвета (currentColor) — лаконичные, без эмодзи
const Icons = {
  home: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
    </svg>
  ),
  line: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  ),
  live: (
    <svg className="h-5 w-5 shrink-0" fill="currentColor" viewBox="0 0 24 24" aria-hidden>
      <circle cx="12" cy="12" r="4" />
    </svg>
  ),
  stats: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
  ),
  trophy: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 14v3m4-3v3m4-3v3M3 21h18M3 10h18M5 21V8l5-4 4 4 5 4v13M5 10h14" />
    </svg>
  ),
  user: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
    </svg>
  ),
  check: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
    </svg>
  ),
  calculator: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
    </svg>
  ),
  settings: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  chevronDown: (
    <svg className="h-4 w-4 shrink-0 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  ),
  chevronRight: (
    <svg className="h-4 w-4 shrink-0 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
    </svg>
  ),
  back: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
    </svg>
  ),
  logout: (
    <svg className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  ),
};

export function DashboardSidebar() {
  const pathname = usePathname();
  const { logout } = useAuth();

  const [openTableTennis, setOpenTableTennis] = useState(true);
  const [openTennis, setOpenTennis] = useState(false);
  const [openHockey, setOpenHockey] = useState(false);

  const isActive = (href: string) => pathname === href;

  const navLinkClasses = (active: boolean) =>
    `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
      active
        ? "bg-slate-700/60 text-white"
        : "text-slate-400 hover:bg-slate-800/80 hover:text-white"
    }`;

  const subLinkClasses = (active: boolean) =>
    `ml-6 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
      active
        ? "bg-slate-700/50 text-white"
        : "text-slate-400 hover:bg-slate-800/60 hover:text-white"
    }`;

  const soonSubLinkClasses =
    "ml-6 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-500 cursor-not-allowed";

  const sectionButtonClasses = (open: boolean) =>
    `mt-4 flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm font-medium transition
     bg-slate-800/50 text-slate-300 hover:bg-slate-800 hover:text-white
     border border-slate-700/50 ${open ? "rounded-b-none border-b-0" : ""}`;

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-56 border-r border-slate-800 bg-slate-900/95 backdrop-blur-sm flex flex-col">
      <div className="p-4 border-b border-slate-800">
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
      <nav className="flex-1 overflow-y-auto p-3 space-y-0.5">
        <Link
          href="/dashboard"
          className={navLinkClasses(isActive("/dashboard"))}
        >
          {Icons.home}
          Дашборд
        </Link>

        {/* Настольный теннис */}
        <button
          type="button"
          onClick={() => setOpenTableTennis((v) => !v)}
          className={sectionButtonClasses(openTableTennis)}
          aria-expanded={openTableTennis}
        >
          <span>Настольный теннис</span>
          <span className={openTableTennis ? "rotate-0" : "-rotate-90"}>
            {Icons.chevronDown}
          </span>
        </button>
        {openTableTennis && (
          <div className="rounded-b-lg border border-t-0 border-slate-700/50 bg-slate-800/30 px-2 pb-2 pt-1">
            <Link
              href="/dashboard/table-tennis/line"
              className={subLinkClasses(isActive("/dashboard/table-tennis/line"))}
            >
              {Icons.line}
              Линия
            </Link>
            <Link
              href="/dashboard/table-tennis/live"
              className={subLinkClasses(isActive("/dashboard/table-tennis/live"))}
            >
              {Icons.live}
              Лайв
            </Link>
            <Link
              href="/dashboard/table-tennis/stats"
              className={subLinkClasses(isActive("/dashboard/table-tennis/stats"))}
            >
              {Icons.stats}
              Статистика
            </Link>
            <Link
              href="/dashboard/table-tennis/leagues"
              className={subLinkClasses(isActive("/dashboard/table-tennis/leagues"))}
            >
              {Icons.trophy}
              Лиги
            </Link>
            <Link
              href="/dashboard/table-tennis/players"
              className={subLinkClasses(isActive("/dashboard/table-tennis/players"))}
            >
              {Icons.user}
              Игроки
            </Link>
            <Link
              href="/dashboard/table-tennis/results"
              className={subLinkClasses(isActive("/dashboard/table-tennis/results"))}
            >
              {Icons.check}
              Результаты
            </Link>
          </div>
        )}

        {/* Теннис (скоро) */}
        <button
          type="button"
          onClick={() => setOpenTennis((v) => !v)}
          className={sectionButtonClasses(openTennis)}
          aria-expanded={openTennis}
        >
          <span className="text-slate-400">Теннис <span className="text-slate-500 font-normal">(скоро)</span></span>
          <span className={openTennis ? "rotate-0" : "-rotate-90"}>{Icons.chevronDown}</span>
        </button>
        {openTennis && (
          <div className="rounded-b-lg border border-t-0 border-slate-700/50 bg-slate-800/30 px-2 pb-2 pt-1">
            <div className={soonSubLinkClasses}>{Icons.line} Линия</div>
            <div className={soonSubLinkClasses}>{Icons.live} Лайв</div>
            <div className={soonSubLinkClasses}>{Icons.stats} Статистика</div>
            <div className={soonSubLinkClasses}>{Icons.trophy} Лиги</div>
            <div className={soonSubLinkClasses}>{Icons.user} Игроки</div>
            <div className={soonSubLinkClasses}>{Icons.check} Результаты</div>
          </div>
        )}

        {/* Хоккей (скоро) */}
        <button
          type="button"
          onClick={() => setOpenHockey((v) => !v)}
          className={sectionButtonClasses(openHockey)}
          aria-expanded={openHockey}
        >
          <span className="text-slate-400">Хоккей <span className="text-slate-500 font-normal">(скоро)</span></span>
          <span className={openHockey ? "rotate-0" : "-rotate-90"}>{Icons.chevronDown}</span>
        </button>
        {openHockey && (
          <div className="rounded-b-lg border border-t-0 border-slate-700/50 bg-slate-800/30 px-2 pb-2 pt-1">
            <div className={soonSubLinkClasses}>{Icons.line} Линия</div>
            <div className={soonSubLinkClasses}>{Icons.live} Лайв</div>
            <div className={soonSubLinkClasses}>{Icons.stats} Статистика</div>
            <div className={soonSubLinkClasses}>{Icons.trophy} Лиги</div>
            <div className={soonSubLinkClasses}>{Icons.user} Игроки</div>
            <div className={soonSubLinkClasses}>{Icons.check} Результаты</div>
          </div>
        )}

        <div className="mt-4" />
        <Link
          href="/dashboard/calculator"
          className={navLinkClasses(isActive("/dashboard/calculator"))}
        >
          {Icons.calculator}
          Калькулятор
        </Link>
        <Link
          href="/dashboard/settings"
          className={navLinkClasses(isActive("/dashboard/settings"))}
        >
          {Icons.settings}
          Настройки
        </Link>
      </nav>
      <div className="p-3 border-t border-slate-800">
        <Link
          href="/"
          className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-400 hover:bg-slate-800/80 hover:text-white transition"
        >
          {Icons.back}
          На сайт
        </Link>
        <button
          type="button"
          onClick={() => logout()}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-400 hover:bg-slate-800/80 hover:text-rose-400 transition"
        >
          {Icons.logout}
          Выйти
        </button>
      </div>
    </aside>
  );
}
