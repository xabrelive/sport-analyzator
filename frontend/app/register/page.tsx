"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

const TELEGRAM_BOT_LINK =
  process.env.NEXT_PUBLIC_TELEGRAM_BOT_LINK || "https://t.me/";

function TelegramCodeForm({
  onSuccess,
  acceptTerms,
  acceptPrivacy,
}: {
  onSuccess: () => void;
  acceptTerms: boolean;
  acceptPrivacy: boolean;
}) {
  const { verifyTelegramCode } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyTelegramCode(code, acceptTerms, acceptPrivacy);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка");
    } finally {
      setLoading(false);
    }
  }
  const canSubmit = acceptTerms && acceptPrivacy && code.trim();
  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <input
        type="text"
        inputMode="numeric"
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 10))}
        placeholder="Код из бота"
        className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
      />
      {error && <p className="text-rose-400 text-sm">{error}</p>}
      <button
        type="submit"
        disabled={loading || !canSubmit}
        className="w-full rounded-lg bg-cyan-600 py-2.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
      >
        {loading ? "Вход…" : "Войти по коду"}
      </button>
    </form>
  );
}

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const [mode, setMode] = useState<"email" | "telegram">("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [agreePrivacy, setAgreePrivacy] = useState(false);
  const [agreeTermsTelegram, setAgreeTermsTelegram] = useState(false);
  const [agreePrivacyTelegram, setAgreePrivacyTelegram] = useState(false);
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
    if (!agreeTerms || !agreePrivacy) {
      setError("Необходимо принять условия использования и политику конфиденциальности");
      return;
    }
    setLoading(true);
    try {
      const result = await register(email, password, agreeTerms, agreePrivacy);
      if (!result.ok) {
        if (result.email_verified) {
          router.push(`/forgot-password?email=${encodeURIComponent(email)}`);
          return;
        }
        router.push(`/verify-email?email=${encodeURIComponent(email)}`);
        return;
      }
      setSuccessMessage(
        result.detail || "На почту отправлен код. Введите его на следующей странице."
      );
      window.location.href = `/verify-email?email=${encodeURIComponent(email)}`;
      return;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Header />
      <main className="min-h-[80vh] flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900/60 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="font-display text-2xl font-bold text-white mb-1">Регистрация</h1>
          <p className="text-slate-400 text-sm mb-6">Создайте аккаунт для доступа к аналитике</p>

          <div className="flex rounded-xl bg-slate-800/80 p-1 mb-6">
            <button
              type="button"
              onClick={() => setMode("email")}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
                mode === "email"
                  ? "bg-cyan-600 text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              По почте
            </button>
            <button
              type="button"
              onClick={() => setMode("telegram")}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${
                mode === "telegram"
                  ? "bg-cyan-600 text-white"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              Через Telegram
            </button>
          </div>

          {mode === "telegram" ? (
            <div className="space-y-4">
              <p className="text-slate-300 text-sm">
                Откройте бота в Telegram, получите код и введите его ниже. После этого аккаунт будет создан и вы войдёте на сайт.
              </p>
              <a
                href={TELEGRAM_BOT_LINK}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 w-full rounded-lg bg-[#0088cc] py-3 font-medium text-white transition hover:bg-[#0077b5]"
              >
                <span>✈️</span>
                Открыть бота в Telegram
              </a>
              <p className="text-slate-500 text-xs">Для регистрации необходимо принять:</p>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreeTermsTelegram}
                  onChange={(e) => setAgreeTermsTelegram(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                />
                <span className="text-slate-300 text-sm">
                  Я принимаю{" "}
                  <Link href="/terms" target="_blank" className="text-cyan-400 hover:underline">
                    условия использования
                  </Link>
                </span>
              </label>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreePrivacyTelegram}
                  onChange={(e) => setAgreePrivacyTelegram(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                />
                <span className="text-slate-300 text-sm">
                  Я принимаю{" "}
                  <Link href="/privacy" target="_blank" className="text-cyan-400 hover:underline">
                    политику конфиденциальности
                  </Link>
                </span>
              </label>
              <TelegramCodeForm
                onSuccess={() => router.push("/dashboard")}
                acceptTerms={agreeTermsTelegram}
                acceptPrivacy={agreePrivacyTelegram}
              />
              <p className="text-slate-500 text-xs text-center">
                Уже зарегистрировались через бота?{" "}
                <Link href="/login" className="text-cyan-400 hover:underline">
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
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
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
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 text-sm mb-1">Повторите пароль</label>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                />
              </div>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreeTerms}
                  onChange={(e) => setAgreeTerms(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                />
                <span className="text-slate-300 text-sm">
                  Я принимаю{" "}
                  <Link href="/terms" target="_blank" className="text-cyan-400 hover:underline">
                    условия использования
                  </Link>
                  . Аналитика носит информационный характер; любые ставки — на свой страх и риск.
                </span>
              </label>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={agreePrivacy}
                  onChange={(e) => setAgreePrivacy(e.target.checked)}
                  className="mt-1 rounded border-slate-600 bg-slate-800 text-cyan-600 focus:ring-cyan-500"
                />
                <span className="text-slate-300 text-sm">
                  Я принимаю{" "}
                  <Link href="/privacy" target="_blank" className="text-cyan-400 hover:underline">
                    политику конфиденциальности
                  </Link>
                </span>
              </label>
              {successMessage && (
                <p className="text-cyan-400 text-sm bg-cyan-500/10 rounded-lg p-3">
                  {successMessage}
                </p>
              )}
              {error && <p className="text-rose-400 text-sm">{error}</p>}
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-cyan-600 py-2.5 font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
              >
                {loading ? "Регистрация…" : "Зарегистрироваться"}
              </button>
            </form>
          )}

          <p className="mt-6 text-center text-slate-400 text-sm">
            Уже есть аккаунт?{" "}
            <Link href="/login" className="text-cyan-400 hover:underline">
              Войти
            </Link>
          </p>
        </div>
      </main>
      <Footer />
    </>
  );
}
