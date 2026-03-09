"use client";

import { useEffect, useMemo, useState } from "react";
import {
  fetchRecommendationsStats,
  fetchMySignals,
  type RecommendationStatsItem,
  type RecommendationChannelFilter,
} from "@/lib/api";

type CalcItem = RecommendationStatsItem & { selected: boolean };

type CalcChannel = "all" | "free" | "vip" | "signals";

const CALC_PER_PAGE_OPTIONS = [20, 50, 100];

function formatMatchStart(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

async function loadAllRecommendations(params: {
  channel: RecommendationChannelFilter;
  days?: number;
  date_from?: string;
  date_to?: string;
}): Promise<RecommendationStatsItem[]> {
  const base = {
    result_filter: "all" as const,
    odds_min: undefined as number | undefined,
    odds_max: undefined as number | undefined,
    channel: params.channel,
    days: params.date_from || params.date_to ? undefined : params.days,
    date_from: params.date_from,
    date_to: params.date_to,
  };

  const perPage = 100;
  const first = await fetchRecommendationsStats({
    ...base,
    page: 1,
    per_page: perPage,
  });

  const items: RecommendationStatsItem[] = [...(first.items || [])];
  const totalPages = first.total_pages || 0;

  if (totalPages <= 1) {
    return items;
  }

  for (let page = 2; page <= totalPages; page++) {
    const resp = await fetchRecommendationsStats({
      ...base,
      page,
      per_page: perPage,
    });
    if (resp.items?.length) {
      items.push(...resp.items);
    }
  }

  return items;
}

export default function StatsCalculator() {
  const [channel, setChannel] = useState<CalcChannel>("all");
  const [days, setDays] = useState<number | null>(30);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  const [stake, setStake] = useState<string>("100");
  const [initialBank, setInitialBank] = useState<string>("10000");

  const [items, setItems] = useState<CalcItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);

  // Загружаем все рекомендации для выбранного типа аналитики и периода (без лимита по количеству).
  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      setPage(1);
      try {
        if (channel === "signals") {
          const params: { days?: number; date_from?: string; date_to?: string } = {};
          if (dateFrom || dateTo) {
            if (dateFrom) params.date_from = dateFrom;
            if (dateTo) params.date_to = dateTo;
          } else if (days != null) {
            params.days = days;
          }
          const resp = await fetchMySignals(params);
          if (cancelled) return;
          const mapped: CalcItem[] = (resp.items || []).map((it) => {
            const outcome = it.outcome;
            const correct =
              outcome === "won" ? true : outcome === "lost" ? false : null;
            return {
              match_id: it.match_id,
              league_name: it.league_name,
              start_time: it.start_time,
              started_at: null,
              home_name: it.home_name,
              away_name: it.away_name,
              recommendation_text: it.recommendation_text,
              final_score: null,
              winner_name: null,
              correct,
              odds_at_recommendation: it.odds_at_recommendation,
              minutes_before_start: null,
              created_at: it.sent_at,
              selected: correct !== null && it.odds_at_recommendation != null,
            };
          });
          setItems(mapped);
        } else {
          const data = await loadAllRecommendations({
            channel: channel as RecommendationChannelFilter,
            days: dateFrom || dateTo ? undefined : days ?? undefined,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
          });
          if (cancelled) return;
          const mapped: CalcItem[] = (data || []).map((it) => ({
            ...it,
            selected: it.correct !== null && it.odds_at_recommendation != null,
          }));
          setItems(mapped);
        }
      } catch {
        if (!cancelled) setError("Не удалось загрузить список прогнозов");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [channel, days, dateFrom, dateTo]);

  const stakeNum = useMemo(() => {
    const v = parseFloat(stake.replace(",", "."));
    return Number.isFinite(v) && v > 0 ? v : 0;
  }, [stake]);

  const initialBankNum = useMemo(() => {
    const v = parseFloat(initialBank.replace(",", "."));
    return Number.isFinite(v) && v >= 0 ? v : 0;
  }, [initialBank]);

  const calc = useMemo(() => {
    let bank = initialBankNum;
    let used = 0;
    let wins = 0;
    let losses = 0;

    if (stakeNum <= 0 || items.length === 0) {
      return { bankStart: initialBankNum, bankFinal: bank, profit: 0, used, wins, losses };
    }

    for (const it of items) {
      if (!it.selected) continue;
      if (it.correct === true && it.odds_at_recommendation != null) {
        used += stakeNum;
        wins += 1;
        bank += stakeNum * (it.odds_at_recommendation - 1);
      } else if (it.correct === false) {
        used += stakeNum;
        losses += 1;
        bank -= stakeNum;
      }
    }

    return {
      bankStart: initialBankNum,
      bankFinal: bank,
      profit: bank - initialBankNum,
      used,
      wins,
      losses,
    };
  }, [items, stakeNum, initialBankNum]);

  const toggleAll = (value: boolean) => {
    setItems((prev) => prev.map((it) => ({ ...it, selected: value })));
  };

  const totalPages = Math.max(1, Math.ceil(items.length / perPage));
  const currentPage = Math.min(page, totalPages);
  const pageItems = useMemo(
    () => items.slice((currentPage - 1) * perPage, currentPage * perPage),
    [items, currentPage, perPage],
  );

  const handlePresetPeriod = (preset: "today" | 1 | 7 | 14 | 30) => {
    const today = new Date().toISOString().slice(0, 10);
    if (preset === "today") {
      setDateFrom(today);
      setDateTo(today);
      setDays(null);
    } else {
      setDays(preset);
      setDateFrom("");
      setDateTo("");
    }
  };

  const todayIso = new Date().toISOString().slice(0, 10);
  const isTodayActive = !days && dateFrom === todayIso && dateTo === todayIso;
  const isDaysActive = (d: number) => !dateFrom && !dateTo && days === d;

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Калькулятор ставок</h2>
      </div>
      <p className="text-slate-400 text-sm mb-4">
        Считает результат условной фиксированной ставки по всем прогнозам за выбранный
        период для бесплатной аналитики, платной аналитики, VIP‑канала или сигналов бота.
      </p>

      <>
          <div className="flex flex-wrap items-center gap-4 mb-4">
            <div className="inline-flex rounded-lg bg-slate-800 p-1">
              <button
                type="button"
                onClick={() => setChannel("free")}
                className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md ${
                  channel === "free" ? "bg-teal-600 text-white" : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                Бесплатная аналитика
              </button>
              <button
                type="button"
                onClick={() => setChannel("all")}
                className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md ${
                  channel === "all" ? "bg-teal-600 text-white" : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                Платная аналитика
              </button>
              <button
                type="button"
                onClick={() => setChannel("vip")}
                className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md ${
                  channel === "vip" ? "bg-teal-600 text-white" : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                VIP‑канал
              </button>
              <button
                type="button"
                onClick={() => setChannel("signals")}
                className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md ${
                  channel === "signals" ? "bg-teal-600 text-white" : "text-slate-300 hover:bg-slate-700"
                }`}
              >
                Сигналы бота
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs sm:text-sm">
              <span className="text-slate-400">Период:</span>
              <button
                type="button"
                onClick={() => handlePresetPeriod("today")}
                className={`px-3 py-1.5 rounded-lg ${
                  isTodayActive
                    ? "bg-emerald-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                Сегодня
              </button>
              {[1, 7, 14, 30].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => handlePresetPeriod(d as 1 | 7 | 14 | 30)}
                  className={`px-3 py-1.5 rounded-lg ${
                    isDaysActive(d)
                      ? "bg-emerald-600 text-white"
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                  }`}
                >
                  {d === 1 ? "1 день" : `${d} дней`}
                </button>
              ))}
              <div className="flex items-center gap-1">
                <span className="text-slate-400">Дата:</span>
                <input
                  type="date"
                  value={dateFrom && dateFrom === dateTo ? dateFrom : ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDateFrom(v);
                    setDateTo(v);
                    setDays(null);
                  }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
                />
              </div>
              <div className="flex items-center gap-1">
                <span className="text-slate-400">Период:</span>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => {
                    setDateFrom(e.target.value);
                    setDays(null);
                  }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
                />
                <span className="text-slate-400">—</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => {
                    setDateTo(e.target.value);
                    setDays(null);
                  }}
                  className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
                />
              </div>
            </div>
          </div>

          <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 sm:p-6 mb-6">
            <div className="flex flex-wrap items-center gap-4 mb-4">
              <div>
                <p className="text-slate-400 text-xs mb-1">Начальный банк, ₽</p>
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={initialBank}
                  onChange={(e) => setInitialBank(e.target.value)}
                  className="w-32 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
                />
              </div>

              <div>
                <p className="text-slate-400 text-xs mb-1">Ставка на каждый прогноз, ₽</p>
                <input
                  type="number"
                  min={0}
                  step={10}
                  value={stake}
                  onChange={(e) => setStake(e.target.value)}
                  className="w-32 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
                />
              </div>

              <div className="ml-auto flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => toggleAll(true)}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-200 hover:bg-slate-700"
                >
                  Отметить все
                </button>
                <button
                  type="button"
                  onClick={() => toggleAll(false)}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-200 hover:bg-slate-700"
                >
                  Снять всё
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-lg bg-slate-800/80 p-4">
                <p className="text-slate-400 text-xs mb-1">Начальный банк</p>
                <p className="text-xl font-semibold text-white">
                  {calc.bankStart.toFixed(0)} ₽
                </p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4">
                <p className="text-slate-400 text-xs mb-1">Итоговый банк</p>
                <p className="text-xl font-semibold text-white">
                  {calc.bankFinal.toFixed(0)} ₽
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Ставок учтено: {calc.wins + calc.losses}, сумма ставок: {calc.used.toFixed(0)} ₽
                </p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4">
                <p className="text-slate-400 text-xs mb-1">Результат</p>
                <p
                  className={`text-xl font-semibold ${
                    calc.profit > 0
                      ? "text-emerald-400"
                      : calc.profit < 0
                      ? "text-rose-400"
                      : "text-slate-300"
                  }`}
                >
                  {calc.profit >= 0 ? "+" : ""}
                  {calc.profit.toFixed(0)} ₽
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Выиграло: {calc.wins}, проиграло: {calc.losses}
                </p>
              </div>
            </div>
          </section>

          <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 sm:p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm sm:text-lg font-semibold text-white">
                Список прогнозов для расчёта
              </h3>
              <span className="text-slate-500 text-xs">
                Всего прогнозов: {items.length}
              </span>
            </div>
            {loading ? (
              <p className="text-slate-500 text-sm">Загрузка прогнозов…</p>
            ) : error ? (
              <p className="text-rose-400 text-sm">{error}</p>
            ) : items.length === 0 ? (
              <p className="text-slate-500 text-sm">
                {channel === "signals"
                  ? "За выбранный период сигналы бота вам не отправлялись."
                  : "За выбранный период нет сохранённых рекомендаций."}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-3 mb-3 text-xs sm:text-sm">
                  <span className="text-slate-400">На странице:</span>
                  <select
                    value={perPage}
                    onChange={(e) => {
                      setPerPage(Number(e.target.value));
                      setPage(1);
                    }}
                    className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-xs text-white"
                  >
                    {CALC_PER_PAGE_OPTIONS.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                  <span className="text-slate-500">
                    Страница {currentPage} из {totalPages}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs sm:text-sm">
                    <thead>
                      <tr className="text-slate-400 border-b border-slate-700">
                        <th className="py-2 pr-2">
                          <span className="sr-only">В расчёт</span>
                        </th>
                        <th className="text-left py-2 pr-2">Лига</th>
                        <th className="text-left py-2 pr-2">Матч</th>
                        <th className="text-left py-2 pr-2 whitespace-nowrap">
                          Начало матча
                        </th>
                        <th className="text-left py-2 pr-2">Рекомендация</th>
                        <th className="text-left py-2 pr-2 whitespace-nowrap">
                          Кф. при рекомендации
                        </th>
                        <th className="text-left py-2 pr-2">Счёт</th>
                        <th className="text-left py-2 pr-2">Исход</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageItems.map((row, idx) => {
                        const globalIndex = (currentPage - 1) * perPage + idx;
                        return (
                          <tr
                            key={`${row.match_id}-${row.created_at ?? globalIndex}`}
                            className="border-b border-slate-700/60"
                          >
                            <td className="py-2 pr-2 text-center">
                              <input
                                type="checkbox"
                                checked={row.selected}
                                onChange={() =>
                                  setItems((prev) =>
                                    prev.map((it, i) =>
                                      i === globalIndex
                                        ? { ...it, selected: !it.selected }
                                        : it,
                                    ),
                                  )
                                }
                                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
                              />
                            </td>
                            <td className="py-2 pr-2 text-slate-400">
                              {row.league_name || "—"}
                            </td>
                            <td className="py-2 pr-2 text-slate-200">
                              {row.home_name} — {row.away_name}
                            </td>
                            <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                              {formatMatchStart(row.start_time)}
                            </td>
                            <td className="py-2 pr-2 text-slate-300">
                              {row.recommendation_text}
                            </td>
                            <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                              {row.odds_at_recommendation != null
                                ? row.odds_at_recommendation.toFixed(2)
                                : "—"}
                            </td>
                            <td className="py-2 pr-2 text-slate-400 font-mono">
                              {row.final_score ?? "—"}
                            </td>
                            <td className="py-2 pr-2">
                              {row.correct === true && (
                                <span className="text-emerald-400">Угадали</span>
                              )}
                              {row.correct === false && (
                                <span className="text-rose-400">Не угадали</span>
                              )}
                              {row.correct === null && (
                                <span className="text-slate-500">
                                  Ожидает / не оценивается
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {totalPages > 1 && (
                  <div className="flex flex-wrap items-center gap-4 mt-4 pt-4 border-t border-slate-700">
                    <button
                      type="button"
                      disabled={currentPage <= 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Назад
                    </button>
                    <button
                      type="button"
                      disabled={currentPage >= totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      className="px-3 py-1.5 rounded-lg text-xs sm:text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Вперёд
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </>
    </section>
  );
}

