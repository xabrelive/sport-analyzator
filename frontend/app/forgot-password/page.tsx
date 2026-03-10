"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import { requestPasswordReset, resetPassword } from "@/lib/api";

function ForgotPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailParam = searchParams.get("email") ?? "";
  const [step, setStep] = useState<"email" | "code">(emailParam ? "code" : "email");
  const [email, setEmail] = useState(emailParam);
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState("");

  async function handleRequestCode(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await requestPasswordReset(email.trim());
      setSuccessMessage("Код отправлен на почту. Введите его ниже и задайте новый пароль.");
      setStep("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось отправить код");
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("Пароли не совпадают");
      return;
    }
    if (newPassword.length < 6) {
      setError("Пароль не менее 6 символов");
      return;
    }
    setLoading(true);
    try {
      await resetPassword(email.trim(), code, newPassword);
      router.push("/login?message=password_reset");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка сброса пароля");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <Header />
      <main className="min-h-[80vh] flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md rounded-2xl border border-slate-700/80 bg-slate-900/60 p-8 shadow-xl backdrop-blur-sm">
          <h1 className="font-display text-2xl font-bold text-white mb-1">
            Восстановление пароля
          </h1>
          <p className="text-slate-400 text-sm mb-6">
            {step === "email"
              ? "Введите email — мы отправим код для сброса пароля (действует 2 часа)."
              : "Введите код из письма и новый пароль."}
          </p>

          {step === "email" ? (
            <form onSubmit={handleRequestCode} className="space-y-4">
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
              {error && <p className="text-rose-400 text-sm">{error}</p>}
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-cyan-600 py-2.5 font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
              >
                {loading ? "Отправка…" : "Отправить код"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleResetPassword} className="space-y-4">
              {successMessage && (
                <p className="text-emerald-400 text-sm bg-emerald-500/10 rounded-lg p-3">
                  {successMessage}
                </p>
              )}
              <div>
                <label className="block text-slate-400 text-sm mb-1">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 text-sm mb-1">Код из письма</label>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 10))}
                  required
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                  placeholder="123456"
                />
              </div>
              <div>
                <label className="block text-slate-400 text-sm mb-1">Новый пароль</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                />
              </div>
              <div>
                <label className="block text-slate-400 text-sm mb-1">Повторите пароль</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                />
              </div>
              {error && <p className="text-rose-400 text-sm">{error}</p>}
              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-lg bg-cyan-600 py-2.5 font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
              >
                {loading ? "Сохранение…" : "Сохранить пароль"}
              </button>
              <button
                type="button"
                onClick={() => setStep("email")}
                className="w-full rounded-lg border border-slate-600 py-2.5 font-medium text-slate-300 hover:bg-slate-800"
              >
                Указать другой email
              </button>
            </form>
          )}

          <p className="mt-6 text-center text-slate-400 text-sm">
            <Link href="/login" className="text-cyan-400 hover:underline">
              Войти
            </Link>
            {" · "}
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

export default function ForgotPasswordPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-[80vh] flex items-center justify-center text-slate-500">
          Загрузка…
        </main>
      }
    >
      <ForgotPasswordContent />
    </Suspense>
  );
}
