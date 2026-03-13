"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getTableTennisForecasts, type TableTennisForecastItem } from "@/lib/api";

type PhaseFilter = "all" | "upcoming" | "live";

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

function formatCountdownFromNow(ts: number | null | undefined): string {
  if (!ts) return "—";
  const now = Math.floor(Date.now() / 1000);
  const diff = ts - now;
  if (diff <= 0) return "Матч идёт";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `До начала ${mins} мин`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  return `До начала ${hours} ч ${rest} мин`;
}

function formatLeadTime(seconds: number | null | undefined): string {
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
}

function formatMatchPhase(item: TableTennisForecastItem): string {
  if (item.event_status === "finished") return "Завершен";
  if (item.event_status === "live") return "В игре";
  return formatCountdownFromNow(item.starts_at ?? null);
}

function formatStatus(item: TableTennisForecastItem): string {
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
}

function statusTextClass(item: TableTennisForecastItem): string {
  if (item.status === "hit") return "text-emerald-400";
  if (item.status === "miss") return "text-rose-400";
  if (item.status === "pending") return "text-sky-300";
  if (item.status === "cancelled" || item.status === "no_result") return "text-amber-300";
  return "text-slate-300";
}

function formatScoreDetails(item: TableTennisForecastItem): string {
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
}

export default function TableTennisLineNoMlPage() {
  const [items, setItems] = useState<TableTennisForecastItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [lockedMessage, setLockedMessage] = useState<string | null>(null);
  const [lockedUrl, setLockedUrl] = useState<string | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await getTableTennisForecasts({
          page,
          page_size: pageSize,
          channel: "no_ml",
          // берём только текущие/свежие матчи: сегодня
          date_from: new Date().toISOString().slice(0, 10),
          date_to: new Date().toISOString().slice(0, 10),
        });
        if (cancelled) return;
        setItems(res.items ?? []);
        setTotal(res.total ?? 0);
        setLocked(Boolean(res.forecast_locked));
        setLockedMessage(res.forecast_locked_message ?? null);
        setLockedUrl(res.forecast_purchase_url ?? null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки прогнозов");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [page, pageSize]);

  const filteredItems = useMemo(() => {
    return items.filter((it) => {
      if (phaseFilter === "upcoming") return it.event_status === "scheduled";
      if (phaseFilter === "live") return it.event_status === "live";
      return true;
    });
  }, [items, phaseFilter]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="p-6 md:p-8 space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold text-white mb-2">
          Настольный теннис — аналитика без ML
        </h1>
        <p className="text-slate-400 text-sm">
          Прематч‑прогнозы по исторической статистике игроков без использования ML‑модели.
        </p>
      </div>

      {locked && (
        <div className="rounded-lg border border-amber-500/60 bg-amber-900/20 px-4 py-3 text-sm text-amber-100 space-y-1">
          <p className="font-medium">Доступ к аналитике без ML недоступен.</p>
          <p className="text-amber-100/90">
            {lockedMessage || "Чтобы видеть прогнозы и статистику по предстоящим матчам, оформите подписку на аналитику без ML."}
          </p>
          <div className="pt-1">
            <Link
              href={lockedUrl || "/pricing"}
              className="inline-flex items-center rounded-md bg-gradient-to-r from-sky-600 to-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:from-sky-500 hover:to-blue-500"
            >
              Перейти к тарифам
            </Link>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex items-center gap-1">
          <span className="text-xs text-slate-500">Матчи:</span>
          <button
            type="button"
            onClick={() => setPhaseFilter("all")}
            className={`px-2 py-1 rounded-md text-xs ${
              phaseFilter === "all"
                ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                : "border border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            Все
          </button>
          <button
            type="button"
            onClick={() => setPhaseFilter("upcoming")}
            className={`px-2 py-1 rounded-md text-xs ${
              phaseFilter === "upcoming"
                ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                : "border border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            Ещё не начались
          </button>
          <button
            type="button"
            onClick={() => setPhaseFilter("live")}
            className={`px-2 py-1 rounded-md text-xs ${
              phaseFilter === "live"
                ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                : "border border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            Уже идут
          </button>
        </div>
        <div className="inline-flex items-center gap-2 text-slate-300 text-sm">
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
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      </div>

      {loading && <p className="text-slate-400 text-sm">Загрузка прогнозов…</p>}
      {error && <p className="text-rose-400 text-sm">{error}</p>}

      {!loading && !error && filteredItems.length === 0 && !locked && (
        <p className="text-slate-500 text-sm">Нет прогнозов для выбранных фильтров.</p>
      )}

      {!loading && !error && filteredItems.length > 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs md:text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/80 text-slate-300">
                  <th className="px-3 py-2 text-left font-medium">Статус матча</th>
                  <th className="px-3 py-2 text-left font-medium">Начало</th>
                  <th className="px-3 py-2 text-center font-medium whitespace-nowrap">За сколько до начала</th>
                  <th className="px-3 py-2 text-left font-medium">Матч</th>
                  <th className="px-3 py-2 text-left font-medium">Лига</th>
                  <th className="px-3 py-2 text-left font-medium min-w-[220px]">Прогноз (без ML)</th>
                  <th className="px-3 py-2 text-center font-medium whitespace-nowrap">Кф</th>
                  <th className="px-3 py-2 text-center font-medium">Счёт</th>
                  <th className="px-3 py-2 text-center font-medium">Статус прогноза</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((f, idx) => (
                  <tr
                    key={`${f.id ?? f.event_id}-${f.market ?? "match"}-${f.channel ?? "no_ml"}`}
                    className={`border-b border-slate-700/60 hover:bg-slate-700/25 transition ${
                      idx % 2 === 0 ? "bg-slate-900/10" : "bg-transparent"
                    }`}
                  >
                    <td className="px-3 py-2 whitespace-nowrap text-slate-300">
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                        className="hover:text-emerald-200"
                      >
                        {formatMatchPhase(f)}
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
                    <td className="px-3 py-2 text-center text-slate-300 tabular-nums whitespace-nowrap">
                      {formatLeadTime(f.forecast_lead_seconds ?? null)}
                    </td>
                    <td className="px-3 py-2 text-white">
                      <Link
                        href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                        className="text-emerald-300 hover:text-emerald-200 font-semibold"
                      >
                        {f.home_name} — {f.away_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-slate-400 whitespace-nowrap">
                      <span className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-xs">
                        {f.league_name ?? "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-slate-100">
                      {f.forecast_text || "—"}
                    </td>
                    <td className="px-3 py-2 text-center text-slate-200 tabular-nums whitespace-nowrap">
                      {f.forecast_odds != null ? f.forecast_odds.toFixed(2) : f.odds_used != null ? f.odds_used.toFixed(2) : "—"}
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
                    <td className="px-3 py-2 text-center">
                      <span className={`text-xs font-medium ${statusTextClass(f)}`}>
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

      {!loading && !error && (
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
      )}
    </div>
  );
}

