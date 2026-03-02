"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchSignalsStats, fetchRecommendationsStats, type SignalStatsResponse, type RecommendationStatsResponse, type RecommendationResultFilter } from "@/lib/api";

const RESULT_FILTERS: { value: RecommendationResultFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "correct", label: "Угадали" },
  { value: "wrong", label: "Не угадали" },
  { value: "pending", label: "Ожидают" },
];

const PER_PAGE_OPTIONS = [10, 20, 50];

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
  const [recStats, setRecStats] = useState<RecommendationStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [recLoading, setRecLoading] = useState(true);
  const [recPage, setRecPage] = useState(1);
  const [recPerPage, setRecPerPage] = useState(20);
  const [recResultFilter, setRecResultFilter] = useState<RecommendationResultFilter>("all");
  const [recOddsMin, setRecOddsMin] = useState("");
  const [recOddsMax, setRecOddsMax] = useState("");
  const [days, setDays] = useState(7);

  useEffect(() => {
    let cancelled = false;
    fetchSignalsStats(days)
      .then((d) => { if (!cancelled) setStats(d); })
      .catch(() => { if (!cancelled) setStats(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days]);

  useEffect(() => {
    let cancelled = false;
    const oddsMin = recOddsMin.trim() ? parseFloat(recOddsMin) : undefined;
    const oddsMax = recOddsMax.trim() ? parseFloat(recOddsMax) : undefined;
    if (recOddsMin.trim() && (Number.isNaN(oddsMin!) || oddsMin! <= 0)) {
      setRecLoading(false);
      return;
    }
    if (recOddsMax.trim() && (Number.isNaN(oddsMax!) || oddsMax! <= 0)) {
      setRecLoading(false);
      return;
    }
    const doFetch = () => {
      fetchRecommendationsStats({
        page: recPage,
        per_page: recPerPage,
        result_filter: recResultFilter,
        odds_min: oddsMin,
        odds_max: oddsMax,
      })
        .then((d) => { if (!cancelled) setRecStats(d); })
        .catch(() => { if (!cancelled) setRecStats(null); })
        .finally(() => { if (!cancelled) setRecLoading(false); });
    };
    setRecLoading(true);
    doFetch();
    const interval = setInterval(() => {
      if (cancelled) return;
      doFetch();
    }, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [recPage, recPerPage, recResultFilter, recOddsMin, recOddsMax]);

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
      <h1 className="text-2xl font-bold text-white mb-2">Статистика сигналов</h1>
      <p className="text-slate-400 text-sm mb-6">
        Сколько сигналов выдано, сколько сыграло (угадано) и сколько не сыграло. Данные только для информации — мы предоставляем аналитику, а не рекомендации к ставкам.
      </p>

      <div className="flex flex-wrap gap-2 mb-6">
        {[1, 7, 14, 30].map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setDays(d)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${
              days === d
                ? "bg-emerald-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {d === 1 ? "1 день" : `${d} дней`}
          </button>
        ))}
      </div>

      {!stats ? (
        <p className="text-rose-400">Не удалось загрузить статистику</p>
      ) : (
        <>
          <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
            <h2 className="text-lg font-semibold text-white mb-4">Всего</h2>
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
            {stats.total > 0 && stats.won + stats.lost > 0 && (
              <p className="text-slate-500 text-sm mt-3">
                Процент угадывания (из сыгравших): {((stats.won / (stats.won + stats.lost)) * 100).toFixed(1)}%
              </p>
            )}
          </section>

          <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
            <h2 className="text-lg font-semibold text-white mb-4">По дням</h2>
            {stats.by_day.length === 0 ? (
              <p className="text-slate-500 text-sm">За выбранный период сигналов пока нет</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-slate-400 border-b border-slate-700">
                      <th className="text-left py-2">Дата</th>
                      <th className="text-right py-2">Дано</th>
                      <th className="text-right py-2">Выиграло</th>
                      <th className="text-right py-2">Проиграло</th>
                      <th className="text-right py-2">Ожидают</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.by_day.map((row) => (
                      <tr key={row.date} className="border-b border-slate-700/60">
                        <td className="py-2 text-white">{row.date}</td>
                        <td className="text-right py-2 text-slate-300">{row.total}</td>
                        <td className="text-right py-2 text-emerald-400">{row.won}</td>
                        <td className="text-right py-2 text-rose-400">{row.lost}</td>
                        <td className="text-right py-2 text-slate-500">{row.pending}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mt-8">
        <h2 className="text-lg font-semibold text-white mb-2">Статистика рекомендаций (линия/лайв)</h2>
        <p className="text-slate-400 text-sm mb-4">
          Учитываются все рекомендации из колонки «Рекомендация» в таблице линии и лайва. Угадали/не угадали считается для рекомендаций на победителя (П1/П2 в матче или по сетам). Тоталы (ТБ/ТМ), фора и т.п. пока в «ожидают».
        </p>
        {recLoading ? (
          <p className="text-slate-500 text-sm">Загрузка...</p>
        ) : !recStats ? (
          <p className="text-rose-400 text-sm">Не удалось загрузить</p>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
              <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                <p className="text-2xl font-bold text-white">{recStats.total}</p>
                <p className="text-slate-400 text-sm">Рекомендаций выдано</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                <p className="text-2xl font-bold text-emerald-400">{recStats.correct}</p>
                <p className="text-slate-400 text-sm">Угадали</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                <p className="text-2xl font-bold text-rose-400">{recStats.wrong}</p>
                <p className="text-slate-400 text-sm">Не угадали</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                <p className="text-2xl font-bold text-slate-400">{recStats.pending}</p>
                <p className="text-slate-400 text-sm">Ожидают / не оцениваются</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-4 text-center">
                <p className="text-2xl font-bold text-amber-400/90">
                  {recStats.cancelled_or_no_data_count ?? 0}
                </p>
                <p className="text-slate-400 text-sm">Отменён / Не получено данных</p>
                {recStats.total > 0 && (recStats.cancelled_or_no_data_pct ?? 0) >= 0 && (
                  <p className="text-slate-500 text-xs mt-0.5">
                    {recStats.cancelled_or_no_data_pct ?? 0}% от общего
                  </p>
                )}
              </div>
            </div>
            {recStats.total > 0 && recStats.correct + recStats.wrong > 0 && (
              <p className="text-slate-500 text-sm mb-4">
                Процент угадывания (из сыгравших): {((recStats.correct / (recStats.correct + recStats.wrong)) * 100).toFixed(1)}%
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
                    onClick={() => { setRecResultFilter(value); setRecPage(1); }}
                    className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                      recResultFilter === value
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
                value={recOddsMin}
                onChange={(e) => { setRecOddsMin(e.target.value); setRecPage(1); }}
                className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
              />
              <span className="text-slate-400 text-sm">Кф. до</span>
              <input
                type="number"
                min={1}
                step={0.01}
                placeholder="—"
                value={recOddsMax}
                onChange={(e) => { setRecOddsMax(e.target.value); setRecPage(1); }}
                className="w-20 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white placeholder-slate-500"
              />
              <span className="text-slate-400 text-sm">На странице:</span>
              <select
                value={recPerPage}
                onChange={(e) => { setRecPerPage(Number(e.target.value)); setRecPage(1); }}
                className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
              >
                {PER_PAGE_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
            <p className="text-slate-500 text-sm mb-3">
              Показано {recStats.total_filtered} из {recStats.total} рекомендаций
              {recResultFilter !== "all" || recOddsMin || recOddsMax ? " (по фильтрам)" : ""}.
            </p>
            {recStats.items.length === 0 ? (
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
                    {recStats.items.map((row) => (
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
                        <td className="py-2 pr-2 text-slate-400">{row.odds_at_recommendation != null ? row.odds_at_recommendation.toFixed(2) : "—"}</td>
                        <td className="py-2 pr-2 text-slate-400">{row.minutes_before_start != null ? `за ${row.minutes_before_start} мин до начала` : "—"}</td>
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
            {recStats.total_pages > 0 && (
              <div className="flex flex-wrap items-center gap-4 mt-4 pt-4 border-t border-slate-700">
                <span className="text-slate-400 text-sm">
                  Страница {recStats.page} из {recStats.total_pages}
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={recStats.page <= 1}
                    onClick={() => setRecPage((p) => Math.max(1, p - 1))}
                    className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Назад
                  </button>
                  <button
                    type="button"
                    disabled={recStats.page >= recStats.total_pages}
                    onClick={() => setRecPage((p) => p + 1)}
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
    </main>
  );
}
