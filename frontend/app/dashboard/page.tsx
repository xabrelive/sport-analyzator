"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  createBillingVipInvite,
  createBillingCheckout,
  getBillingMyInvoices,
  getBillingMySubscriptions,
  getBillingPaymentMethods,
  getBillingProducts,
  getBillingVipAccess,
  getMe,
  getTableTennisForecastStats,
  type BillingCheckoutResponse,
  type BillingMyInvoiceItem,
  type BillingMySubscriptionsResponse,
  type BillingVipAccessResponse,
  type BillingVipCreateInviteResponse,
  type MeProfile,
  type TableTennisForecastStats,
} from "@/lib/api";

type ChannelTab = "free" | "paid" | "vip" | "bot_signals" | "no_ml";
type PeriodFilter = "today" | "1d" | "7d" | "30d";

const CHANNELS: Array<{ id: ChannelTab; label: string }> = [
  { id: "free", label: "Бесплатный канал" },
  { id: "paid", label: "Платная аналитика" },
  { id: "vip", label: "VIP чат" },
  { id: "bot_signals", label: "Сигналы от бота" },
  { id: "no_ml", label: "Аналитика без ML" },
];

const PERIODS: Array<{ id: PeriodFilter; label: string }> = [
  { id: "today", label: "Сегодня" },
  { id: "1d", label: "1 день" },
  { id: "7d", label: "7 дней" },
  { id: "30d", label: "30 дней" },
];

function statValue(v: number | null | undefined, digits = 0): string {
  if (v == null) return "—";
  return digits > 0 ? v.toFixed(digits) : String(v);
}

function moneyCompact(v: number | null | undefined): string {
  if (v == null) return "—";
  const rounded = Math.round(v * 100) / 100;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2);
}

