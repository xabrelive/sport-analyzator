"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  getTableTennisForecastStats,
  getTableTennisForecasts,
  subscribeTableTennisForecastsStream,
  type TableTennisForecastItem,
  type TableTennisForecastsStreamPayload,
} from "@/lib/api";

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "—";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export default function TableTennisStatsPage() {
  const [activeTab, setActiveTab] = useState<"free" | "paid" | "vip" | "bot_signals">("paid");
  const [stats, setStats] = useState<{ total: number; by_status: Record<string, number>; hit_rate: number | null } | null>(null);
  const [items, setItems] = useState<TableTennisForecastItem[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [s, f] = await Promise.all([
          getTableTennisForecastStats({ channel: activeTab }),
          getTableTennisForecasts({
            page,
            page_size: pageSize,
            status: statusFilter || undefined,
            channel: activeTab,
          }),
        ]);
        if (cancelled) return;
        setStats(s);
        setItems(f.items);
        setTotal(f.total);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки статистики");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, statusFilter, activeTab]);

  // SSE-обновления для активной вкладки (канала): обновляем агрегаты и список прогнозов
  useEffect(() => {
    const unsub = subscribeTableTennisForecastsStream(
      activeTab,
      (payload: TableTennisForecastsStreamPayload) => {
        setStats(payload.stats);
        setItems((prev) => {
          // если пользователь на первой странице, можно обновлять полностью
          return page === 1 ? payload.forecasts.items : prev;
        });
        setTotal(payload.forecasts.total);
      },
      (err) => {
        console.error("Forecasts SSE error", err);
      }
    );
    return () => {
      unsub();
    };
  }, [activeTab, page]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const hit = stats?.by_status?.hit ?? 0;
  const miss = stats?.by_status?.miss ?? 0;
  const pending = stats?.by_status?.pending ?? 0;
  const cancelledCount = stats?.by_status?.cancelled ?? 0;
  const noResult = stats?.by_status?.no_result ?? 0;

  const formatStatus = (item: TableTennisForecastItem): string => {
    if (item.status === "pending") {
      if (item.event_status === "live") return "Матч идёт";
      if (item.event_status === "finished") return "Ожидает результата";
      return "Ожидает начала матча";
    }
    if (item.status === "hit") return "Угадан";
    if (item.status === "miss") return "Не угадан";
    if (item.status === "cancelled") return "Отменён";
    if (item.status === "no_result") return "Нет данных";
    return item.status;
  };

  const formatScoreDetails = (item: TableTennisForecastItem): string => {
    if (!item.live_score) return "";
    const keys = Object.keys(item.live_score).sort((a, b) => Number(a) - Number(b));
    const parts: string[] = [];
    for (const k of keys) {
      const s = item.live_score[k];
      if (!s) continue;
      const h = s.home;
      const a = s.away;
      if (h == null && a == null) continue;
      parts.push(`${h}-${a}`);
    }
    return parts.join(" ");
  };

  const formatLeadTime = (seconds: number | null | undefined): string => {
    if (seconds == null) return "—";
    const s = seconds;
    const abs = Math.abs(s);
    const sign = s >= 0 ? "" : "-";
    const minutes = Math.floor(abs / 60);
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    if (hours > 0) {
      return `${sign}${hours} ч ${remMin} мин`;
    }
    return `${sign}${minutes} мин`;
  };

  return (
    <div className="p-6 md:p-8 space-y-8">
      <div>
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — статистика прогнозов
        </h1>
        <p className="text-slate-400 text-sm">
          Сводка по прематч‑прогнозам модели и список всех прогнозов. Для деталей по матчу перейдите в его карточку.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-slate-700 pb-2">
        {[
          { id: "free" as const, label: "Бесплатный канал" },
          { id: "paid" as const, label: "Платная аналитика" },
          { id: "vip" as const, label: "VIP чат" },
          { id: "bot_signals" as const, label: "Сигналы от бота" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setActiveTab(tab.id);
              setPage(1);
            }}
            className={`px-3 py-1.5 rounded-t-md text-sm ${
              activeTab === tab.id
                ? "bg-slate-800 text-emerald-300 border border-slate-700 border-b-slate-800"
                : "bg-transparent text-slate-400 border border-transparent hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <section className="grid grid-cols-1 md:grid-cols-7 gap-3">
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Всего прогнозов</p>
          <p className="text-xl font-semibold text-white">{stats?.total ?? 0}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Угадано</p>
          <p className="text-xl font-semibold text-emerald-400">{hit}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Не угадано</p>
          <p className="text-xl font-semibold text-rose-400">{miss}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Ожидают результата</p>
          <p className="text-xl font-semibold text-slate-200">{pending}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Hit‑rate (все завершённые)</p>
          <p className="text-xl font-semibold text-emerald-300">
            {stats?.hit_rate != null ? `${stats.hit_rate.toFixed(1)}%` : "—"}
          </p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Отменено</p>
          <p className="text-xl font-semibold text-slate-200">{cancelledCount}</p>
        </div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Нет данных</p>
          <p className="text-xl font-semibold text-slate-200">{noResult}</p>
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-white">Список прогнозов</h2>
          <label className="flex items-center gap-2 text-slate-300 text-sm">
            <span className="text-slate-500">Статус:</span>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setPage(1);
              }}
              className="rounded bg-slate-800 border border-slate-600 text-slate-200 px-2 py-1 text-sm"
            >
              <option value="">Все</option>
              <option value="pending">Ожидает</option>
              <option value="hit">Угадан</option>
              <option value="miss">Не угадан</option>
              <option value="cancelled">Отменён</option>
              <option value="no_result">Нет данных</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300 text-sm">
            <span className="text-slate-500">На странице:</span>
            <select
              value={pageSize}
              onChange={(e) => {
                const v = Number(e.target.value) || 10;
                setPageSize(v);
                setPage(1);
              }}
              className="rounded bg-slate-800 border border-slate-600 text-slate-200 px-2 py-1 text-sm"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </label>
        </div>

        {loading && <p className="text-slate-400 text-sm">Загрузка…</p>}
        {error && <p className="text-rose-400 text-sm">{error}</p>}

        {!loading && !error && (
          <>
            {items.length === 0 ? (
              <p className="text-slate-500 text-sm">Прогнозов по выбранным фильтрам нет.</p>
            ) : (
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs md:text-sm">
                    <thead>
                      <tr className="border-b border-slate-700 bg-slate-700/60 text-slate-300">
                        <th className="px-3 py-2 text-left font-medium">Дата прогноза</th>
                        <th className="px-3 py-2 text-left font-medium">Начало матча</th>
                        <th className="px-3 py-2 text-center font-medium">За сколько до начала</th>
                        <th className="px-3 py-2 text-left font-medium">Матч</th>
                        <th className="px-3 py-2 text-left font-medium">Лига</th>
                        <th className="px-3 py-2 text-left font-medium">Прогноз</th>
                        <th className="px-3 py-2 text-center font-medium">Кф прогноза</th>
                        <th className="px-3 py-2 text-center font-medium">Счёт</th>
                        <th className="px-3 py-2 text-center font-medium">Уверенность</th>
                        <th className="px-3 py-2 text-center font-medium">Статус</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((f) => (
                        <tr key={f.event_id} className="border-b border-slate-700/60 hover:bg-slate-700/30 transition">
                          <td className="px-3 py-2 whitespace-nowrap text-slate-300 tabular-nums">
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {formatDateTime(f.created_at)}
                            </Link>
                          </td>
                          <td className="px-3 py-2 whitespace-nowrap text-slate-300 tabular-nums">
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {formatDateTime(f.starts_at)}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-center text-slate-300 tabular-nums">
                            {formatLeadTime(f.forecast_lead_seconds ?? null)}
                          </td>
                          <td className="px-3 py-2 text-white">
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="text-emerald-300 hover:text-emerald-200"
                            >
                              {f.home_name} — {f.away_name}
                            </Link>
                          </td>
                          <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                            {f.league_name ?? "—"}
                          </td>
                          <td className="px-3 py-2 text-slate-200">
                            {f.forecast_text}
                          </td>
                          <td className="px-3 py-2 text-center text-slate-200 tabular-nums">
                            {f.forecast_odds != null ? f.forecast_odds.toFixed(2) : "—"}
                          </td>
                          <td className="px-3 py-2 text-center text-slate-200 tabular-nums">
                            <div className="font-semibold">
                              {f.sets_score ?? "—"}
                            </div>
                            {formatScoreDetails(f) && (
                              <div className="text-[11px] text-slate-400">
                                ({formatScoreDetails(f)})
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center text-slate-200 tabular-nums">
                            {f.confidence_pct != null ? `${f.confidence_pct.toFixed(0)}%` : "—"}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span
                              className={
                                f.status === "hit"
                                  ? "text-emerald-400"
                                  : f.status === "miss"
                                  ? "text-rose-400"
                                  : "text-slate-300"
                              }
                            >
                              {formatStatus(f)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            <div className="mt-3 flex items-center gap-2">
              <button
                className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
                disabled={page <= 1}
                onClick={() => setPage((v) => Math.max(1, v - 1))}
              >
                Назад
              </button>
              <span className="text-slate-400 text-xs md:text-sm">
                Страница {page} из {totalPages} · прогнозов {total}
              </span>
              <button
                className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
                disabled={page >= totalPages}
                onClick={() => setPage((v) => Math.min(totalPages, v + 1))}
              >
                Вперёд
              </button>
            </div>
          </>
        )}
      </section>

    </div>
  );
}

