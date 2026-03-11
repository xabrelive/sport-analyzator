"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

const TELEGRAM_BOT_LINK =
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_LINK || "https://t.me/";

function LoginContent() {
  const { login, loginByTelegramCode, saveToken } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [telegramCode, setTelegramCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [telegramCodeLoading, setTelegramCodeLoading] = useState(false);

  useEffect(() => {
    const token = searchParams.get("token");
    const err = searchParams.get("error");
    if (err) {
      if (err === "invalid_token") setError("Ссылка подтверждения недействительна или истекла.");
      else if (err === "user_not_found") setError("Пользователь не найден.");
      else setError("Произошла ошибка.");
      return;
    }
    if (token) {
      saveToken(token);
      router.replace("/dashboard");
    }
  }, [searchParams, saveToken, router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err: unknown) {
      const e = err as Error & { code?: string; email?: string };
      if (e?.code === "email_not_verified" && e?.email) {
        router.push(`/verify-email?email=${encodeURIComponent(e.email)}`);
        return;
      }
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  async function handleTelegramCodeSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setTelegramCodeLoading(true);
    try {
      await loginByTelegramCode(telegramCode.trim());
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа по коду");
    } finally {
      setTelegramCodeLoading(false);
    }
  }

  return (
    <>
      <Header />
      <main className="min-h-[80vh] flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900/60 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="font-display text-2xl font-bold text-white mb-1">Вход</h1>
          <p className="text-slate-400 text-sm mb-6">Войдите для доступа к аналитике</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-slate-400 text-sm mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                placeholder="you@example.com"
              />
            </div>
            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="block text-slate-400 text-sm">Пароль</label>
                <Link
                  href="/forgot-password"
                  className="text-cyan-400 text-sm hover:underline"
                >
                  Забыли пароль?
                </Link>
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
            </div>
            {searchParams.get("message") === "password_reset" && (
              <p className="text-emerald-400 text-sm">Пароль изменён. Войдите с новым паролем.</p>
            )}
            {error && <p className="text-rose-400 text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-cyan-600 py-2.5 font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
            >
              {loading ? "Вход…" : "Войти по почте"}
            </button>
          </form>

          <div className="my-6 flex items-center gap-3">
            <span className="flex-1 h-px bg-slate-600" />
            <span className="text-slate-500 text-xs">или</span>
            <span className="flex-1 h-px bg-slate-600" />
          </div>

          <p className="text-slate-400 text-sm mb-2">Войти по коду из Telegram-бота</p>
          <p className="text-slate-500 text-xs mb-3">
            Получите код в боте и введите его ниже (код действует 10 мин).
          </p>
          <form onSubmit={handleTelegramCodeSubmit} className="space-y-2 mb-4">
            <div className="flex gap-2">
              <input
                type="text"
                inputMode="numeric"
                value={telegramCode}
                onChange={(e) => setTelegramCode(e.target.value.replace(/\D/g, "").slice(0, 10))}
                placeholder="Код из бота"
                className="flex-1 rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
              <button
                type="submit"
                disabled={telegramCodeLoading || !telegramCode.trim()}
                className="rounded-lg bg-cyan-600 px-4 py-2.5 font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
              >
                {telegramCodeLoading ? "Вход…" : "Войти"}
              </button>
            </div>
            <a
              href={TELEGRAM_BOT_LINK}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-cyan-400 text-sm hover:underline"
            >
              Открыть бота в Telegram
            </a>
          </form>

          <p className="mt-6 text-center text-slate-400 text-sm">
            Нет аккаунта?{" "}
            <Link href="/register" className="text-cyan-400 hover:underline">
              Регистрация
            </Link>
          </p>
        </div>
      </main>
      <Footer />
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-[80vh] flex items-center justify-center px-4 text-slate-500">
          Загрузка…
        </main>
      }
    >
      <LoginContent />
    </Suspense>
  );
}
