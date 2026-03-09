"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";

function VerifyEmailContent() {
  const { verifyEmail } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailParam = searchParams.get("email") ?? "";
  const [email, setEmail] = useState(emailParam);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await verifyEmail(email, code);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ошибка подтверждения");
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
            Подтверждение почты
          </h1>
          <p className="text-slate-400 text-sm mb-6">
            Введите код из письма (действует ограниченное время)
          </p>
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
              <label className="block text-slate-400 text-sm mb-1">Код</label>
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
            {error && <p className="text-rose-400 text-sm">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-cyan-600 py-2.5 font-medium text-white transition hover:bg-cyan-500 disabled:opacity-50"
            >
              {loading ? "Проверка…" : "Подтвердить"}
            </button>
          </form>
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

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-[80vh] flex items-center justify-center text-slate-500">
          Загрузка…
        </main>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}
