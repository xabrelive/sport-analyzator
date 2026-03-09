"use client";

import Link from "next/link";

const PROTECTED_PREFIXES = ["/dashboard", "/line", "/live", "/results", "/stats", "/leagues", "/sports", "/match", "/player", "/players", "/signals", "/me"];

export function BlurOverlay() {
  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-slate-950/90 backdrop-blur-xl">
      <div className="text-center px-4">
        <p className="text-white font-semibold text-lg mb-2">Доступ к аналитике после регистрации</p>
        <p className="text-slate-400 text-sm mb-6">Данные обновляются в реальном времени. Зарегистрируйтесь, чтобы видеть всё.</p>
        <div className="flex flex-wrap justify-center gap-3">
          <Link
            href="/register"
            className="rounded-xl bg-teal-500 px-6 py-3 font-semibold text-white hover:bg-teal-400 transition-all hover:shadow-lg hover:shadow-teal-500/25"
          >
            Регистрация
          </Link>
          <Link
            href="/login"
            className="rounded-xl border border-slate-600 px-6 py-3 font-medium text-slate-200 hover:bg-slate-800"
          >
            Войти
          </Link>
        </div>
      </div>
    </div>
  );
}

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"));
}
