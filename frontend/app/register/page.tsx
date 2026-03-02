"use client";

import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

const TELEGRAM_BOT_LINK =
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_LINK || "https://t.me/PingWinBot?start=register";

export default function RegisterPage() {
  const { register } = useAuth();
  const [mode, setMode] = useState<"email" | "telegram">("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [agreeRisks, setAgreeRisks] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSuccessMessage("");
    if (password !== confirm) {
      setError("Пароли не совпадают");
      return;
    }
    if (password.length < 6) {
      setError("Пароль не менее 6 символов");
      return;
    }
    if (!agreeTerms) {
      setError("Необходимо согласие с условиями использования и правилами предоставления аналитики");
      return;
    }
    if (!agreeRisks) {
      setError("Необходимо подтвердить, что все риски вы берёте на себя");
      return;
    }
    setLoading(true);
    try {
      const result = await register(email, password);
      setSuccessMessage(result.detail || "Проверьте почту и перейдите по ссылке для подтверждения.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-[80vh] flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900/80 p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-white mb-2">Регистрация</h1>
        <p className="text-slate-400 text-sm mb-6">Создайте аккаунт для доступа к аналитике</p>

        <div className="flex rounded-xl bg-slate-800/80 p-1 mb-6">
          <button
            type="button"
            onClick={() => setMode("email")}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === "email" ? "bg-teal-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            По почте
          </button>
          <button
            type="button"
            onClick={() => setMode("telegram")}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === "telegram" ? "bg-teal-600 text-white" : "text-slate-400 hover:text-white"
            }`}
          >
            Через Telegram
          </button>
        </div>

        {mode === "telegram" ? (
          <div className="space-y-4">
            <p className="text-slate-300 text-sm">
              Нажмите кнопку ниже — откроется бот в Telegram. Подтвердите регистрацию, укажите дату рождения и при
              желании почту. После этого вы сможете входить на сайт через «Войти через Telegram».
            </p>
            <a
              href={TELEGRAM_BOT_LINK}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full rounded-lg bg-[#0088cc] py-3 font-medium text-white hover:bg-[#0077b5] transition-colors"
            >
              <span>✈️</span>
              Открыть бота в Telegram
            </a>
            <p className="text-slate-500 text-xs text-center">
              Уже зарегистрировались через бота?{" "}
              <Link href="/login" className="text-teal-400 hover:underline">
                Войти
              </Link>
            </p>
          </div>
        ) : (
          <form onSubmit={handleEmailSubmit} className="space-y-4">
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
                minLength={6}
                className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-2.5 text-white placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 text-sm mb-1">Повторите пароль</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-2.5 text-white placeholder-slate-500 focus:border-teal-500 focus:outline-none focus:ring-1 focus:ring-teal-500"
              />
            </div>
            <div className="space-y-3">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreeTerms}
                  onChange={(e) => setAgreeTerms(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-teal-600 focus:ring-teal-500"
                />
                <span className="text-slate-300 text-sm">
                  Я согласен с{" "}
                  <Link href="/terms" target="_blank" className="text-teal-400 hover:underline">
                    условиями использования и правилами предоставления аналитики
                  </Link>
                  . Платные услуги — это доступ к аналитике, а не рекомендации или призыв к ставкам; все ставки на свой
                  страх и риск.
                </span>
              </label>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreeRisks}
                  onChange={(e) => setAgreeRisks(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-teal-600 focus:ring-teal-500"
                />
                <span className="text-slate-300 text-sm">
                  Все риски беру на себя. Понимаю, что сервис не даёт рекомендаций и призывов к ставкам; любые решения о
                  пари принимаю самостоятельно.
                </span>
              </label>
            </div>
            {successMessage && (
              <p className="text-teal-400 text-sm bg-teal-500/10 rounded-lg p-3">{successMessage}</p>
            )}
            {error && <p className="text-rose-400 text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-teal-600 py-2.5 font-medium text-white hover:bg-teal-500 disabled:opacity-50"
            >
              {loading ? "Регистрация..." : "Зарегистрироваться"}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-slate-400 text-sm">
          Уже есть аккаунт?{" "}
          <Link href="/login" className="text-teal-400 hover:underline">
            Войти
          </Link>
        </p>
      </div>
    </main>
  );
}
