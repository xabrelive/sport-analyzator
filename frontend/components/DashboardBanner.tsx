"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getMe, type MeProfile } from "@/lib/api";

const STORAGE_KEY_TELEGRAM = "banner_dismissed_telegram";
const STORAGE_KEY_EMAIL = "banner_dismissed_email";

export function DashboardBanner() {
  const [profile, setProfile] = useState<MeProfile | null>(null);
  const [dismissedTelegram, setDismissedTelegram] = useState(false);
  const [dismissedEmail, setDismissedEmail] = useState(false);

  useEffect(() => {
    getMe()
      .then((p) => setProfile(p))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissedTelegram(!!sessionStorage.getItem(STORAGE_KEY_TELEGRAM));
    setDismissedEmail(!!sessionStorage.getItem(STORAGE_KEY_EMAIL));
  }, []);

  const showTelegramBanner =
    profile &&
    !profile.is_telegram_only &&
    !profile.telegram_linked &&
    !dismissedTelegram;
  const showEmailBanner =
    profile &&
    profile.is_telegram_only &&
    !profile.notification_email &&
    !dismissedEmail;

  const dismissTelegram = () => {
    sessionStorage.setItem(STORAGE_KEY_TELEGRAM, "1");
    setDismissedTelegram(true);
  };
  const dismissEmail = () => {
    sessionStorage.setItem(STORAGE_KEY_EMAIL, "1");
    setDismissedEmail(true);
  };

  if (!showTelegramBanner && !showEmailBanner) return null;

  return (
    <div className="space-y-2 px-4 md:px-6 pt-4">
      {showTelegramBanner && (
        <div className="flex items-center gap-3 rounded-lg border border-sky-500/35 bg-gradient-to-r from-sky-500/15 to-blue-500/10 px-4 py-3 text-sky-200">
          <p className="flex-1 text-sm">
            Привяжите Telegram для получения уведомлений в личные сообщения.{" "}
            <Link href="/dashboard/settings" className="font-medium underline hover:no-underline">
              Настройки
            </Link>
          </p>
          <button
            type="button"
            onClick={dismissTelegram}
            className="shrink-0 rounded p-1 text-sky-400 hover:bg-sky-500/20 hover:text-white"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>
      )}
      {showEmailBanner && (
        <div className="flex items-center gap-3 rounded-lg border border-sky-500/35 bg-gradient-to-r from-sky-500/15 to-blue-500/10 px-4 py-3 text-sky-200">
          <p className="flex-1 text-sm">
            Привяжите почту для получения уведомлений на email.{" "}
            <Link href="/dashboard/settings" className="font-medium underline hover:no-underline">
              Настройки
            </Link>
          </p>
          <button
            type="button"
            onClick={dismissEmail}
            className="shrink-0 rounded p-1 text-sky-400 hover:bg-sky-500/20 hover:text-white"
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}

export function clearDashboardBannerDismissed() {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(STORAGE_KEY_TELEGRAM);
  sessionStorage.removeItem(STORAGE_KEY_EMAIL);
}
