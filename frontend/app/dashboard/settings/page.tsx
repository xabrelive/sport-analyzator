"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  getMe,
  patchMe,
  requestLinkEmail,
  requestTelegramLinkCode,
  verifyLinkEmail,
  unlinkTelegram,
  unlinkNotificationEmail,
  type MeProfile,
  type MeSettingsUpdate,
} from "@/lib/api";

const TELEGRAM_BOT_LINK = process.env.NEXT_PUBLIC_TELEGRAM_BOT_LINK || "https://t.me/";

export default function DashboardSettingsPage() {
  const [profile, setProfile] = useState<MeProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Telegram link
  const [tgCode, setTgCode] = useState("");
  const [tgCodeLoading, setTgCodeLoading] = useState(false);
  const [tgUnlinkLoading, setTgUnlinkLoading] = useState(false);

  // Email link (for Telegram-only users)
  const [linkEmailStep, setLinkEmailStep] = useState<"email" | "code">("email");
  const [linkEmail, setLinkEmail] = useState("");
  const [linkCode, setLinkCode] = useState("");
  const [linkEmailLoading, setLinkEmailLoading] = useState(false);
  const [linkCodeLoading, setLinkCodeLoading] = useState(false);
  const [unlinkEmailLoading, setUnlinkEmailLoading] = useState(false);

  // Quiet hours
  const [quietStart, setQuietStart] = useState("");
  const [quietEnd, setQuietEnd] = useState("");
  const [quietLoading, setQuietLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((p) => {
        if (!cancelled) {
          setProfile(p);
          setQuietStart(p.quiet_hours_start ?? "");
          setQuietEnd(p.quiet_hours_end ?? "");
        }
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  async function handleRequestTelegramCode() {
    setError("");
    setSuccess("");
    setTgCodeLoading(true);
    try {
      const r = await requestTelegramLinkCode();
      setTgCode(r.code);
      setSuccess("Код получен. Введите его в боте в Telegram (меню «Привязать аккаунт»).");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setTgCodeLoading(false);
    }
  }

  async function handleUnlinkTelegram() {
    setError("");
    setTgUnlinkLoading(true);
    try {
      await unlinkTelegram();
      const p = await getMe();
      setProfile(p);
      setTgCode("");
      setSuccess("Telegram отвязан.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setTgUnlinkLoading(false);
    }
  }

  async function handleRequestLinkEmail(e: React.FormEvent) {
    e.preventDefault();
    if (!linkEmail.trim()) return;
    setError("");
    setLinkEmailLoading(true);
    try {
      await requestLinkEmail(linkEmail.trim());
      setLinkEmailStep("code");
      setSuccess("Код отправлен на почту. Введите его ниже.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLinkEmailLoading(false);
    }
  }

  async function handleVerifyLinkEmail(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLinkCodeLoading(true);
    try {
      await verifyLinkEmail(linkEmail.trim(), linkCode.trim());
      const p = await getMe();
      setProfile(p);
      setLinkEmailStep("email");
      setLinkEmail("");
      setLinkCode("");
      setSuccess("Почта привязана.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setLinkCodeLoading(false);
    }
  }

  async function handleUnlinkEmail() {
    setError("");
    setUnlinkEmailLoading(true);
    try {
      await unlinkNotificationEmail();
      const p = await getMe();
      setProfile(p);
      setSuccess("Почта для уведомлений отвязана.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setUnlinkEmailLoading(false);
    }
  }

  async function handleSaveQuietHours(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setQuietLoading(true);
    try {
      const data: MeSettingsUpdate = {};
      if (quietStart.trim()) data.quiet_hours_start = quietStart.trim();
      else data.quiet_hours_start = null;
      if (quietEnd.trim()) data.quiet_hours_end = quietEnd.trim();
      else data.quiet_hours_end = null;
      const p = await patchMe(data);
      setProfile(p);
      setQuietStart(p.quiet_hours_start ?? "");
      setQuietEnd(p.quiet_hours_end ?? "");
      setSuccess("Режим тишины сохранён.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      setQuietLoading(false);
    }
  }

  if (loading || !profile) {
    return (
      <div className="p-6 md:p-8">
        <p className="text-slate-400">Загрузка…</p>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8">
      <h1 className="font-display text-2xl font-bold text-white mb-2">Настройки</h1>
      <p className="text-slate-400 text-sm mb-6">
        Привязка Telegram и почты для уведомлений, режим тишины.
      </p>

      {error && (
        <div className="mb-4 p-3 rounded-lg bg-rose-500/10 text-rose-400 text-sm">{error}</div>
      )}
      {success && (
        <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 text-emerald-400 text-sm">
          {success}
        </div>
      )}

      <div className="space-y-8 max-w-xl">
        {/* Telegram */}
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-6">
          <h2 className="font-semibold text-white mb-2">Telegram</h2>
          <p className="text-slate-400 text-sm mb-4">
            Привяжите личный Telegram для уведомлений в личные сообщения (не в групповые чаты).
          </p>
          {profile.telegram_linked ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-emerald-400 text-sm">
                Привязан{profile.telegram_username ? ` @${profile.telegram_username}` : ""}
              </span>
              <button
                type="button"
                onClick={handleUnlinkTelegram}
                disabled={tgUnlinkLoading}
                className="text-sm text-rose-400 hover:underline disabled:opacity-50"
              >
                {tgUnlinkLoading ? "…" : "Отвязать"}
              </button>
            </div>
          ) : (
            <div>
              <button
                type="button"
                onClick={handleRequestTelegramCode}
                disabled={tgCodeLoading}
                className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
              >
                {tgCodeLoading ? "Получение кода…" : "Получить код для привязки"}
              </button>
              {tgCode && (
                <div className="mt-4 p-4 rounded-lg bg-slate-900/80">
                  <p className="text-slate-400 text-sm mb-2">Введите этот код в боте:</p>
                  <p className="font-mono text-lg text-white mb-2">{tgCode}</p>
                  <a
                    href={TELEGRAM_BOT_LINK}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-cyan-400 text-sm hover:underline"
                  >
                    Открыть бота в Telegram
                  </a>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Email (for Telegram-only or display) */}
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-6">
          <h2 className="font-semibold text-white mb-2">Почта для уведомлений</h2>
          {profile.is_telegram_only ? (
            <>
              {profile.notification_email ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-slate-300 text-sm">
                    {profile.notification_email_masked ?? profile.notification_email}
                  </span>
                  <button
                    type="button"
                    onClick={handleUnlinkEmail}
                    disabled={unlinkEmailLoading}
                    className="text-sm text-rose-400 hover:underline disabled:opacity-50"
                  >
                    {unlinkEmailLoading ? "…" : "Отвязать"}
                  </button>
                </div>
              ) : (
                <div>
                  {linkEmailStep === "email" ? (
                    <form onSubmit={handleRequestLinkEmail} className="space-y-3">
                      <input
                        type="email"
                        value={linkEmail}
                        onChange={(e) => setLinkEmail(e.target.value)}
                        placeholder="your@email.com"
                        className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                      />
                      <button
                        type="submit"
                        disabled={linkEmailLoading}
                        className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                      >
                        {linkEmailLoading ? "Отправка кода…" : "Отправить код на почту"}
                      </button>
                    </form>
                  ) : (
                    <form onSubmit={handleVerifyLinkEmail} className="space-y-3">
                      <p className="text-slate-400 text-sm">Код отправлен на {linkEmail}</p>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={linkCode}
                        onChange={(e) => setLinkCode(e.target.value.replace(/\D/g, "").slice(0, 10))}
                        placeholder="Код из письма"
                        className="w-full rounded-lg border border-slate-600 bg-slate-800/80 px-4 py-2.5 text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                      />
                      <div className="flex gap-2">
                        <button
                          type="submit"
                          disabled={linkCodeLoading}
                          className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                        >
                          {linkCodeLoading ? "…" : "Подтвердить"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setLinkEmailStep("email")}
                          className="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800"
                        >
                          Другой email
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="text-slate-400 text-sm">
              Уведомления приходят на почту аккаунта: {profile.email_masked}
            </p>
          )}
        </section>

        {/* Режим тишины */}
        <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-6">
          <h2 className="font-semibold text-white mb-2">Режим тишины</h2>
          <p className="text-slate-400 text-sm mb-4">
            В этот интервал уведомления не отправляются (например, с 22:00 до 08:00).
          </p>
          <form onSubmit={handleSaveQuietHours} className="flex flex-wrap items-end gap-4">
            <div>
              <label className="block text-slate-400 text-xs mb-1">С</label>
              <input
                type="time"
                value={quietStart}
                onChange={(e) => setQuietStart(e.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-800/80 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
            </div>
            <div>
              <label className="block text-slate-400 text-xs mb-1">До</label>
              <input
                type="time"
                value={quietEnd}
                onChange={(e) => setQuietEnd(e.target.value)}
                className="rounded-lg border border-slate-600 bg-slate-800/80 px-3 py-2 text-white focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500"
              />
            </div>
            <button
              type="submit"
              disabled={quietLoading}
              className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
            >
              {quietLoading ? "Сохранение…" : "Сохранить"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
