"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import type { TelegramAuthPayload } from "@/lib/api";

const TELEGRAM_BOT_USERNAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || "PingWinBot";

function LoginPageContent() {
  const { login, loginWithTelegram, saveToken } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const telegramRef = useRef<HTMLDivElement>(null);

  // Handle token from verify-email redirect or direct link
  useEffect(() => {
    const token = searchParams.get("token");
    const verified = searchParams.get("verified");
    const err = searchParams.get("error");
    if (err) {
      if (err === "invalid_token") setError("Ссылка подтверждения недействительна или истекла.");
      else if (err === "user_not_found") setError("Пользователь не найден.");
      else if (err === "blocked") setError("Аккаунт заблокирован. Обратитесь в поддержку.");
      else setError("Произошла ошибка.");
      return;
    }
    if (token) {
      saveToken(token);
      router.replace("/dashboard");
    }
  }, [searchParams, saveToken, router]);

  // Telegram Login Widget
  const handleTelegramAuth = useCallback(
    async (data: TelegramAuthPayload) => {
      setError("");
      setLoading(true);
      try {
        await loginWithTelegram(data);
        router.push("/dashboard");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Ошибка входа через Telegram");
      } finally {
        setLoading(false);
      }
    },
    [loginWithTelegram, router],
  );

  useEffect(() => {
    if (!telegramRef.current || typeof window === "undefined") return;
    const callbackName = "onTelegramAuthCallback";
    (window as unknown as Record<string, (d: TelegramAuthPayload) => void>)[callbackName] = handleTelegramAuth;
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.setAttribute("data-telegram-login", TELEGRAM_BOT_USERNAME);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-onauth", callbackName);
    script.setAttribute("data-request-access", "write");
    script.async = true;
    telegramRef.current.appendChild(script);
    return () => {
      delete (window as unknown as Record<string, unknown>)[callbackName];
      if (telegramRef.current && script.parentNode === telegramRef.current) {
        telegramRef.current.removeChild(script);
      }
    };
  }, [handleTelegramAuth]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900/80 p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-white mb-2">Вход</h1>
        <p className="text-slate-400 text-sm mb-6">Войдите в аккаунт для доступа к аналитике</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-slate-400 text-sm mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-2.5 text-white placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-slate-400 text-sm mb-1">Пароль</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-2.5 text-white placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
            />
          </div>
          {error && <p className="text-rose-400 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-teal-600 py-2.5 font-medium text-white hover:bg-teal-500 disabled:opacity-50"
          >
            {loading ? "Вход..." : "Войти по почте"}
          </button>
        </form>

        <div className="my-6 flex items-center gap-3">
          <span className="flex-1 h-px bg-slate-600" />
          <span className="text-slate-500 text-xs">или</span>
          <span className="flex-1 h-px bg-slate-600" />
        </div>

        <div className="flex flex-col items-center gap-2">
          <p className="text-slate-400 text-sm">Войти через Telegram</p>
          <div ref={telegramRef} />
        </div>

        <p className="mt-6 text-center text-slate-400 text-sm">
          Нет аккаунта?{" "}
          <Link href="/register" className="text-teal-400 hover:underline">
            Регистрация
          </Link>
        </p>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="min-h-[80vh] flex items-center justify-center px-4 text-slate-500">Загрузка...</main>}>
      <LoginPageContent />
    </Suspense>
  );
}
