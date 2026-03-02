"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  fetchSignalsStats,
  fetchMeAccess,
  type SignalStatsResponse,
  type AccessSummaryResponse,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

const PERIODS = [
  { key: "day", days: 1, label: "За день" },
  { key: "week", days: 7, label: "За неделю" },
  { key: "month", days: 30, label: "За месяц" },
  { key: "all", days: 90, label: "За всё время" },
] as const;

export default function DashboardPage() {
  const [periodKey, setPeriodKey] = useState<typeof PERIODS[number]["key"]>("week");
  const [stats, setStats] = useState<SignalStatsResponse | null>(null);
  const [access, setAccess] = useState<AccessSummaryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const { isAuthenticated } = useAuth();

  const period = PERIODS.find((p) => p.key === periodKey)!;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSignalsStats(period.days)
      .then((d) => { if (!cancelled) setStats(d); })
      .catch(() => { if (!cancelled) setStats(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [period.days]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    fetchMeAccess()
      .then((d) => { if (!cancelled) setAccess(d); })
      .catch(() => { if (!cancelled) setAccess(null); });
    return () => { cancelled = true; };
  }, [isAuthenticated]);

  return (
    <main className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-bold text-white mb-1">Дашборд</h1>
      <p className="text-slate-500 text-sm mb-6">
        Статистика по прогнозам (сигналам) по видам спорта. Бесплатный доступ — ограниченная аналитика.
      </p>

      {isAuthenticated && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
          <h2 className="text-lg font-semibold text-white mb-4">Мои подписки</h2>
          {access == null ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-300">Полная аналитика (ТГ):</span>
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
              <Link href="/pricing" className="inline-block text-teal-400 hover:text-teal-300 text-sm font-medium">
                Управление тарифами →
              </Link>
            </div>
          )}
        </section>
      )}

      {/* Период */}
      <div className="flex flex-wrap gap-2 mb-6">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => setPeriodKey(p.key)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
              periodKey === p.key
                ? "bg-teal-500 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Статистика по прогнозам (пока общая; по видам спорта — когда будет API) */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-4">Статистика прогнозов</h2>
        {loading ? (
          <p className="text-slate-500">Загрузка...</p>
        ) : !stats ? (
          <p className="text-rose-400">Не удалось загрузить статистику</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-lg bg-slate-800/80 p-4 text-center">
              <p className="text-2xl font-bold text-white">{stats.total}</p>
              <p className="text-slate-400 text-sm">Дано сигналов</p>
            </div>
            <div className="rounded-lg bg-slate-800/80 p-4 text-center">
              <p className="text-2xl font-bold text-emerald-400">{stats.won}</p>
              <p className="text-slate-400 text-sm">Выиграло</p>
            </div>
            <div className="rounded-lg bg-slate-800/80 p-4 text-center">
              <p className="text-2xl font-bold text-rose-400">{stats.lost}</p>
              <p className="text-slate-400 text-sm">Проиграло</p>
            </div>
            <div className="rounded-lg bg-slate-800/80 p-4 text-center">
              <p className="text-2xl font-bold text-slate-400">{stats.pending}</p>
              <p className="text-slate-400 text-sm">Ожидают</p>
            </div>
          </div>
        )}
        <p className="text-slate-500 text-xs mt-3">
          Сейчас в системе один вид спорта (настольный теннис). Разбивка по видам появится с новыми данными.
        </p>
      </section>

      {/* Призыв: полная аналитика */}
      <section className="rounded-xl border border-teal-500/40 bg-teal-950/30 p-6 mb-6">
        <h2 className="text-lg font-semibold text-white mb-2">Полная аналитика</h2>
        <p className="text-slate-400 text-sm mb-4">
          Доступ к линии, лайв-сетке и углублённой аналитике по матчам. Выберите один вид спорта или все.
        </p>
        <div className="flex flex-wrap gap-3 mb-4">
          <span className="px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 text-sm">1 вид спорта</span>
          <span className="px-3 py-1.5 rounded-lg bg-slate-800 text-slate-300 text-sm">Все виды</span>
          <span className="px-3 py-1.5 rounded-lg bg-slate-700 text-slate-400 text-xs">Тарифы: 1 день · Неделя · 30 дней</span>
        </div>
        <Link
          href="/pricing#analytics"
          className="inline-flex items-center gap-2 rounded-xl bg-teal-500 px-5 py-2.5 font-medium text-white hover:bg-teal-400 transition-all"
        >
          Выбрать тариф
        </Link>
      </section>

      {/* Призыв: сигналы в ТГ / почте */}
      <section className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-2">Сигналы в Telegram или на почту</h2>
        <p className="text-slate-400 text-sm mb-4">
          Получайте прогнозы в реальном времени: в Telegram-бот или на email. Тарифы на 1 день, неделю или 30 дней.
        </p>
        <Link
          href="/pricing#signals"
          className="inline-flex items-center gap-2 rounded-xl bg-amber-500/90 px-5 py-2.5 font-medium text-white hover:bg-amber-400 transition-all"
        >
          Купить доступ к сигналам
        </Link>
      </section>

      {/* Быстрые ссылки */}
      <section>
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">Разделы</h2>
        <div className="flex flex-wrap gap-2">
          <Link href="/sports" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            По видам спорта
          </Link>
          <Link href="/live" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Лайв
          </Link>
          <Link href="/line" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Линия
          </Link>
          <Link href="/stats" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Статистика сигналов
          </Link>
        </div>
      </section>
    </main>
  );
}
