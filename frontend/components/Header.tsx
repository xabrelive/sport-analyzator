"use client";

import Link from "next/link";
import Image from "next/image";
import { useAuth } from "@/contexts/AuthContext";

export function Header() {
  const { isAuthenticated, isLoading, logout } = useAuth();

  return (
    <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-[var(--bg)]/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        <Link
          href="/"
          className="flex items-center gap-2.5 font-display text-lg font-semibold text-white transition hover:opacity-90"
        >
          <Image
            src="/pingwin-logo.png"
            alt="PingWin"
            width={36}
            height={36}
            className="rounded-lg"
          />
          <span>PingWin</span>
        </Link>
        <nav className="hidden items-center gap-6 sm:flex">
          <Link
            href="/"
            className="text-sm text-slate-400 transition hover:text-white"
          >
            Главная
          </Link>
          <Link
            href="/about"
            className="text-sm text-slate-400 transition hover:text-white"
          >
            О проекте
          </Link>
          <Link
            href="/advantages"
            className="text-sm text-slate-400 transition hover:text-white"
          >
            Преимущества
          </Link>
          {!isLoading && (
            <>
              {isAuthenticated ? (
                <>
                  <Link
                    href="/dashboard"
                    className="text-sm text-slate-300 transition hover:text-white"
                  >
                    Кабинет
                  </Link>
                  <button
                    type="button"
                    onClick={logout}
                    className="text-sm text-slate-400 transition hover:text-rose-400"
                  >
                    Выйти
                  </button>
                </>
              ) : (
                <>
                  <Link
                    href="/login"
                    className="text-sm text-slate-300 transition hover:text-white"
                  >
                    Войти
                  </Link>
                  <Link
                    href="/register"
                    className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-cyan-400 hover:shadow-lg hover:shadow-cyan-500/25"
                  >
                    Регистрация
                  </Link>
                </>
              )}
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
