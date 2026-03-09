"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { Nav } from "./Nav";
import { Sidebar } from "./Sidebar";
import { ProtectedBlur } from "./ProtectedBlur";
import { DateTimeBar } from "./DateTimeBar";

function isProtectedPath(pathname: string): boolean {
  const prefixes = ["/dashboard", "/line", "/live", "/results", "/stats", "/leagues", "/sports", "/pricing", "/match", "/player", "/players", "/signals", "/me"];
  return prefixes.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, logout } = useAuth();
  const pathname = usePathname();
  const showSidebar = !isLoading && isAuthenticated && isProtectedPath(pathname ?? "");

  return (
    <>
      <DateTimeBar />
      <header className="sticky top-0 z-10 border-b border-slate-700/50 bg-slate-950/95 backdrop-blur-xl">
        <div className={`${showSidebar ? "max-w-full" : "max-w-6xl"} mx-auto px-4 flex items-center justify-between h-14`}>
          <Link href={isAuthenticated ? "/line" : "/"} prefetch={false} className="flex items-center gap-2 font-bold text-lg text-white tracking-tight hover:text-teal-400 transition-colors">
            <Image src="/pingwin-logo.png" alt="PingWin - AI-аналитика спорта" width={32} height={32} className="rounded-lg" style={{ height: "auto" }} />
            <span>PingWin</span>
          </Link>
          {!isLoading && (
            <div className="flex items-center gap-1">
              {isAuthenticated ? (
                <>
                  {pathname === "/" ? (
                    <nav className="flex items-center gap-1">
                      <Link href="/dashboard" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Дашборд</Link>
                      <Link href="/me" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Кабинет (профиль)</Link>
                      <button type="button" onClick={logout} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Выход</button>
                    </nav>
                  ) : showSidebar ? (
                    <nav className="flex items-center gap-1">
                      <Link href="/me" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Кабинет</Link>
                      <Link href="/sports" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Виды спорта</Link>
                      <Link href="/stats" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Статистика</Link>
                      <Link href="/pricing" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Тарифы</Link>
                    </nav>
                  ) : (
                    <Nav />
                  )}
                  {pathname !== "/" && (
                    <>
                      <span className="w-px h-5 bg-slate-600 mx-0.5 shrink-0" aria-hidden />
                      <Link href="/me" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Профиль</Link>
                      <button type="button" onClick={logout} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Выход</button>
                    </>
                  )}
                </>
              ) : (
                <>
                  <Link href="/" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Главная</Link>
                  <Link href="/rules" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Правила</Link>
                  <Link href="/about" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Как работает</Link>
                  <Link href="/disclaimer" prefetch={false} className="px-3 py-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 text-sm transition-colors">Оговорка</Link>
                  <Link href="/login" prefetch={false} className="px-4 py-2 rounded-xl text-slate-200 hover:bg-slate-800 text-sm font-medium transition-colors">Войти</Link>
                  <Link href="/register" prefetch={false} className="px-4 py-2 rounded-xl bg-teal-500 hover:bg-teal-400 text-white text-sm font-semibold transition-all hover:shadow-lg hover:shadow-teal-500/25 hover:-translate-y-0.5">
                    Регистрация
                  </Link>
                </>
              )}
            </div>
          )}
        </div>
      </header>
      {showSidebar ? (
        <div className="flex">
          <Sidebar />
          <main className="flex-1 min-w-0">
            <ProtectedBlur>{children}</ProtectedBlur>
          </main>
        </div>
      ) : (
        <ProtectedBlur>{children}</ProtectedBlur>
      )}
    </>
  );
}
