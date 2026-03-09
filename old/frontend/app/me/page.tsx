"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMyProfile,
  fetchMeAccess,
  fetchMySubscriptions,
  fetchMyTopupHistory,
  fetchLinkTelegramRequest,
  unlinkTelegramRequest,
  patchMyProfile,
  requestVerifyEmail,
  type MyProfile,
  type AccessSummaryResponse,
  type SubscriptionOut,
  type TopupHistoryResponse,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { getSignalSettings, setSignalSettings, type SignalSettings } from "@/lib/signalSettings";

const TELEGRAM_BOT_USERNAME = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME || "pingwinbetsbot";

function formatDate(s: string): string {
  try {
    return new Date(s).toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return s;
  }
}

export default function MePage() {
  const { isAuthenticated } = useAuth();
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [access, setAccess] = useState<AccessSummaryResponse | null>(null);
  const [subscriptions, setSubscriptions] = useState<SubscriptionOut[]>([]);
  const [topupHistory, setTopupHistory] = useState<TopupHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [signalSettings, setSignalSettingsState] = useState<SignalSettings>(() => getSignalSettings());
  const [saved, setSaved] = useState(false);
  const [savingDelivery, setSavingDelivery] = useState(false);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [linkTelegramLoading, setLinkTelegramLoading] = useState(false);
  const [linkTelegramError, setLinkTelegramError] = useState<string | null>(null);
  const [linkTelegramCode, setLinkTelegramCode] = useState<string | null>(null);
  const [linkTelegramLink, setLinkTelegramLink] = useState<string | null>(null);
  const [linkCodeCopied, setLinkCodeCopied] = useState(false);
  const [unlinkTelegramLoading, setUnlinkTelegramLoading] = useState(false);
  const [unlinkTelegramError, setUnlinkTelegramError] = useState<string | null>(null);
  const [emailToVerify, setEmailToVerify] = useState("");
  const [verifyEmailLoading, setVerifyEmailLoading] = useState(false);
  const [verifyEmailSent, setVerifyEmailSent] = useState(false);
  const [verifyEmailError, setVerifyEmailError] = useState<string | null>(null);
  const telegramBlockRef = useRef<HTMLDivElement>(null);
  const emailBlockRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const [p, a, s, topup] = await Promise.all([
        fetchMyProfile(),
        fetchMeAccess(),
        fetchMySubscriptions(),
        fetchMyTopupHistory(),
      ]);
      setProfile(p);
      setAccess(a);
      setSubscriptions(s);
      setTopupHistory(topup);
    } catch {
      setProfile(null);
      setAccess(null);
      setSubscriptions([]);
      setTopupHistory(null);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (profile?.telegram_linked) {
      setLinkTelegramCode(null);
      setLinkTelegramLink(null);
    }
  }, [profile?.telegram_linked]);

  useEffect(() => {
    setSignalSettingsState(getSignalSettings());
  }, []);

  const handleSignalSettingChange = useCallback((patch: Partial<SignalSettings>) => {
    setSignalSettings(patch);
    setSignalSettingsState((prev) => ({ ...prev, ...patch }));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, []);

  const handleDeliveryChange = useCallback(
    async (patch: { signal_via_telegram?: boolean; signal_via_email?: boolean }) => {
      setDeliveryError(null);
      setSavingDelivery(true);
      try {
        const updated = await patchMyProfile(patch);
        setProfile(updated);
      } catch (e) {
        setDeliveryError(e instanceof Error ? e.message : "Ошибка сохранения");
      } finally {
        setSavingDelivery(false);
      }
    },
    [],
  );

  const handleLinkTelegram = useCallback(async () => {
    setLinkTelegramError(null);
    setLinkTelegramCode(null);
    setLinkTelegramLink(null);
    setLinkTelegramLoading(true);
    try {
      const { link, code } = await fetchLinkTelegramRequest();
      setLinkTelegramCode(code);
      setLinkTelegramLink(link);
    } catch (e) {
      setLinkTelegramError(e instanceof Error ? e.message : "Не удалось получить код");
    } finally {
      setLinkTelegramLoading(false);
    }
  }, []);

  const openBotForLink = useCallback(() => {
    if (linkTelegramLink) window.open(linkTelegramLink, "_blank", "noopener,noreferrer");
  }, [linkTelegramLink]);

  const handleUnlinkTelegram = useCallback(async () => {
    if (!confirm("Отвязать Telegram от аккаунта? Уведомления в бота перестанут приходить.")) return;
    setUnlinkTelegramError(null);
    setUnlinkTelegramLoading(true);
    try {
      const updated = await unlinkTelegramRequest();
      setProfile(updated);
    } catch (e) {
      setUnlinkTelegramError(e instanceof Error ? e.message : "Не удалось отвязать");
    } finally {
      setUnlinkTelegramLoading(false);
    }
  }, []);

  if (!isAuthenticated) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-12">
        <p className="text-slate-400 mb-4">Войдите в аккаунт, чтобы открыть личный кабинет.</p>
        <Link href="/login" prefetch={false} className="text-teal-400 hover:underline">
          Войти
        </Link>
      </main>
    );
  }

  if (loading && !profile) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-12">
        <p className="text-slate-500">Загрузка...</p>
      </main>
    );
  }

  const isPlaceholderEmail = profile?.email?.startsWith("tg_") && profile?.email?.endsWith("@telegram.pingwin.local");

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-1">Личный кабинет</h1>
      <p className="text-slate-500 text-sm mb-8">
        Подписки, каналы связи и настройки сигналов.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Профиль и каналы */}
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Профиль</h2>
          <dl className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <dt className="text-slate-500 text-sm">Почта</dt>
                <dd className="text-white font-medium mt-0.5">
                  {isPlaceholderEmail ? "Не указана (вход через Telegram)" : profile?.email ?? "—"}
                  {profile?.email_verified === true && (
                    <span className="ml-2 text-emerald-400 text-xs">подтверждена</span>
                  )}
                  {profile?.email_verified === false && !isPlaceholderEmail && (
                    <span className="ml-2 text-amber-400 text-xs">не подтверждена</span>
                  )}
                </dd>
              </div>
              {(isPlaceholderEmail || (profile?.email && !profile?.email_verified)) && (
                <button
                  type="button"
                  onClick={() => emailBlockRef.current?.scrollIntoView({ behavior: "smooth" })}
                  className="shrink-0 px-3 py-1.5 rounded-lg bg-teal-600/90 text-white text-sm font-medium hover:bg-teal-500"
                >
                  Привязать
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <dt className="text-slate-500 text-sm">Telegram</dt>
                <dd className="text-white font-medium mt-0.5">
                  {profile?.telegram_linked ? (
                    <span className="text-emerald-400">
                      Привязан{profile?.telegram_username ? ` @${profile.telegram_username}` : ""}
                    </span>
                  ) : (
                    <span className="text-slate-400">Не привязан</span>
                  )}
                </dd>
              </div>
              {!profile?.telegram_linked && (
                <button
                  type="button"
                  onClick={() => telegramBlockRef.current?.scrollIntoView({ behavior: "smooth" })}
                  className="shrink-0 px-3 py-1.5 rounded-lg bg-teal-600/90 text-white text-sm font-medium hover:bg-teal-500"
                >
                  Привязать
                </button>
              )}
            </div>
          </dl>
        </section>

        {/* Подписки */}
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Подписки</h2>
          {access ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-300">Аналитика (ТГ):</span>
                {access.tg_analytics.has ? (
                  <>
                    <span className="text-emerald-400">до {access.tg_analytics.valid_until ?? ""}</span>
                    <span className="text-slate-500 text-sm">
                      {access.tg_analytics.scope === "all" ? "все виды" : access.tg_analytics.sport_key ?? "один вид"}
                    </span>
                  </>
                ) : (
                  <span className="text-slate-500">нет доступа</span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-300">Сигналы:</span>
                {access.signals.has ? (
                  <>
                    <span className="text-emerald-400">до {access.signals.valid_until ?? ""}</span>
                    <span className="text-slate-500 text-sm">
                      {access.signals.scope === "all" ? "все виды" : access.signals.sport_key ?? "один вид"}
                    </span>
                  </>
                ) : (
                  <span className="text-slate-500">нет доступа</span>
                )}
              </div>
              {subscriptions.length > 0 && (
                <div className="pt-2 border-t border-slate-700/80">
                  <p className="text-slate-500 text-xs mb-2">Активные подписки ({subscriptions.length})</p>
                  <ul className="space-y-1 text-sm">
                    {subscriptions.map((sub) => (
                      <li key={sub.id} className="text-slate-300">
                        {sub.access_type === "tg_analytics" ? "Аналитика" : "Сигналы"} · до {formatDate(sub.valid_until)}
                        {sub.scope === "one_sport" && sub.sport_key && ` · ${sub.sport_key}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <Link href="/pricing" prefetch={false} className="inline-block text-teal-400 hover:text-teal-300 text-sm font-medium">
                Тарифы →
              </Link>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">Не удалось загрузить данные подписок.</p>
          )}
        </section>
      </div>

      {/* История пополнений */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">История пополнений</h2>
        <p className="text-slate-400 text-sm mb-4">Счета (оплаты) и выдачи подписок через поддержку.</p>
        {!topupHistory ? (
          <p className="text-slate-500 text-sm">Загрузка…</p>
        ) : (topupHistory.invoices.length === 0 && topupHistory.subscription_grants.length === 0) ? (
          <p className="text-slate-500 text-sm">Нет записей</p>
        ) : (
          <div className="space-y-4">
            {topupHistory.invoices.length > 0 && (
              <div>
                <h3 className="text-slate-300 text-sm font-medium mb-2">Счета</h3>
                <ul className="space-y-2 text-sm">
                  {topupHistory.invoices.map((i) => (
                    <li key={i.id} className="flex flex-wrap items-center gap-2 text-slate-300">
                      <span>{i.amount} {i.currency}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${i.status === "paid" ? "bg-emerald-900/50 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>{i.status === "paid" ? "Оплачен" : i.status}</span>
                      <span className="text-slate-500">{i.created_at ? new Date(i.created_at).toLocaleString("ru") : ""}</span>
                      {i.paid_at && <span className="text-slate-500">оплачен {new Date(i.paid_at).toLocaleString("ru")}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {topupHistory.subscription_grants.length > 0 && (
              <div>
                <h3 className="text-slate-300 text-sm font-medium mb-2">Выдачи через поддержку</h3>
                <ul className="space-y-2 text-sm">
                  {topupHistory.subscription_grants.map((g) => (
                    <li key={g.id} className="text-slate-300">
                      {g.access_type === "tg_analytics" ? "Аналитика" : "Сигналы"} · до {formatDate(g.valid_until)}
                      {g.scope === "one_sport" && g.sport_key && ` · ${g.sport_key}`}
                      {g.comment && <span className="text-slate-500 ml-2">— {g.comment}</span>}
                      <span className="text-slate-500 text-xs ml-2">{g.created_at ? new Date(g.created_at).toLocaleString("ru") : ""}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Добавить канал: Telegram / почта */}
      <section ref={telegramBlockRef} className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Каналы связи</h2>
        <p className="text-slate-400 text-sm mb-4">
          Если вы зарегистрировались по одному каналу (почта или Telegram), можно добавить второй для получения сигналов и уведомлений.
        </p>
        <div className="space-y-4">
          {profile?.telegram_linked && (
            <div className="rounded-lg bg-slate-800/80 p-4">
              <p className="font-medium text-white mb-1">Telegram привязан</p>
              <p className="text-slate-400 text-sm mb-3">
                {profile.telegram_username ? `@${profile.telegram_username}` : "Аккаунт подключён"}. Уведомления о прогнозах приходят в бота. Можно отвязать — тогда уведомления в Telegram перестанут приходить, войти на сайт по почте по-прежнему можно.
              </p>
              {unlinkTelegramError && <p className="text-rose-400 text-sm mb-2">{unlinkTelegramError}</p>}
              <button
                type="button"
                onClick={() => void handleUnlinkTelegram()}
                disabled={unlinkTelegramLoading}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-slate-600 text-slate-300 hover:bg-slate-700 hover:text-white text-sm font-medium disabled:opacity-50"
              >
                {unlinkTelegramLoading ? "Отвязка…" : "Отвязать Telegram"}
              </button>
            </div>
          )}
          {!profile?.telegram_linked && (
            <div className="rounded-lg bg-slate-800/80 p-4">
              <p className="font-medium text-white mb-1">Привязать Telegram</p>
              <p className="text-slate-400 text-sm mb-3">
                Бот @{TELEGRAM_BOT_USERNAME} нужен только для личных уведомлений. В каналы его добавлять не нужно — мы пишем только вам в личку.
              </p>
              {!linkTelegramCode ? (
                <>
                  <button
                    type="button"
                    onClick={() => void handleLinkTelegram()}
                    disabled={linkTelegramLoading}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-700 text-slate-200 hover:bg-slate-600 text-sm font-medium disabled:opacity-50"
                  >
                    {linkTelegramLoading ? "Загрузка…" : "Получить код привязки"}
                  </button>
                  <p className="text-slate-500 text-xs mt-2">
                    Вы получите код на 15 минут. Отправьте его боту в Telegram — аккаунт привяжется. Один аккаунт на сайте = один Telegram.
                  </p>
                </>
              ) : (
                <>
                  <p className="text-slate-300 text-sm mb-2">Код привязки (действует 15 мин):</p>
                  <p className="text-2xl font-mono font-bold text-teal-400 tracking-widest mb-3">{linkTelegramCode}</p>
                  <p className="text-slate-400 text-sm mb-3">
                    Перейдите в бота по ссылке — привязка произойдёт автоматически. Или скопируйте код и отправьте его боту вручную.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <a
                      href={linkTelegramLink ?? `https://t.me/${TELEGRAM_BOT_USERNAME}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-teal-600 text-white hover:bg-teal-500 text-sm font-medium"
                    >
                      Перейти в бота по ссылке (привязка сразу)
                    </a>
                    <button
                      type="button"
                      onClick={() => {
                        if (linkTelegramCode && typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                          navigator.clipboard.writeText(linkTelegramCode);
                          setLinkTelegramError(null);
                          setLinkCodeCopied(true);
                          setTimeout(() => setLinkCodeCopied(false), 2000);
                        }
                      }}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm"
                    >
                      {linkCodeCopied ? "Скопировано" : "Скопировать код"}
                    </button>
                  </div>
                </>
              )}
              {linkTelegramError && (
                <p className="text-rose-400 text-sm mt-2">{linkTelegramError}</p>
              )}
              <p className="text-slate-500 text-xs mt-2">
                Регистрация через бота: откройте <a href={`https://t.me/${TELEGRAM_BOT_USERNAME}`} target="_blank" rel="noopener noreferrer" className="text-teal-400 hover:underline">@{TELEGRAM_BOT_USERNAME}</a> и отправьте /start. Вход по почте — виджет на странице <Link href="/login" prefetch={false} className="text-teal-400 hover:underline">входа</Link>.
              </p>
            </div>
          )}
          {(isPlaceholderEmail || !profile?.email_verified) && (
            <div ref={emailBlockRef} className="rounded-lg bg-slate-800/80 p-4">
              <p className="font-medium text-white mb-1">Добавить или подтвердить почту</p>
              <p className="text-slate-400 text-sm mb-3">
                Укажите email — на него придёт ссылка для подтверждения. После перехода по ссылке почта будет привязана к аккаунту.
              </p>
              {verifyEmailSent ? (
                <p className="text-emerald-400 text-sm">Письмо отправлено. Проверьте почту и перейдите по ссылке.</p>
              ) : (
                <>
                  <input
                    type="email"
                    value={emailToVerify}
                    onChange={(e) => {
                      setEmailToVerify(e.target.value);
                      setVerifyEmailError(null);
                    }}
                    placeholder="you@example.com"
                    className="w-full max-w-xs rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white text-sm placeholder-slate-500 mb-2"
                  />
                  <button
                    type="button"
                    onClick={async () => {
                      setVerifyEmailError(null);
                      if (!emailToVerify.trim()) return;
                      setVerifyEmailLoading(true);
                      try {
                        await requestVerifyEmail(emailToVerify.trim());
                        setVerifyEmailSent(true);
                      } catch (e) {
                        setVerifyEmailError(e instanceof Error ? e.message : "Ошибка отправки");
                      } finally {
                        setVerifyEmailLoading(false);
                      }
                    }}
                    disabled={verifyEmailLoading || !emailToVerify.trim()}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-700 text-slate-200 hover:bg-slate-600 text-sm font-medium disabled:opacity-50"
                  >
                    {verifyEmailLoading ? "Отправка…" : "Отправить ссылку подтверждения"}
                  </button>
                  {verifyEmailError && <p className="text-rose-400 text-sm mt-2">{verifyEmailError}</p>}
                </>
              )}
              <p className="text-slate-500 text-xs mt-2">
                Подтверждение почты нужно для получения уведомлений на email и восстановления доступа.
              </p>
            </div>
          )}
          {profile?.telegram_linked && !isPlaceholderEmail && profile?.email_verified && (
            <p className="text-slate-500 text-sm">Оба канала подключены.</p>
          )}
        </div>
      </section>

      {/* Настройки сигналов */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-4">Уведомления о рекомендациях</h2>

        {access?.signals.has ? (
          <>
            {access.tg_analytics.has ? (
              <p className="text-emerald-400/90 text-sm mb-4">
                Подписка на сигналы активна до {access.signals.valid_until ? formatDate(access.signals.valid_until) : ""}. Новые рекомендации отправляются в выбранные каналы.
              </p>
            ) : (
              <div className="rounded-lg bg-amber-900/30 border border-amber-700/50 p-4 mb-4">
                <p className="text-amber-200 text-sm font-medium">Уведомления в личку доступны только при подписке на аналитику.</p>
                <p className="text-slate-400 text-sm mt-1">
                  У вас оформлен только VIP-канал (сигналы). Чтобы получать рекомендации в Telegram и на почту, оформите подписку на аналитику на странице <Link href="/pricing" prefetch={false} className="text-teal-400 hover:underline">тарифов</Link>.
                </p>
              </div>
            )}
          </>
        ) : (
          <div className="rounded-lg bg-amber-900/30 border border-amber-700/50 p-4 mb-4">
            <p className="text-amber-200 text-sm font-medium">Уведомления приходят только при активной подписке на сигналы.</p>
            <p className="text-slate-400 text-sm mt-1">
              Оформите подписку на сигналы, чтобы получать каждую новую рекомендацию в Telegram и/или на почту. После окончания подписки рассылка прекращается.
            </p>
            <Link href="/pricing" prefetch={false} className="inline-block text-teal-400 hover:text-teal-300 text-sm font-medium mt-2">
              Оформить подписку →
            </Link>
          </div>
        )}

        <div className="mb-6">
          <p className="text-slate-400 text-sm mb-3">Куда отправлять уведомления</p>
          {(() => {
            const canReceivePersonal = access?.signals.has && access?.tg_analytics.has;
            return (
              <div className="flex flex-wrap gap-6">
                <label className={`flex items-center gap-2 ${!canReceivePersonal ? "cursor-not-allowed opacity-70" : "cursor-pointer"}`}>
                  <input
                    type="checkbox"
                    checked={profile?.signal_via_telegram ?? true}
                    disabled={savingDelivery || !profile?.telegram_linked || !canReceivePersonal}
                    onChange={(e) => void handleDeliveryChange({ signal_via_telegram: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-800 text-teal-500 focus:ring-teal-500 disabled:opacity-50"
                  />
                  <span className="text-slate-300">
                    В привязанный Telegram
                    {!profile?.telegram_linked && (
                      <span className="text-slate-500 text-xs ml-1">(сначала привяжите Telegram)</span>
                    )}
                  </span>
                </label>
                <label className={`flex items-center gap-2 ${!canReceivePersonal ? "cursor-not-allowed opacity-70" : "cursor-pointer"}`}>
                  <input
                    type="checkbox"
                    checked={profile?.signal_via_email ?? true}
                    disabled={savingDelivery || isPlaceholderEmail || !canReceivePersonal}
                    onChange={(e) => void handleDeliveryChange({ signal_via_email: e.target.checked })}
                    className="rounded border-slate-600 bg-slate-800 text-teal-500 focus:ring-teal-500 disabled:opacity-50"
                  />
                  <span className="text-slate-300">
                    На почту
                    {isPlaceholderEmail && (
                      <span className="text-slate-500 text-xs ml-1">(укажите почту в профиле)</span>
                    )}
                  </span>
                </label>
              </div>
            );
          })()}
          {deliveryError && <p className="text-rose-400 text-sm mt-2">{deliveryError}</p>}
        </div>

        <p className="text-slate-400 text-sm mb-4">
          Ограничения по времени доставки (режим тишины). Пока сохраняются только в этом устройстве; применение на стороне рассылки — в разработке.
        </p>

        <div className="space-y-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={signalSettings.quiet_mode_enabled}
              onChange={(e) => handleSignalSettingChange({ quiet_mode_enabled: e.target.checked })}
              className="rounded border-slate-600 bg-slate-800 text-teal-500 focus:ring-teal-500"
            />
            <span className="text-slate-300">Режим тишины — не присылать сигналы в указанный интервал</span>
          </label>

          {signalSettings.quiet_mode_enabled && (
            <div className="flex flex-wrap items-center gap-3 pl-6">
              <div>
                <label className="block text-slate-500 text-xs mb-1">С</label>
                <input
                  type="time"
                  value={signalSettings.quiet_start}
                  onChange={(e) => handleSignalSettingChange({ quiet_start: e.target.value })}
                  className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white text-sm"
                />
              </div>
              <div>
                <label className="block text-slate-500 text-xs mb-1">До</label>
                <input
                  type="time"
                  value={signalSettings.quiet_end}
                  onChange={(e) => handleSignalSettingChange({ quiet_end: e.target.value })}
                  className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-white text-sm"
                />
              </div>
              <p className="text-slate-500 text-xs w-full">По местному времени браузера</p>
            </div>
          )}

          {saved && (
            <p className="text-emerald-400 text-sm">Настройки сохранены</p>
          )}
        </div>
      </section>

      <Link href="/dashboard" prefetch={false} className="text-slate-400 hover:text-white text-sm">
        ← На дашборд
      </Link>
    </main>
  );
}
