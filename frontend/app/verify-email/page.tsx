"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:11001";

export default function VerifyEmailPage() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  useEffect(() => {
    if (!token) return;
    window.location.href = `${API_BASE}/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`;
  }, [token]);

  if (!token) {
    return (
      <main className="min-h-[80vh] flex items-center justify-center px-4">
        <div className="text-center text-slate-400">
          <p>Неверная ссылка подтверждения.</p>
          <a href="/login" className="mt-4 inline-block text-teal-400 hover:underline">
            Перейти на страницу входа
          </a>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="text-center text-slate-400">
        <p>Подтверждение почты…</p>
        <p className="mt-2 text-sm">Вы будете перенаправлены на страницу входа.</p>
      </div>
    </main>
  );
}