function tariffTitle(name: string, priceRub: number, priceUsd: number): string {
  return `${name} — ${moneyCompact(priceRub)} RUB / ${moneyCompact(priceUsd)} USD`;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getRange(period: PeriodFilter): { date_from: string; date_to: string } {
  const end = new Date();
  const start = new Date();
  if (period === "today") {
    return { date_from: isoDate(end), date_to: isoDate(end) };
  }
  if (period === "1d") {
    start.setUTCDate(start.getUTCDate() - 1);
    return { date_from: isoDate(start), date_to: isoDate(end) };
  }
  if (period === "7d") {
    start.setUTCDate(start.getUTCDate() - 6);
    return { date_from: isoDate(start), date_to: isoDate(end) };
  }
  start.setUTCDate(start.getUTCDate() - 29);
  return { date_from: isoDate(start), date_to: isoDate(end) };
}

function formatIsoDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function invoiceStatusLabel(status: string): { text: string; className: string } {
  if (status === "paid") return { text: "Оплачен", className: "text-emerald-300" };
  if (status === "cancelled") return { text: "Отменён", className: "text-amber-300" };
  return { text: "Ожидает оплаты", className: "text-sky-300" };
}

function LinkifiedText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  const tokenRe = /(https?:\/\/[^\s]+|t\.me\/[A-Za-z0-9_]+|@[A-Za-z0-9_]{3,})/g;
  return (
    <span className="whitespace-pre-wrap break-words">
      {lines.map((line, lineIdx) => (
        <span key={`line-${lineIdx}`}>
          {line.split(tokenRe).map((part, idx) => {
            if (!part) return null;
            if (/^https?:\/\//i.test(part)) {
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={part}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            if (/^t\.me\//i.test(part)) {
              const href = `https://${part}`;
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            if (/^@[A-Za-z0-9_]{3,}$/.test(part)) {
              const handle = part.slice(1);
              return (
                <a
                  key={`${lineIdx}-${idx}`}
                  href={`https://t.me/${handle}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-300 hover:text-sky-200 underline"
                >
                  {part}
                </a>
              );
            }
            return <span key={`${lineIdx}-${idx}`}>{part}</span>;
          })}
          {lineIdx < lines.length - 1 ? "\n" : null}
        </span>
      ))}
    </span>
  );
}

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<ChannelTab>("paid");
  const [period, setPeriod] = useState<PeriodFilter>("7d");
  const [stats, setStats] = useState<TableTennisForecastStats | null>(null);
  const [me, setMe] = useState<MeProfile | null>(null);
  const [subs, setSubs] = useState<BillingMySubscriptionsResponse | null>(null);
  const [lastInvoice, setLastInvoice] = useState<BillingMyInvoiceItem | null>(null);
  const [vipAccess, setVipAccess] = useState<BillingVipAccessResponse | null>(null);
  const [vipInvite, setVipInvite] = useState<BillingVipCreateInviteResponse | null>(null);
  const [vipInviteLoading, setVipInviteLoading] = useState(false);
  const [products, setProducts] = useState<
    Array<{ id: string; code: string; name: string; service_key: string; duration_days: number; price_rub: number; price_usd: number }>
  >([]);
  const [paymentMethods, setPaymentMethods] = useState<
    Array<{ id: string; name: string; method_type: string; instructions: string | null }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [buyProductCode, setBuyProductCode] = useState<string | null>(null);
  const [buyMethodId, setBuyMethodId] = useState<string>("");
  const [buyComment, setBuyComment] = useState("");
  const [buyLoading, setBuyLoading] = useState(false);
  const [buyResult, setBuyResult] = useState<BillingCheckoutResponse | null>(null);

  const loadBase = async () => {
    setLoading(true);
    setError(null);
    try {
      const [meRes, subRes, invRes, productsRes, methodsRes, vipAccessRes] = await Promise.all([
        getMe(),
        getBillingMySubscriptions(),
        getBillingMyInvoices(),
        getBillingProducts(),
        getBillingPaymentMethods(),
        getBillingVipAccess(),
      ]);
      setMe(meRes);
      setSubs(subRes);
      setLastInvoice(invRes.items?.[0] ?? null);
      setProducts(productsRes);
      setPaymentMethods(methodsRes);
      setVipAccess(vipAccessRes);
      if (!buyMethodId && methodsRes.length > 0) {
        setBuyMethodId(methodsRes[0].id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки дашборда");
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async (channel: ChannelTab) => {
    setStatsLoading(true);
    try {
      const range = getRange(period);
      const s = await getTableTennisForecastStats({
        channel,
        date_from: range.date_from,
        date_to: range.date_to,
      });
      setStats(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки статистики");
    } finally {
      setStatsLoading(false);
    }
  };

  useEffect(() => {
    void loadBase();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadStats(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, period]);

  const hit = stats?.by_status?.hit ?? 0;
  const miss = stats?.by_status?.miss ?? 0;
  const pending = stats?.by_status?.pending ?? 0;
  const cancelled = stats?.by_status?.cancelled ?? 0;

  const notificationSummary = useMemo(() => {
    if (!me) return "—";
    const parts: string[] = [];
    if (me.notify_telegram) {
      parts.push(me.telegram_linked ? "Telegram: включён" : "Telegram: не привязан");
    } else {
      parts.push("Telegram: выключен");
    }
    if (me.notify_email) {
      parts.push(me.email_linked ? "Email: включён" : "Email: не привязан");
    } else {
      parts.push("Email: выключен");
    }
    return parts.join(" · ");
  }, [me]);

  const analyticsSub = subs?.analytics;
  const analyticsNoMlSub = subs?.analytics_no_ml;
  const vipSub = subs?.vip_channel;
  const invoiceBadge = invoiceStatusLabel(lastInvoice?.status || "pending");
  const buyProduct = useMemo(
    () => products.find((p) => p.code === buyProductCode) || null,
    [products, buyProductCode]
  );
  const selectedMethod = useMemo(
    () => paymentMethods.find((m) => m.id === buyMethodId) || null,
    [paymentMethods, buyMethodId]
  );
  const notificationEmail = me?.notification_email_masked || me?.email_masked || "не задан";
  const telegramLinked = Boolean(me?.telegram_linked);

  return (
    <div className="p-6 md:p-8 space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold text-white mb-2">Дашборд</h1>
        <p className="text-slate-400 text-sm">Главная сводка по каналам, подпискам и уведомлениям.</p>
      </div>

      <a
        href="https://t.me/PingwinBets"
        target="_blank"
        rel="noopener noreferrer"
        className="block rounded-xl border-2 border-emerald-500/50 bg-gradient-to-br from-emerald-900/30 to-slate-800/60 p-4 md:p-5 hover:border-emerald-400/60 hover:from-emerald-900/40 transition"
      >
        <div className="flex items-start gap-3">
          <span className="text-3xl">🐧</span>
          <div>
            <p className="text-emerald-200 font-semibold text-lg">Бесплатный канал</p>
            <p className="text-slate-300 text-sm mt-1">
              Каждый день публикуем наши прогнозы бесплатно в Telegram
            </p>
            <p className="text-emerald-300 font-medium mt-2">t.me/PingwinBets →</p>
          </div>
        </div>
      </a>

      {error && <p className="text-sm text-rose-300">{error}</p>}

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
          <h2 className="text-white font-semibold mb-3">Подписки</h2>
          {loading ? (
            <p className="text-slate-400 text-sm">Загрузка…</p>
          ) : (
            <div className="space-y-3 text-sm">
              <div className="rounded-lg border border-slate-700/70 bg-slate-900/40 p-3">
                <p className="text-slate-300">Аналитика</p>
                <p className="text-slate-400 mt-1">
                  {analyticsSub?.is_active
                    ? `Активна до ${analyticsSub.valid_until} · осталось ${analyticsSub.days_left} дн`
                    : "Не активна"}
                </p>
              </div>
              <div className="rounded-lg border border-slate-700/70 bg-slate-900/40 p-3">
                <p className="text-slate-300">Аналитика без ML</p>
                <p className="text-slate-400 mt-1">
                  {analyticsNoMlSub?.is_active
                    ? `Активна до ${analyticsNoMlSub.valid_until} · осталось ${analyticsNoMlSub.days_left} дн`
                    : "Не активна"}
                </p>
              </div>
              <div className="rounded-lg border border-slate-700/70 bg-slate-900/40 p-3">
                <p className="text-slate-300">VIP канал</p>
                <p className="text-slate-400 mt-1">
                  {vipSub?.is_active
                    ? `Активна до ${vipSub.valid_until} · осталось ${vipSub.days_left} дн`
                    : "Не активна"}
                </p>
                {vipSub?.is_active ? (
                  <div className="mt-2 space-y-2">
                    {vipAccess?.is_member ? (
                      <p className="text-emerald-300 text-xs">
                        Вы уже в VIP-канале
                        {vipAccess.channel_url ? (
                          <>
                            {" · "}
                            <a
                              href={vipAccess.channel_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="underline text-sky-300 hover:text-sky-200"
                            >
                              открыть канал
                            </a>
                          </>
                        ) : null}
                      </p>
                    ) : (
                      <>
                        <button
                          type="button"
                          disabled={vipInviteLoading || !vipAccess?.can_create_invite}
                          onClick={async () => {
                            try {
                              setVipInviteLoading(true);
                              const res = await createBillingVipInvite();
                              setVipInvite(res);
                              const access = await getBillingVipAccess();
                              setVipAccess(access);
                            } catch (e) {
                              setError(e instanceof Error ? e.message : "Ошибка получения ссылки VIP");
                            } finally {
                              setVipInviteLoading(false);
                            }
                          }}
                          className="inline-flex rounded border border-sky-600/60 px-3 py-1.5 text-xs text-sky-200 hover:bg-sky-900/30 disabled:opacity-50"
                        >
                          {vipInviteLoading ? "Формируем ссылку..." : "Присоединиться к VIP чату"}
                        </button>
                        <p className="text-amber-300 text-xs">
                          Ссылка одноразовая: после перехода она станет недействительной.
                        </p>
                        {vipInvite?.invite_link ? (
                          <a
                            href={vipInvite.invite_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block text-xs underline text-sky-300 hover:text-sky-200 break-all"
                          >
                            {vipInvite.invite_link}
                          </a>
                        ) : null}
                        {vipInvite?.already_in_channel && vipInvite.channel_url ? (
                          <a
                            href={vipInvite.channel_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block text-xs underline text-sky-300 hover:text-sky-200"
                          >
                            Вы уже в канале, открыть VIP
                          </a>
                        ) : null}
                      </>
                    )}
                  </div>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => setBuyProductCode(products[0]?.code || null)}
                className="inline-flex rounded-md bg-gradient-to-r from-sky-600 to-blue-600 px-3 py-2 text-white hover:from-sky-500 hover:to-blue-500"
              >
                Купить / Продлить
              </button>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
          <h2 className="text-white font-semibold mb-3">Уведомления</h2>
          {loading ? (
            <p className="text-slate-400 text-sm">Загрузка…</p>
          ) : (
            <div className="space-y-3 text-sm">
              <p className="text-slate-300">{notificationSummary}</p>
              <p className="text-slate-400">
                Telegram: {me?.telegram_username ? `@${me.telegram_username}` : me?.telegram_linked ? "привязан" : "не привязан"}
              </p>
              {analyticsSub?.is_active && !telegramLinked && me?.notify_telegram ? (
                <p className="text-amber-300 text-xs">
                  Для получения уведомлений в боте привяжите Telegram в настройках профиля.
                </p>
              ) : null}
              <p className="text-slate-400">Email для уведомлений: {notificationEmail}</p>
              <Link href="/dashboard/settings" className="inline-flex rounded-md border border-slate-600 px-3 py-2 text-slate-200 hover:bg-slate-700/60">
                Открыть настройки
              </Link>
            </div>
          )}
        </div>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
          <h2 className="text-white font-semibold mb-3">Быстрые действия</h2>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <Link href="/dashboard/table-tennis/live" className="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200 hover:bg-slate-700/40">
              Лайв матчи
            </Link>
            <Link href="/dashboard/table-tennis/line" className="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200 hover:bg-slate-700/40">
              Линия матчей
            </Link>
            <Link href="/dashboard/table-tennis/stats" className="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200 hover:bg-slate-700/40">
              Статистика
            </Link>
            <Link href="/dashboard/calculator" className="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200 hover:bg-slate-700/40">
              Калькулятор
            </Link>
          </div>
        </div>

        <div className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
          <h2 className="text-white font-semibold mb-3">Последний инвойс</h2>
          {loading ? (
            <p className="text-slate-400 text-sm">Загрузка…</p>
          ) : !lastInvoice ? (
            <div className="space-y-3 text-sm">
              <p className="text-slate-400">Инвойсов пока нет.</p>
              <Link
                href="/pricing"
                className="inline-flex rounded-md bg-gradient-to-r from-sky-600 to-blue-600 px-3 py-2 text-white hover:from-sky-500 hover:to-blue-500"
              >
                Перейти к тарифам
              </Link>
            </div>
          ) : (
            <div className="space-y-2 text-sm">
              <p className={`font-medium ${invoiceBadge.className}`}>{invoiceBadge.text}</p>
              <p className="text-slate-300">Сумма: {statValue(lastInvoice.amount_rub, 2)} RUB</p>
              <p className="text-slate-400">Создан: {formatIsoDateTime(lastInvoice.created_at)}</p>
              {lastInvoice.paid_at ? <p className="text-slate-400">Оплачен: {formatIsoDateTime(lastInvoice.paid_at)}</p> : null}
              <div className="pt-1">
                <button
                  type="button"
                  onClick={() => setBuyProductCode(products[0]?.code || null)}
                  className="inline-flex rounded-md border border-slate-600 px-3 py-2 text-slate-200 hover:bg-slate-700/60"
                >
                  Купить / Продлить
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
        <h2 className="text-white font-semibold mb-3">Тарифы</h2>
        {loading ? (
          <p className="text-slate-400 text-sm">Загрузка…</p>
        ) : products.length === 0 ? (
          <p className="text-slate-400 text-sm">Тарифы пока не настроены.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {products.map((p) => (
              <div key={p.id} className="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
                <p className="text-slate-200 font-medium">{tariffTitle(p.name, p.price_rub, p.price_usd)}</p>
                <p className="text-slate-400 text-sm mt-1">
                  {p.service_key === "analytics"
                    ? "Аналитика (ML)"
                    : p.service_key === "analytics_no_ml"
                    ? "Аналитика без ML"
                    : "VIP канал"}{" "}
                  · {p.duration_days} дн
                </p>
                <p className="text-white text-lg font-semibold mt-2">
                  {moneyCompact(p.price_rub)} RUB / {moneyCompact(p.price_usd)} USD
                </p>
                <button
                  type="button"
                  disabled={p.service_key === "vip_channel" && !telegramLinked}
                  onClick={() => {
                    setBuyProductCode(p.code);
                    setBuyResult(null);
                    setBuyComment("");
                  }}
                  className="mt-3 inline-flex rounded-md bg-gradient-to-r from-sky-600 to-blue-600 px-3 py-2 text-sm text-white hover:from-sky-500 hover:to-blue-500 disabled:opacity-40"
                >
                  Оплатить
                </button>
                {p.service_key === "vip_channel" && !telegramLinked ? (
                  <p className="mt-2 text-xs text-amber-300">
                    Для покупки VIP привяжите Telegram в настройках профиля.
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-4">
        <h2 className="text-white font-semibold mb-3">Статистика по каналам</h2>
        <div className="mb-3 flex flex-wrap gap-2">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setPeriod(p.id)}
              className={`px-3 py-1.5 rounded-md text-sm ${
                period === p.id
                  ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                  : "border border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 border-b border-slate-700 pb-3 mb-4">
          {CHANNELS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1.5 rounded-md text-sm ${
                activeTab === tab.id
                  ? "bg-gradient-to-r from-sky-500/25 to-blue-500/25 text-sky-100 border border-sky-500/35"
                  : "text-slate-400 border border-slate-700 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {statsLoading ? (
          <p className="text-slate-400 text-sm">Загрузка статистики…</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Всего</p>
              <p className="text-white text-lg font-semibold">{statValue(stats?.total)}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Угадано</p>
              <p className="text-emerald-400 text-lg font-semibold">{hit}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Не угадано</p>
              <p className="text-rose-400 text-lg font-semibold">{miss}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Ожидают</p>
              <p className="text-sky-300 text-lg font-semibold">{pending}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Hit-rate</p>
              <p className="text-white text-lg font-semibold">
                {stats?.hit_rate != null ? `${stats.hit_rate.toFixed(1)}%` : "—"}
              </p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2">
              <p className="text-slate-500 text-xs">Средний кф</p>
              <p className="text-white text-lg font-semibold">{statValue(stats?.avg_odds, 2)}</p>
            </div>
            <div className="rounded-lg bg-slate-900/50 border border-slate-700 px-3 py-2 md:col-span-3 xl:col-span-6">
              <p className="text-slate-500 text-xs">Отменено</p>
              <p className="text-amber-300 text-lg font-semibold">{cancelled}</p>
            </div>
          </div>
        )}
        <div className="mt-4">
          <Link href="/dashboard/table-tennis/stats" className="text-sky-300 hover:text-sky-200 text-sm">
            Открыть детальную статистику →
          </Link>
        </div>
      </section>

      {buyProductCode ? (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-[1px] px-4 py-8 overflow-y-auto">
          <div className="mx-auto max-w-lg rounded-xl border border-slate-700 bg-slate-900 p-5">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-white text-lg font-semibold">Оплата тарифа</h3>
              <button
                type="button"
                onClick={() => setBuyProductCode(null)}
                className="text-slate-400 hover:text-slate-200"
              >
                ✕
              </button>
            </div>
            <p className="text-slate-300 mt-2">
              {buyProduct ? tariffTitle(buyProduct.name, buyProduct.price_rub, buyProduct.price_usd) : "—"}
            </p>
            <p className="text-slate-400 text-sm mt-1">
              {buyProduct ? `${moneyCompact(buyProduct.price_rub)} RUB / ${moneyCompact(buyProduct.price_usd)} USD` : ""}
            </p>

            <div className="mt-4 space-y-2">
              <p className="text-slate-200 text-sm">Способ оплаты</p>
              {paymentMethods.map((m) => (
                <label key={m.id} className="flex items-start gap-2 rounded border border-slate-700 bg-slate-800/40 p-2">
                  <input
                    type="radio"
                    name="payment_method"
                    checked={buyMethodId === m.id}
                    onChange={() => setBuyMethodId(m.id)}
                    className="mt-1"
                  />
                  <span className="text-sm text-slate-300">
                    <span className="font-medium">{m.name}</span>
                    {m.instructions ? (
                      <span className="block text-slate-500 mt-0.5">
                        <LinkifiedText text={m.instructions} />
                      </span>
                    ) : null}
                  </span>
                </label>
              ))}
            </div>

            <label className="mt-4 block text-sm text-slate-300">
              Комментарий к оплате (опционально)
              <textarea
                value={buyComment}
                onChange={(e) => setBuyComment(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-white"
              />
            </label>

            {selectedMethod?.instructions ? (
              <div className="mt-2 text-xs text-slate-500">
                <span>Инструкция: </span>
                <LinkifiedText text={selectedMethod.instructions} />
              </div>
            ) : null}
            {buyResult ? (
              <p className="mt-3 rounded border border-emerald-700/40 bg-emerald-900/20 p-2 text-sm text-emerald-300">
                Инвойс создан: {buyResult.invoice_id}. Статус: {buyResult.status}. Ожидает подтверждения админом.
              </p>
            ) : null}
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                disabled={buyLoading || !buyProduct}
                onClick={async () => {
                  if (!buyProduct) return;
                  try {
                    setBuyLoading(true);
                    const res = await createBillingCheckout({
                      items: [{ product_code: buyProduct.code, quantity: 1 }],
                      payment_method_id: buyMethodId || undefined,
                      comment: buyComment.trim() || undefined,
                    });
                    setBuyResult(res);
                    const inv = await getBillingMyInvoices();
                    setLastInvoice(inv.items?.[0] ?? null);
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "Ошибка создания инвойса");
                  } finally {
                    setBuyLoading(false);
                  }
                }}
                className="rounded bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-500 disabled:opacity-50"
              >
                {buyLoading ? "Создание..." : "Создать инвойс"}
              </button>
              <button
                type="button"
                onClick={() => setBuyProductCode(null)}
                className="rounded border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
