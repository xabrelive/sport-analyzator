"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import StatsCalculator from "@/components/StatsCalculator";
import {
  fetchSignalsStats,
  fetchRecommendationsStats,
  fetchMySignals,
  type SignalStatsResponse,
  type RecommendationStatsResponse,
  type RecommendationResultFilter,
  type MySignalsResponse,
} from "@/lib/api";

const RESULT_FILTERS: { value: RecommendationResultFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "correct", label: "Угадали" },
  { value: "wrong", label: "Не угадали" },
  { value: "pending", label: "Ожидают" },
];

const PER_PAGE_OPTIONS = [10, 20, 50];

type StatsTab = "paid" | "free" | "vip" | "bot" | "calculator";

function formatMatchStart(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function StatsPage() {
  const [stats, setStats] = useState<SignalStatsResponse | null>(null);
  const [recStatsPaid, setRecStatsPaid] = useState<RecommendationStatsResponse | null>(null);
  const [recStatsFree, setRecStatsFree] = useState<RecommendationStatsResponse | null>(null);
  const [recStatsVip, setRecStatsVip] = useState<RecommendationStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [recLoadingPaid, setRecLoadingPaid] = useState(true);
  const [recLoadingFree, setRecLoadingFree] = useState(false);
  const [recLoadingVip, setRecLoadingVip] = useState(false);
  const [activeTab, setActiveTab] = useState<StatsTab>("paid");

  // Параметры платной аналитики (все рекомендации)
  const [paidPage, setPaidPage] = useState(1);
  const [paidPerPage, setPaidPerPage] = useState(20);
  const [paidResultFilter, setPaidResultFilter] = useState<RecommendationResultFilter>("all");
  const [paidOddsMin, setPaidOddsMin] = useState("");
  const [paidOddsMax, setPaidOddsMax] = useState("");
  const [paidDays, setPaidDays] = useState<number | null>(7);
  const [paidDateFrom, setPaidDateFrom] = useState<string>("");
  const [paidDateTo, setPaidDateTo] = useState<string>("");

  // Параметры бесплатной аналитики (бесплатный канал)
  const [freePage, setFreePage] = useState(1);
  const [freePerPage, setFreePerPage] = useState(20);
  const [freeResultFilter, setFreeResultFilter] = useState<RecommendationResultFilter>("all");
  const [freeOddsMin, setFreeOddsMin] = useState("");
  const [freeOddsMax, setFreeOddsMax] = useState("");
  const [freeDaysFilter, setFreeDaysFilter] = useState<number | null>(7);
  const [freeDateFromFilter, setFreeDateFromFilter] = useState<string>("");
  const [freeDateToFilter, setFreeDateToFilter] = useState<string>("");

  // Параметры VIP‑канала
  const [vipPage, setVipPage] = useState(1);
  const [vipPerPage, setVipPerPage] = useState(20);
  const [vipResultFilter, setVipResultFilter] = useState<RecommendationResultFilter>("all");
  const [vipOddsMin, setVipOddsMin] = useState("");
  const [vipOddsMax, setVipOddsMax] = useState("");
  const [vipDaysFilter, setVipDaysFilter] = useState<number | null>(7);
  const [vipDateFromFilter, setVipDateFromFilter] = useState<string>("");
  const [vipDateToFilter, setVipDateToFilter] = useState<string>("");
  const [days, setDays] = useState(7);

  // Сигналы бота для текущего пользователя
  const [mySignals, setMySignals] = useState<MySignalsResponse | null>(null);
  const [mySignalsLoading, setMySignalsLoading] = useState(false);
  const [mySignalsError, setMySignalsError] = useState<string | null>(null);
  const [mySignalsDaysFilter, setMySignalsDaysFilter] = useState<number | null>(7);
  const [mySignalsDateFrom, setMySignalsDateFrom] = useState<string>("");
  const [mySignalsDateTo, setMySignalsDateTo] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    fetchSignalsStats(days)
      .then((d) => { if (!cancelled) setStats(d); })
      .catch(() => { if (!cancelled) setStats(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  // Сигналы от бота (личные сигналы пользователю)
  useEffect(() => {
    if (activeTab !== "bot") return;
    let cancelled = false;
    setMySignalsLoading(true);
    setMySignalsError(null);
    const params: { days?: number; date_from?: string; date_to?: string } = {};
    if (mySignalsDateFrom || mySignalsDateTo) {
      if (mySignalsDateFrom) params.date_from = mySignalsDateFrom;
      if (mySignalsDateTo) params.date_to = mySignalsDateTo;
    } else if (mySignalsDaysFilter != null) {
      params.days = mySignalsDaysFilter;
    }
    fetchMySignals(params)
      .then((d) => {
        if (!cancelled) setMySignals(d);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg =
            (err as Error)?.message === "Failed to fetch my signals"
              ? "Не удалось загрузить сигналы. Возможно, вы не авторизованы."
              : "Не удалось загрузить сигналы.";
          setMySignalsError(msg);
          setMySignals(null);
        }
      })
      .finally(() => {
        if (!cancelled) setMySignalsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, mySignalsDaysFilter, mySignalsDateFrom, mySignalsDateTo]);

  // Загрузка платной аналитики (все рекомендации)
  useEffect(() => {
    if (activeTab !== "paid") return;
    let cancelled = false;
    const oddsMin = paidOddsMin.trim() ? parseFloat(paidOddsMin) : undefined;
    const oddsMax = paidOddsMax.trim() ? parseFloat(paidOddsMax) : undefined;
    if (paidOddsMin.trim() && (Number.isNaN(oddsMin!) || oddsMin! <= 0)) {
      setRecLoadingPaid(false);
      return;
    }
    if (paidOddsMax.trim() && (Number.isNaN(oddsMax!) || oddsMax! <= 0)) {
      setRecLoadingPaid(false);
      return;
    }
    const doFetch = () => {
      fetchRecommendationsStats({
        page: paidPage,
        per_page: paidPerPage,
        result_filter: paidResultFilter,
        odds_min: oddsMin,
        odds_max: oddsMax,
        days: paidDateFrom || paidDateTo ? undefined : paidDays ?? undefined,
        date_from: paidDateFrom || undefined,
        date_to: paidDateTo || undefined,
        channel: "all",
      })
        .then((d) => { if (!cancelled) setRecStatsPaid(d); })
        .catch(() => { if (!cancelled) setRecStatsPaid(null); })
        .finally(() => { if (!cancelled) setRecLoadingPaid(false); });
    };
    setRecLoadingPaid(true);
    doFetch();
    const interval = setInterval(() => {
      if (cancelled) return;
      doFetch();
    }, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [activeTab, paidPage, paidPerPage, paidResultFilter, paidOddsMin, paidOddsMax, paidDays, paidDateFrom, paidDateTo]);

  // Бесплатная аналитика (бесплатный канал)
  useEffect(() => {
    if (activeTab !== "free") return;
    let cancelled = false;
    const oddsMin = freeOddsMin.trim() ? parseFloat(freeOddsMin) : undefined;
    const oddsMax = freeOddsMax.trim() ? parseFloat(freeOddsMax) : undefined;
    if (freeOddsMin.trim() && (Number.isNaN(oddsMin!) || oddsMin! <= 0)) {
      setRecLoadingFree(false);
      return;
    }
    if (freeOddsMax.trim() && (Number.isNaN(oddsMax!) || oddsMax! <= 0)) {
      setRecLoadingFree(false);
      return;
    }
    const doFetch = () => {
      fetchRecommendationsStats({
        page: freePage,
        per_page: freePerPage,
        result_filter: freeResultFilter,
        odds_min: oddsMin,
        odds_max: oddsMax,
        days: freeDateFromFilter || freeDateToFilter ? undefined : freeDaysFilter ?? undefined,
        date_from: freeDateFromFilter || undefined,
        date_to: freeDateToFilter || undefined,
        channel: "free",
      })
        .then((d) => { if (!cancelled) setRecStatsFree(d); })
        .catch(() => { if (!cancelled) setRecStatsFree(null); })
        .finally(() => { if (!cancelled) setRecLoadingFree(false); });
    };
    setRecLoadingFree(true);
    doFetch();
    const interval = setInterval(() => {
      if (cancelled) return;
      doFetch();
    }, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [activeTab, freePage, freePerPage, freeResultFilter, freeOddsMin, freeOddsMax, freeDaysFilter, freeDateFromFilter, freeDateToFilter]);

  // VIP‑канал
  useEffect(() => {
    if (activeTab !== "vip") return;
    let cancelled = false;
    const oddsMin = vipOddsMin.trim() ? parseFloat(vipOddsMin) : undefined;
    const oddsMax = vipOddsMax.trim() ? parseFloat(vipOddsMax) : undefined;
    if (vipOddsMin.trim() && (Number.isNaN(oddsMin!) || oddsMin! <= 0)) {
      setRecLoadingVip(false);
      return;
    }
    if (vipOddsMax.trim() && (Number.isNaN(oddsMax!) || oddsMax! <= 0)) {
      setRecLoadingVip(false);
      return;
    }
    const doFetch = () => {
      fetchRecommendationsStats({
        page: vipPage,
        per_page: vipPerPage,
        result_filter: vipResultFilter,
        odds_min: oddsMin,
        odds_max: oddsMax,
        days: vipDateFromFilter || vipDateToFilter ? undefined : vipDaysFilter ?? undefined,
        date_from: vipDateFromFilter || undefined,
        date_to: vipDateToFilter || undefined,
        channel: "vip",
      })
        .then((d) => { if (!cancelled) setRecStatsVip(d); })
        .catch(() => { if (!cancelled) setRecStatsVip(null); })
        .finally(() => { if (!cancelled) setRecLoadingVip(false); });
    };
    setRecLoadingVip(true);
    doFetch();
    const interval = setInterval(() => {
      if (cancelled) return;
      doFetch();
    }, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [activeTab, vipPage, vipPerPage, vipResultFilter, vipOddsMin, vipOddsMax, vipDaysFilter, vipDateFromFilter, vipDateToFilter]);

  const loadingAny = loading;

  if (loadingAny) {
    return (
      <main className="max-w-6xl mx-auto px-4 py-8">
        <p className="text-slate-400">Загрузка статистики...</p>
      </main>
    );
  }

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-white mb-2">Статистика</h1>
      <p className="text-slate-400 text-sm mb-6">
        Аналитика по бесплатным и платным прогнозам, VIP‑каналу и расчёт банка.
      </p>

      {/* Вкладки */}
      <div className="inline-flex rounded-xl border border-slate-700/80 bg-slate-900/80 p-1 mb-6">
        {[
          { id: "free" as StatsTab, label: "Бесплатная аналитика" },
          { id: "paid" as StatsTab, label: "Платная аналитика" },
          { id: "vip" as StatsTab, label: "VIP‑канал" },
          { id: "bot" as StatsTab, label: "Сигналы от бота" },
          { id: "calculator" as StatsTab, label: "Калькулятор расчёта" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium rounded-lg ${
              activeTab === tab.id
                ? "bg-teal-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Содержимое вкладок */}
      {activeTab === "paid" && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-2">Платная аналитика (все рекомендации)</h2>
          <p className="text-slate-400 text-sm mb-4">
            Все прогнозы из колонки «Рекомендация» (линия и лайв).
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="text-slate-400 text-sm">Период:</span>
            {[
              { label: "Сегодня", type: "today" as const },
              { label: "1 день", type: "1d" as const },
              { label: "7 дней", type: "7d" as const },
              { label: "14 дней", type: "14d" as const },
              { label: "30 дней", type: "30d" as const },
            ].map((btn) => (
              <button
                key={btn.type}
                type="button"
                onClick={() => {
                  const today = new Date().toISOString().slice(0, 10);
                  if (btn.type === "today") {
                    setPaidDateFrom(today);
                    setPaidDateTo(today);
                    setPaidDays(null);
                  } else {
                    const days =
                      btn.type === "1d" ? 1 : btn.type === "7d" ? 7 : btn.type === "14d" ? 14 : 30;
                    setPaidDays(days);
                    setPaidDateFrom("");
                    setPaidDateTo("");
                  }
                  setPaidPage(1);
                }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                {btn.label}
              </button>
            ))}
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Конкретная дата:</span>
              <input
                type="date"
                value={paidDateFrom && paidDateFrom === paidDateTo ? paidDateFrom : ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setPaidDateFrom(v);
                  setPaidDateTo(v);
                  setPaidDays(null);
                  setPaidPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Свой период:</span>
              <input
                type="date"
                value={paidDateFrom}
                onChange={(e) => {
                  setPaidDateFrom(e.target.value);
                  setPaidDays(null);
                  setPaidPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
              <span>—</span>
              <input
                type="date"
                value={paidDateTo}
                onChange={(e) => {
                  setPaidDateTo(e.target.value);
                  setPaidDays(null);
                  setPaidPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
          </div>
          {recLoadingPaid ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : !recStatsPaid ? (
            <p className="text-rose-400 text-sm">Не удалось загрузить</p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 mb-6">
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-white">{recStatsPaid.total}</p>
                  <p className="text-slate-400 text-sm">Рекомендаций выдано</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-emerald-400">{recStatsPaid.correct}</p>
                  <p className="text-slate-400 text-sm">Угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-rose-400">{recStatsPaid.wrong}</p>
                  <p className="text-slate-400 text-sm">Не угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-slate-400">{recStatsPaid.pending}</p>
                  <p className="text-slate-400 text-sm">Ожидают / не оцениваются</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-amber-400/90">
                    {recStatsPaid.cancelled_or_no_data_count ?? 0}
                  </p>
                  <p className="text-slate-400 text-sm">Отменён / нет данных</p>
                  {recStatsPaid.total > 0 && (recStatsPaid.cancelled_or_no_data_pct ?? 0) >= 0 && (
                    <p className="text-slate-500 text-xs mt-0.5">
                      {recStatsPaid.cancelled_or_no_data_pct ?? 0}% от общего
                    </p>
                  )}
                </div>
              </div>
              {recStatsPaid.total > 0 && recStatsPaid.correct + recStatsPaid.wrong > 0 && (
                <p className="text-slate-500 text-sm mb-4">
                  Процент угадывания (из сыгравших): {((recStatsPaid.correct / (recStatsPaid.correct + recStatsPaid.wrong)) * 100).toFixed(1)}%
                </p>
              )}

              <h3 className="text-slate-300 font-medium mb-3">Список рекомендаций</h3>
              <div className="flex flex-wrap items-center gap-4 mb-3">
                <span className="text-slate-400 text-sm">Результат:</span>
                <div className="flex flex-wrap gap-2">
                  {RESULT_FILTERS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => { setPaidResultFilter(value); setPaidPage(1); }}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                        paidResultFilter === value
                          ? "bg-teal-600 text-white"
                          : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="text-slate-400 text-sm">Кф. от</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={paidOddsMin}
                  onChange={(e) => { setPaidOddsMin(e.target.value); setPaidPage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">Кф. до</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={paidOddsMax}
                  onChange={(e) => { setPaidOddsMax(e.target.value); setPaidPage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">На странице:</span>
                <select
                  value={paidPerPage}
                  onChange={(e) => { setPaidPerPage(Number(e.target.value)); setPaidPage(1); }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
                >
                  {PER_PAGE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
              <p className="text-slate-500 text-sm mb-3">
                Показано {recStatsPaid.total_filtered} из {recStatsPaid.total} рекомендаций
                {paidResultFilter !== "all" || paidOddsMin || paidOddsMax ? " (по фильтрам)" : ""}.
              </p>
              {recStatsPaid.items.length === 0 ? (
                <p className="text-slate-500 text-sm">Пока нет сохранённых рекомендаций</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="text-left py-2 pr-2">Лига</th>
                        <th className="text-left py-2 pr-2">Матч</th>
                        <th className="text-left py-2 pr-2">Начало матча</th>
                        <th className="text-left py-2 pr-2">Рекомендация</th>
                        <th className="text-left py-2 pr-2">Кф. при рекомендации</th>
                        <th className="text-left py-2 pr-2">Когда появилась</th>
                        <th className="text-left py-2 pr-2">Добавлена запись</th>
                        <th className="text-left py-2 pr-2">Счёт</th>
                        <th className="text-left py-2">Угадали</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recStatsPaid.items.map((row) => (
                        <tr key={row.match_id} className="border-b border-slate-700/60">
                          <td className="py-2 pr-2 text-slate-400">{row.league_name || "—"}</td>
                          <td className="py-2 pr-2">
                            <Link href={`/match/${row.match_id}`} className="text-teal-400 hover:underline">
                              {row.home_name} — {row.away_name}
                            </Link>
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {formatMatchStart(row.start_time)}
                          </td>
                          <td className="py-2 pr-2 text-slate-300">{row.recommendation_text}</td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.odds_at_recommendation != null ? row.odds_at_recommendation.toFixed(2) : "—"}
                          </td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.minutes_before_start != null ? `за ${row.minutes_before_start} мин до начала` : "—"}
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {row.created_at ? formatMatchStart(row.created_at) : "—"}
                          </td>
                          <td className="py-2 pr-2 text-slate-400 font-mono">{row.final_score ?? "—"}</td>
                          <td className="py-2">
                            {row.correct === true && <span className="text-emerald-400">Да</span>}
                            {row.correct === false && <span className="text-rose-400">Нет</span>}
                            {row.correct === null && <span className="text-slate-500">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {recStatsPaid.total_pages > 0 && (
                <div className="flex flex-wrap items-center gap-4 mt-4 pt-4 border-t border-slate-700">
                  <span className="text-slate-400 text-sm">
                    Страница {recStatsPaid.page} из {recStatsPaid.total_pages}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={recStatsPaid.page <= 1}
                      onClick={() => setPaidPage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Назад
                    </button>
                    <button
                      type="button"
                      disabled={recStatsPaid.page >= recStatsPaid.total_pages}
                      onClick={() => setPaidPage((p) => p + 1)}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Вперёд
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {activeTab === "free" && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-2">Бесплатная аналитика (бесплатный канал)</h2>
          <p className="text-slate-400 text-sm mb-4">
            Прогнозы, отправленные в бесплатный Telegram‑канал.
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="text-slate-400 text-sm">Период:</span>
            {[
              { label: "Сегодня", type: "today" as const },
              { label: "1 день", type: "1d" as const },
              { label: "7 дней", type: "7d" as const },
              { label: "14 дней", type: "14d" as const },
              { label: "30 дней", type: "30d" as const },
            ].map((btn) => (
              <button
                key={btn.type}
                type="button"
                onClick={() => {
                  const today = new Date().toISOString().slice(0, 10);
                  if (btn.type === "today") {
                    setFreeDateFromFilter(today);
                    setFreeDateToFilter(today);
                    setFreeDaysFilter(null);
                  } else {
                    const days =
                      btn.type === "1d" ? 1 : btn.type === "7d" ? 7 : btn.type === "14d" ? 14 : 30;
                    setFreeDaysFilter(days);
                    setFreeDateFromFilter("");
                    setFreeDateToFilter("");
                  }
                  setFreePage(1);
                }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                {btn.label}
              </button>
            ))}
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Дата:</span>
              <input
                type="date"
                value={freeDateFromFilter && freeDateFromFilter === freeDateToFilter ? freeDateFromFilter : ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setFreeDateFromFilter(v);
                  setFreeDateToFilter(v);
                  setFreeDaysFilter(null);
                  setFreePage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Период:</span>
              <input
                type="date"
                value={freeDateFromFilter}
                onChange={(e) => {
                  setFreeDateFromFilter(e.target.value);
                  setFreeDaysFilter(null);
                  setFreePage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
              <span>—</span>
              <input
                type="date"
                value={freeDateToFilter}
                onChange={(e) => {
                  setFreeDateToFilter(e.target.value);
                  setFreeDaysFilter(null);
                  setFreePage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
          </div>
          {recLoadingFree ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : !recStatsFree ? (
            <p className="text-rose-400 text-sm">Не удалось загрузить</p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 mb-6">
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-white">{recStatsFree.total}</p>
                  <p className="text-slate-400 text-sm">Всего прогнозов</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-emerald-400">{recStatsFree.correct}</p>
                  <p className="text-slate-400 text-sm">Угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-rose-400">{recStatsFree.wrong}</p>
                  <p className="text-slate-400 text-sm">Не угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-slate-400">{recStatsFree.pending}</p>
                  <p className="text-slate-400 text-sm">Ещё в игре / не оценивается</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-amber-400/90">
                    {recStatsFree.cancelled_or_no_data_count ?? 0}
                  </p>
                  <p className="text-slate-400 text-sm">Отмена / нет данных</p>
                </div>
              </div>
              {recStatsFree.total > 0 && recStatsFree.correct + recStatsFree.wrong > 0 && (
                <p className="text-slate-500 text-sm mb-4">
                  Процент угадывания (из сыгравших): {((recStatsFree.correct / (recStatsFree.correct + recStatsFree.wrong)) * 100).toFixed(1)}%
                </p>
              )}
              <h3 className="text-slate-300 font-medium mb-3">Список прогнозов бесплатного канала</h3>
              <div className="flex flex-wrap items-center gap-4 mb-3">
                <span className="text-slate-400 text-sm">Результат:</span>
                <div className="flex flex-wrap gap-2">
                  {RESULT_FILTERS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => { setFreeResultFilter(value); setFreePage(1); }}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                        freeResultFilter === value
                          ? "bg-teal-600 text-white"
                          : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="text-slate-400 text-sm">Кф. от</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={freeOddsMin}
                  onChange={(e) => { setFreeOddsMin(e.target.value); setFreePage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">Кф. до</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={freeOddsMax}
                  onChange={(e) => { setFreeOddsMax(e.target.value); setFreePage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">На странице:</span>
                <select
                  value={freePerPage}
                  onChange={(e) => { setFreePerPage(Number(e.target.value)); setFreePage(1); }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
                >
                  {PER_PAGE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
              <p className="text-slate-500 text-sm mb-3">
                Показано {recStatsFree.total_filtered} из {recStatsFree.total} рекомендаций
                {freeResultFilter !== "all" || freeOddsMin || freeOddsMax ? " (по фильтрам)" : ""}.
              </p>
              {recStatsFree.items.length === 0 ? (
                <p className="text-slate-500 text-sm">Пока нет прогнозов для выбранного периода</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="text-left py-2 pr-2">Лига</th>
                        <th className="text-left py-2 pr-2">Матч</th>
                        <th className="text-left py-2 pr-2">Начало матча</th>
                        <th className="text-left py-2 pr-2">Рекомендация</th>
                        <th className="text-left py-2 pr-2">Кф. при рекомендации</th>
                        <th className="text-left py-2 pr-2">Счёт</th>
                        <th className="text-left py-2">Угадали</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recStatsFree.items.map((row) => (
                        <tr key={row.match_id} className="border-b border-slate-700/60">
                          <td className="py-2 pr-2 text-slate-400">{row.league_name || "—"}</td>
                          <td className="py-2 pr-2">
                            <Link href={`/match/${row.match_id}`} className="text-teal-400 hover:underline">
                              {row.home_name} — {row.away_name}
                            </Link>
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {formatMatchStart(row.start_time)}
                          </td>
                          <td className="py-2 pr-2 text-slate-300">{row.recommendation_text}</td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.odds_at_recommendation != null ? row.odds_at_recommendation.toFixed(2) : "—"}
                          </td>
                          <td className="py-2 pr-2 text-slate-400 font-mono">{row.final_score ?? "—"}</td>
                          <td className="py-2">
                            {row.correct === true && <span className="text-emerald-400">Да</span>}
                            {row.correct === false && <span className="text-rose-400">Нет</span>}
                            {row.correct === null && <span className="text-slate-500">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {recStatsFree.total_pages > 0 && (
                <div className="flex flex-wrap items-center gap-4 mt-4 pt-4 border-t border-slate-700">
                  <span className="text-slate-400 text-sm">
                    Страница {recStatsFree.page} из {recStatsFree.total_pages}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={recStatsFree.page <= 1}
                      onClick={() => setFreePage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Назад
                    </button>
                    <button
                      type="button"
                      disabled={recStatsFree.page >= recStatsFree.total_pages}
                      onClick={() => setFreePage((p) => p + 1)}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Вперёд
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {activeTab === "vip" && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-2">VIP‑канал</h2>
          <p className="text-slate-400 text-sm mb-4">
            Прогнозы, отправленные в VIP Telegram‑канал.
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="text-slate-400 text-sm">Период:</span>
            {[
              { label: "Сегодня", type: "today" as const },
              { label: "1 день", type: "1d" as const },
              { label: "7 дней", type: "7d" as const },
              { label: "14 дней", type: "14d" as const },
              { label: "30 дней", type: "30d" as const },
            ].map((btn) => (
              <button
                key={btn.type}
                type="button"
                onClick={() => {
                  const today = new Date().toISOString().slice(0, 10);
                  if (btn.type === "today") {
                    setVipDateFromFilter(today);
                    setVipDateToFilter(today);
                    setVipDaysFilter(null);
                  } else {
                    const days =
                      btn.type === "1d" ? 1 : btn.type === "7d" ? 7 : btn.type === "14d" ? 14 : 30;
                    setVipDaysFilter(days);
                    setVipDateFromFilter("");
                    setVipDateToFilter("");
                  }
                  setVipPage(1);
                }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                {btn.label}
              </button>
            ))}
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Дата:</span>
              <input
                type="date"
                value={vipDateFromFilter && vipDateFromFilter === vipDateToFilter ? vipDateFromFilter : ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setVipDateFromFilter(v);
                  setVipDateToFilter(v);
                  setVipDaysFilter(null);
                  setVipPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Период:</span>
              <input
                type="date"
                value={vipDateFromFilter}
                onChange={(e) => {
                  setVipDateFromFilter(e.target.value);
                  setVipDaysFilter(null);
                  setVipPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
              <span>—</span>
              <input
                type="date"
                value={vipDateToFilter}
                onChange={(e) => {
                  setVipDateToFilter(e.target.value);
                  setVipDaysFilter(null);
                  setVipPage(1);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
          </div>
          {recLoadingVip ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : !recStatsVip ? (
            <p className="text-rose-400 text-sm">Не удалось загрузить</p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-6 gap-4 mb-6">
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-white">{recStatsVip.total}</p>
                  <p className="text-slate-400 text-sm">Всего прогнозов</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-emerald-400">{recStatsVip.correct}</p>
                  <p className="text-slate-400 text-sm">Угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-rose-400">{recStatsVip.wrong}</p>
                  <p className="text-slate-400 text-sm">Не угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-slate-400">{recStatsVip.pending}</p>
                  <p className="text-slate-400 text-sm">Ещё в игре / не оценивается</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-amber-400/90">
                    {recStatsVip.cancelled_or_no_data_count ?? 0}
                  </p>
                  <p className="text-slate-400 text-sm">Отмена / нет данных</p>
                </div>
              </div>
              {/* Аналогичная таблица для VIP‑канала может быть добавлена по тем же правилам */}
              <h3 className="text-slate-300 font-medium mb-3">Список прогнозов VIP‑канала</h3>
              <div className="flex flex-wrap items-center gap-4 mb-3">
                <span className="text-slate-400 text-sm">Результат:</span>
                <div className="flex flex-wrap gap-2">
                  {RESULT_FILTERS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => { setVipResultFilter(value); setVipPage(1); }}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                        vipResultFilter === value
                          ? "bg-teal-600 text-white"
                          : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <span className="text-slate-400 text-sm">Кф. от</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={vipOddsMin}
                  onChange={(e) => { setVipOddsMin(e.target.value); setVipPage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">Кф. до</span>
                <input
                  type="number"
                  min={1}
                  step={0.01}
                  placeholder="—"
                  value={vipOddsMax}
                  onChange={(e) => { setVipOddsMax(e.target.value); setVipPage(1); }}
                  className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
                />
                <span className="text-slate-400 text-sm">На странице:</span>
                <select
                  value={vipPerPage}
                  onChange={(e) => { setVipPerPage(Number(e.target.value)); setVipPage(1); }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
                >
                  {PER_PAGE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </div>
              <p className="text-slate-500 text-sm mb-3">
                Показано {recStatsVip.total_filtered} из {recStatsVip.total} рекомендаций
                {vipResultFilter !== "all" || vipOddsMin || vipOddsMax ? " (по фильтрам)" : ""}.
              </p>
              {recStatsVip.items.length === 0 ? (
                <p className="text-slate-500 text-sm">Пока нет прогнозов для выбранного периода</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="text-left py-2 pr-2">Лига</th>
                        <th className="text-left py-2 pr-2">Матч</th>
                        <th className="text-left py-2 pr-2">Начало матча</th>
                        <th className="text-left py-2 pr-2">Рекомендация</th>
                        <th className="text-left py-2 pr-2">Кф. при рекомендации</th>
                        <th className="text-left py-2 pr-2">Счёт</th>
                        <th className="text-left py-2">Угадали</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recStatsVip.items.map((row) => (
                        <tr key={row.match_id} className="border-b border-slate-700/60">
                          <td className="py-2 pr-2 text-slate-400">{row.league_name || "—"}</td>
                          <td className="py-2 pr-2">
                            <Link href={`/match/${row.match_id}`} className="text-teal-400 hover:underline">
                              {row.home_name} — {row.away_name}
                            </Link>
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {formatMatchStart(row.start_time)}
                          </td>
                          <td className="py-2 pr-2 text-slate-300">{row.recommendation_text}</td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.odds_at_recommendation != null ? row.odds_at_recommendation.toFixed(2) : "—"}
                          </td>
                          <td className="py-2 pr-2 text-slate-400 font-mono">{row.final_score ?? "—"}</td>
                          <td className="py-2">
                            {row.correct === true && <span className="text-emerald-400">Да</span>}
                            {row.correct === false && <span className="text-rose-400">Нет</span>}
                            {row.correct === null && <span className="text-slate-500">—</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {recStatsVip.total_pages > 0 && (
                <div className="flex flex-wrap items-center gap-4 mt-4 pt-4 border-t border-slate-700">
                  <span className="text-slate-400 text-sm">
                    Страница {recStatsVip.page} из {recStatsVip.total_pages}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={recStatsVip.page <= 1}
                      onClick={() => setVipPage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Назад
                    </button>
                    <button
                      type="button"
                      disabled={recStatsVip.page >= recStatsVip.total_pages}
                      onClick={() => setVipPage((p) => p + 1)}
                      className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Вперёд
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {activeTab === "bot" && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
          <h2 className="text-lg font-semibold text-white mb-2">Сигналы от бота</h2>
          <p className="text-slate-400 text-sm mb-4">
            Статистика личных сигналов, которые бот отправлял вам в Telegram и/или на почту.
          </p>

          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span className="text-slate-400 text-sm">Период:</span>
            {[
              { label: "Сегодня", type: "today" as const },
              { label: "1 день", type: "1d" as const },
              { label: "7 дней", type: "7d" as const },
              { label: "14 дней", type: "14d" as const },
              { label: "30 дней", type: "30d" as const },
            ].map((btn) => (
              <button
                key={btn.type}
                type="button"
                onClick={() => {
                  const today = new Date().toISOString().slice(0, 10);
                  if (btn.type === "today") {
                    setMySignalsDateFrom(today);
                    setMySignalsDateTo(today);
                    setMySignalsDaysFilter(null);
                  } else {
                    const d =
                      btn.type === "1d" ? 1 : btn.type === "7d" ? 7 : btn.type === "14d" ? 14 : 30;
                    setMySignalsDaysFilter(d);
                    setMySignalsDateFrom("");
                    setMySignalsDateTo("");
                  }
                }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                {btn.label}
              </button>
            ))}
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Конкретная дата:</span>
              <input
                type="date"
                value={
                  mySignalsDateFrom && mySignalsDateFrom === mySignalsDateTo ? mySignalsDateFrom : ""
                }
                onChange={(e) => {
                  const v = e.target.value;
                  setMySignalsDateFrom(v);
                  setMySignalsDateTo(v);
                  setMySignalsDaysFilter(null);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
            <div className="flex items-center gap-2 text-slate-400 text-xs">
              <span>Свой период:</span>
              <input
                type="date"
                value={mySignalsDateFrom}
                onChange={(e) => {
                  setMySignalsDateFrom(e.target.value);
                  setMySignalsDaysFilter(null);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
              <span>—</span>
              <input
                type="date"
                value={mySignalsDateTo}
                onChange={(e) => {
                  setMySignalsDateTo(e.target.value);
                  setMySignalsDaysFilter(null);
                }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
              />
            </div>
          </div>

          {mySignalsLoading ? (
            <p className="text-slate-500 text-sm">Загрузка сигналов…</p>
          ) : mySignalsError ? (
            <p className="text-rose-400 text-sm">{mySignalsError}</p>
          ) : !mySignals ? (
            <p className="text-slate-500 text-sm">
              За выбранный период нет данных по сигналам или требуется авторизация.
            </p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-white">{mySignals.total}</p>
                  <p className="text-slate-400 text-sm">Всего сигналов</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-emerald-400">{mySignals.won}</p>
                  <p className="text-slate-400 text-sm">Угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-rose-400">{mySignals.lost}</p>
                  <p className="text-slate-400 text-sm">Не угадали</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-slate-400">{mySignals.pending}</p>
                  <p className="text-slate-400 text-sm">Ожидают / отменены</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                  <p className="text-2xl font-bold text-sky-400">
                    {mySignals.items.filter((it) => it.sent_via === "telegram").length} /{" "}
                    {mySignals.items.filter((it) => it.sent_via === "email").length}
                  </p>
                  <p className="text-slate-400 text-sm">TG / Email</p>
                </div>
              </div>

              <h3 className="text-slate-300 font-medium mb-3">Список сигналов</h3>
              {mySignals.items.length === 0 ? (
                <p className="text-slate-500 text-sm">
                  За выбранный период сигналы бота вам не отправлялись — возможно, в это время у вас
                  не было активной подписки на сигналы.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="text-left py-2 pr-2">Лига</th>
                        <th className="text-left py-2 pr-2">Матч</th>
                        <th className="text-left py-2 pr-2 whitespace-nowrap">Начало матча</th>
                        <th className="text-left py-2 pr-2">Прогноз</th>
                        <th className="text-left py-2 pr-2">Кф. при сигнале</th>
                        <th className="text-left py-2 pr-2">Исход</th>
                        <th className="text-left py-2 pr-2 whitespace-nowrap">Отправлен</th>
                        <th className="text-left py-2 pr-2">Канал</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mySignals.items.map((row) => (
                        <tr key={`${row.match_id}-${row.sent_at}`} className="border-b border-slate-700/60">
                          <td className="py-2 pr-2 text-slate-400">{row.league_name || "—"}</td>
                          <td className="py-2 pr-2">
                            <Link href={`/match/${row.match_id}`} className="text-teal-400 hover:underline">
                              {row.home_name} — {row.away_name}
                            </Link>
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {formatMatchStart(row.start_time)}
                          </td>
                          <td className="py-2 pr-2 text-slate-300">{row.recommendation_text}</td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.odds_at_recommendation != null
                              ? row.odds_at_recommendation.toFixed(2)
                              : "—"}
                          </td>
                          <td className="py-2 pr-2">
                            {row.outcome === "won" && <span className="text-emerald-400">Угадали</span>}
                            {row.outcome === "lost" && <span className="text-rose-400">Не угадали</span>}
                            {row.outcome === "pending" && (
                              <span className="text-slate-500">Ожидает / отменён / без данных</span>
                            )}
                          </td>
                          <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                            {formatMatchStart(row.sent_at)}
                          </td>
                          <td className="py-2 pr-2 text-slate-400">
                            {row.sent_via === "telegram"
                              ? "Telegram"
                              : row.sent_via === "email"
                              ? "Email"
                              : row.sent_via}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {activeTab === "calculator" && <StatsCalculator />}

      {/* Блок статистики по каналам убран по требованию */}
    </main>
  );
}
