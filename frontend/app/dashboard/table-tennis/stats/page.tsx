"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  getTableTennisForecasts,
  type TableTennisForecastItem,
} from "@/lib/api";
import { forecastMarkKey, getMarkedKeySet, setBetMarked, setBetMarkedBulk } from "@/lib/betMarks";

const STORAGE_KEY_STATS_COMPACT = "tt_stats_compact_mode_v1";
type PeriodFilter = "today" | "1d" | "7d" | "30d";
type PhaseFilter = "all" | "upcoming" | "live";

const PERIODS: Array<{ id: PeriodFilter; label: string }> = [
  { id: "today", label: "Сегодня" },
  { id: "1d", label: "1 день" },
  { id: "7d", label: "7 дней" },
  { id: "30d", label: "30 дней" },
];

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
  if (diff <= 0) return "Стартовал";
  const mins = Math.floor(diff / 60);
  if (mins < 60) return `До начала ${mins} мин`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  return `До начала ${hours} ч ${rest} мин`;
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function periodLocalWindow(period: PeriodFilter): { fromSec: number; toSec: number } {
  const nowMs = Date.now();
  if (period === "today") {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    return { fromSec: Math.floor(start.getTime() / 1000), toSec: Math.floor(end.getTime() / 1000) };
  }
  if (period === "1d") {
    return { fromSec: Math.floor((nowMs - 24 * 60 * 60 * 1000) / 1000), toSec: Math.floor(nowMs / 1000) };
  }
  if (period === "7d") {
    return { fromSec: Math.floor((nowMs - 7 * 24 * 60 * 60 * 1000) / 1000), toSec: Math.floor(nowMs / 1000) };
  }
  return { fromSec: Math.floor((nowMs - 30 * 24 * 60 * 60 * 1000) / 1000), toSec: Math.floor(nowMs / 1000) };
}

function periodApiRange(period: PeriodFilter): { date_from: string; date_to: string } {
  const w = periodLocalWindow(period);
  const from = new Date((w.fromSec - 24 * 60 * 60) * 1000);
  const to = new Date((w.toSec + 24 * 60 * 60) * 1000);
  return { date_from: isoDate(from), date_to: isoDate(to) };
}

function inLocalWindow(item: TableTennisForecastItem, window: { fromSec: number; toSec: number }): boolean {
  const ts = item.created_at ?? item.starts_at ?? 0;
  if (!ts) return false;
  return ts >= window.fromSec && ts < window.toSec;
}

function cleanForecastText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "Недостаточно данных для расчёта";
  return text
    .replace(/\s*\(\d+(?:[.,]\d+)?%\)/g, "")
    .replace(/%/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function getQualityTierLabel(item: TableTennisForecastItem): string {
  const summary = (item.explanation_summary || "").toUpperCase();
  const m = summary.match(/TIER\s+([ABCD])/);
  return m?.[1] || "—";
}

function sortByBetGivenAt(list: TableTennisForecastItem[], dir: "asc" | "desc"): TableTennisForecastItem[] {
  return [...list].sort((a, b) => {
    const aTs = a.created_at ?? a.starts_at ?? 0;
    const bTs = b.created_at ?? b.starts_at ?? 0;
    if (aTs !== bTs) return dir === "desc" ? bTs - aTs : aTs - bTs;
    const aStart = a.starts_at ?? 0;
    const bStart = b.starts_at ?? 0;
    return dir === "desc" ? bStart - aStart : aStart - bStart;
  });
}

type LoadForecastsResult = {
  items: TableTennisForecastItem[];
  only_resolved?: boolean;
  forecast_purchase_url?: string;
};

async function loadAllForecasts(params: {
  channel: "free" | "paid" | "vip" | "bot_signals" | "no_ml" | "nn";
  quality_tier?: string;
  date_from?: string;
  date_to?: string;
}): Promise<LoadForecastsResult> {
  const pageSize = 250;
  const first = await getTableTennisForecasts({
    page: 1,
    page_size: pageSize,
    channel: params.channel,
    quality_tier: params.quality_tier,
    date_from: params.date_from,
    date_to: params.date_to,
  });
  const all = [...(first.items || [])];
  const totalPages = Math.max(1, Math.ceil((first.total || 0) / pageSize));
  for (let page = 2; page <= totalPages; page += 1) {
    const next = await getTableTennisForecasts({
      page,
      page_size: pageSize,
      channel: params.channel,
      quality_tier: params.quality_tier,
      date_from: params.date_from,
      date_to: params.date_to,
    });
    if (next.items?.length) all.push(...next.items);
  }
  return {
    items: all,
    only_resolved: first.only_resolved,
    forecast_purchase_url: first.forecast_purchase_url,
  };
}

const ALL_TABS = [
  { id: "free" as const, label: "Бесплатный канал" },
  { id: "paid" as const, label: "Платная подписка" },
  { id: "bot_signals" as const, label: "Сигналы из бота" },
  { id: "vip" as const, label: "Вип канал" },
  { id: "no_ml" as const, label: "Аналитика без ML" },
  { id: "nn" as const, label: "Аналитика Нейросетью" },
];

export default function TableTennisStatsPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<"free" | "paid" | "vip" | "bot_signals" | "no_ml" | "nn">("paid");
  const [period, setPeriod] = useState<PeriodFilter>("7d");
  const [items, setItems] = useState<TableTennisForecastItem[]>([]);
  const [forecastPurchaseUrl, setForecastPurchaseUrl] = useState<string | null>(null);
  const [onlyResolved, setOnlyResolved] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<string>("");
  const [qualityTier, setQualityTier] = useState<string>("");
  const [compactMode, setCompactMode] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [sortByBetTime, setSortByBetTime] = useState<"asc" | "desc">("desc");
  const [phaseFilter, setPhaseFilter] = useState<PhaseFilter>("all");
  const [markedKeys, setMarkedKeys] = useState<Set<string>>(new Set());
  const [onlyMarked, setOnlyMarked] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setCompactMode(localStorage.getItem(STORAGE_KEY_STATS_COMPACT) === "1");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(STORAGE_KEY_STATS_COMPACT, compactMode ? "1" : "0");
  }, [compactMode]);

  useEffect(() => {
    setMarkedKeys(getMarkedKeySet());
  }, []);

  useEffect(() => {
    const ch = (searchParams.get("channel") || "").toLowerCase();
    if (ch === "free" || ch === "paid" || ch === "vip" || ch === "bot_signals" || ch === "no_ml" || ch === "nn") {
      setActiveTab(ch);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const range = periodApiRange(period);
        const localRange = periodLocalWindow(period);
        const f = await loadAllForecasts({
          channel: activeTab,
          quality_tier: qualityTier || undefined,
          date_from: range.date_from,
          date_to: range.date_to,
        });
        if (cancelled) return;
        setItems((f.items ?? []).filter((it) => inLocalWindow(it, localRange)));
        setTotal(0);
        setForecastPurchaseUrl(f.forecast_purchase_url ?? null);
        setOnlyResolved(Boolean(f.only_resolved));
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
  }, [activeTab, qualityTier, period]);

  const isMarked = (item: TableTennisForecastItem): boolean => markedKeys.has(forecastMarkKey(item));

  const sortedItems = useMemo(() => {
    const filtered = items.filter((it) => {
      if (statusFilter && it.status !== statusFilter) return false;
      if (onlyMarked && !isMarked(it)) return false;
      if (phaseFilter === "all") return true;
      if (phaseFilter === "live") return it.event_status === "live";
      if (phaseFilter === "upcoming") return it.event_status === "scheduled";
      return true;
    });
    return sortByBetGivenAt(filtered, sortByBetTime);
  }, [items, statusFilter, onlyMarked, sortByBetTime, phaseFilter, markedKeys]);

  const pagedItems = useMemo(
    () => sortedItems.slice((page - 1) * pageSize, page * pageSize),
    [sortedItems, page, pageSize],
  );
  const totalItems = sortedItems.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const cellPadClass = compactMode ? "px-2 py-1.5" : "px-3 py-2";
  const tableTextClass = compactMode ? "text-[11px]" : "text-xs md:text-sm";

  const hit = items.filter((x) => x.status === "hit").length;
  const miss = items.filter((x) => x.status === "miss").length;
  const pending = items.filter((x) => x.status === "pending").length;
  const cancelledCount = items.filter((x) => x.status === "cancelled").length;
  const noResult = items.filter((x) => x.status === "no_result").length;
  const resolvedTotal = hit + miss + cancelledCount + noResult;
  const hitRate = resolvedTotal > 0 ? (hit / resolvedTotal) * 100 : null;
  const oddsValues = items
    .map((x) => x.forecast_odds)
    .filter((x): x is number => typeof x === "number" && Number.isFinite(x) && x > 0);
  const avgOdds = oddsValues.length ? oddsValues.reduce((a, b) => a + b, 0) / oddsValues.length : null;

  const toggleMarked = (item: TableTennisForecastItem, marked: boolean) => {
    setBetMarked(item, marked);
    setMarkedKeys(getMarkedKeySet());
  };

  const markVisible = (marked: boolean) => {
    setBetMarkedBulk(sortedItems, marked);
    setMarkedKeys(getMarkedKeySet());
  };

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

  const statusTextClass = (item: TableTennisForecastItem): string => {
    if (item.status === "hit") return "text-emerald-400";
    if (item.status === "miss") return "text-rose-400";
    if (item.status === "pending") return "text-sky-300";
    if (item.status === "cancelled" || item.status === "no_result") return "text-amber-300";
    return "text-slate-300";
  };

  const formatMatchPhase = (item: TableTennisForecastItem): string => {
    if (item.event_status === "finished") return "Завершен";
    if (item.event_status === "live") return "В игре";
    return formatCountdownFromNow(item.starts_at ?? null);
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
        <p className="text-amber-200/90 text-sm mb-1">
          Данные появятся при активной подписке на аналитику или для VIP канала — с доступом к VIP каналу.
        </p>
        <p className="text-slate-400 text-sm">
          Сводка по прематч‑прогнозам модели и список всех прогнозов. Для деталей по матчу перейдите в его карточку.
        </p>
      </div>

      {onlyResolved && forecastPurchaseUrl && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <Link
            href={forecastPurchaseUrl}
            className="text-amber-200 hover:text-amber-100 font-medium"
          >
            Чтобы увидеть текущие и новые прогнозы — приобретите подписку на аналитику или доступ в VIP канал
          </Link>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-b border-slate-700 pb-2">
        {ALL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              setActiveTab(tab.id);
              setPage(1);
            }}
            className={`px-3 py-1.5 rounded-t-md text-sm ${
              activeTab === tab.id
                ? "bg-gradient-to-r from-sky-500/25 to-blue-500/25 text-sky-100 border border-sky-500/35 border-b-slate-800"
                : "bg-transparent text-slate-400 border border-transparent hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {PERIODS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => {
              setPeriod(p.id);
              setPage(1);
            }}
            className={`px-3 py-1.5 rounded-md text-sm ${
              period === p.id
                ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                : "border border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            {p.label}
          </button>
        ))}
        <div className="inline-flex items-center gap-1 ml-2">
          <span className="text-xs text-slate-500">Матчи:</span>
          <button
            type="button"
            onClick={() => {
              setPhaseFilter("all");
              setPage(1);
            }}
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
            onClick={() => {
              setPhaseFilter("upcoming");
              setPage(1);
            }}
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
            onClick={() => {
              setPhaseFilter("live");
              setPage(1);
            }}
            className={`px-2 py-1 rounded-md text-xs ${
              phaseFilter === "live"
                ? "bg-sky-500/20 border border-sky-500/40 text-sky-100"
                : "border border-slate-700 text-slate-400 hover:text-slate-200"
            }`}
          >
            Уже идут
          </button>
        </div>
      </div>

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8 gap-3">
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Всего прогнозов</p>
          <p className="text-xl font-semibold text-white">{items.length}</p>
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
            {hitRate != null ? `${hitRate.toFixed(1)}%` : "—"}
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
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
          <p className="text-slate-400 text-xs mb-1">Средний кф</p>
          <p className="text-xl font-semibold text-slate-200">
            {avgOdds != null ? avgOdds.toFixed(2) : "—"}
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <div className="md:static md:bg-transparent md:px-0 md:py-0 md:border-0 sticky top-[57px] z-20 bg-[var(--bg)]/95 backdrop-blur border-y border-slate-800 px-2 py-2 -mx-2">
          <div className="flex items-center justify-between md:block">
            <h2 className="text-lg font-semibold text-white">Список прогнозов</h2>
            <button
              type="button"
              onClick={() => setMobileFiltersOpen((v) => !v)}
              className="md:hidden rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-300"
            >
              {mobileFiltersOpen ? "Скрыть фильтры" : "Показать фильтры"}
            </button>
          </div>
          <div className={`${mobileFiltersOpen ? "flex" : "hidden"} md:flex flex-wrap items-center gap-3 mt-2 md:mt-3`}>
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
          <label className="flex items-center gap-2 text-slate-300 text-sm">
            <span className="text-slate-500" title="Класс качества прогноза: A — самый сильный, затем B, C и D.">
              Уровень качества:
            </span>
            <select
              value={qualityTier}
              onChange={(e) => {
                setQualityTier(e.target.value);
                setPage(1);
              }}
              className="rounded bg-slate-800 border border-slate-600 text-slate-200 px-2 py-1 text-sm"
            >
              <option value="">Все</option>
              <option value="A">A</option>
              <option value="B">B</option>
              <option value="C">C</option>
              <option value="D">D</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-300 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={compactMode}
              onChange={(e) => setCompactMode(e.target.checked)}
              className="rounded border-slate-600 bg-slate-700"
            />
            <span className="text-slate-500">Компактный режим</span>
          </label>
          <label className="flex items-center gap-2 text-slate-300 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={onlyMarked}
              onChange={(e) => {
                setOnlyMarked(e.target.checked);
                setPage(1);
              }}
              className="rounded border-slate-600 bg-slate-700"
            />
            <span className="text-slate-500">Только отмеченные (ставил)</span>
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => markVisible(true)}
              className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
            >
              Отметить видимые как “ставил”
            </button>
            <button
              type="button"
              onClick={() => markVisible(false)}
              className="rounded border border-slate-600 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
            >
              Снять отметки видимых
            </button>
          </div>
          </div>
        </div>

        {loading && <p className="text-slate-400 text-sm">Загрузка…</p>}
        {error && <p className="text-rose-400 text-sm">{error}</p>}

        {!loading && !error && (
          <>
            {sortedItems.length === 0 ? (
              <p className="text-slate-500 text-sm">Прогнозов по выбранным фильтрам нет.</p>
            ) : (
              <>
              <div className="md:hidden space-y-2">
                {sortedItems.map((f) => (
                  <div key={`${f.id ?? f.event_id}-${f.market ?? "match"}-${f.channel ?? "paid"}`} className="rounded-lg border border-slate-700 bg-slate-800/40 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`} className="text-xs text-emerald-300 hover:text-emerald-200">
                        {formatDateTime(f.starts_at)}
                      </Link>
                      <span className={`text-[11px] font-medium ${statusTextClass(f)}`}>
                        {formatStatus(f)}
                      </span>
                    </div>
                    <div className="mt-2 text-white font-semibold">
                      <Link href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`} className="hover:text-emerald-200">
                        {f.home_name} — {f.away_name}
                      </Link>
                    </div>
                    <div className="mt-1">
                      <span className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-[11px] text-slate-300">
                        {f.league_name ?? "—"}
                      </span>
                    </div>
                    <div className="mt-2 text-sm text-slate-100 leading-5">{cleanForecastText(f.forecast_text)}</div>
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-300">
                      <span>Кф: {f.forecast_odds != null ? f.forecast_odds.toFixed(2) : "—"}</span>
                      <span
                        className="inline-flex items-center rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-sky-200"
                        title="Класс качества прогноза: A — самый сильный, затем B, C и D."
                      >
                        Тир {getQualityTierLabel(f)}
                      </span>
                      <span className={`font-medium ${statusTextClass(f)}`}>{formatStatus(f)}</span>
                    </div>
                    <label className="mt-2 inline-flex items-center gap-2 text-xs text-slate-300">
                      <input
                        type="checkbox"
                        checked={isMarked(f)}
                        onChange={(e) => toggleMarked(f, e.target.checked)}
                        className="h-4 w-4 rounded border-slate-600 bg-slate-800"
                      />
                      Ставил
                    </label>
                    <div className="mt-1 text-xs text-slate-400">
                      {formatMatchPhase(f)} · {formatLeadTime(f.forecast_lead_seconds ?? null)}
                    </div>
                  </div>
                ))}
              </div>
              <div className="hidden md:block rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className={`w-full ${tableTextClass}`}>
                    <thead>
                      <tr className="border-b border-slate-700 bg-slate-800/80 text-slate-300">
                        <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>Ставил</th>
                        <th className={`${cellPadClass} text-left font-medium`}>Статус матча</th>
                        <th
                          className={`${cellPadClass} text-left font-medium cursor-pointer hover:text-white select-none`}
                          onClick={() => setSortByBetTime((d) => (d === "desc" ? "asc" : "desc"))}
                          title="Сортировка по дате и времени, когда прогноз был дан"
                        >
                          Дата ставки {sortByBetTime === "desc" ? "↓" : "↑"}
                        </th>
                        <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>За сколько до начала</th>
                        <th className={`${cellPadClass} text-left font-medium`}>Матч</th>
                        <th className={`${cellPadClass} text-left font-medium`}>Лига</th>
                        <th className={`${cellPadClass} text-left font-medium min-w-[220px]`}>Прогноз</th>
                        <th
                          className={`${cellPadClass} text-center font-medium whitespace-nowrap`}
                          title="Класс качества прогноза: A — самый сильный, затем B, C и D."
                        >
                          Тир
                        </th>
                        <th className={`${cellPadClass} text-center font-medium whitespace-nowrap`}>Оценка в БК</th>
                        <th className={`${cellPadClass} text-center font-medium`}>Счёт</th>
                        <th className={`${cellPadClass} text-center font-medium`}>Статус</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedItems.map((f, idx) => (
                        <tr
                          key={`${f.id ?? f.event_id}-${f.market ?? "match"}-${f.channel ?? "paid"}`}
                          className={`border-b border-slate-700/60 hover:bg-slate-700/25 transition ${
                            idx % 2 === 0 ? "bg-slate-900/5" : "bg-transparent"
                          }`}
                        >
                          <td className={`${cellPadClass} text-center`}>
                            <input
                              type="checkbox"
                              checked={isMarked(f)}
                              onChange={(e) => toggleMarked(f, e.target.checked)}
                              className="h-4 w-4 rounded border-slate-600 bg-slate-800"
                            />
                          </td>
                          <td className={`${cellPadClass} whitespace-nowrap text-slate-300 tabular-nums`}>
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {formatMatchPhase(f)}
                            </Link>
                          </td>
                          <td className={`${cellPadClass} whitespace-nowrap text-slate-300 tabular-nums`}>
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="hover:text-emerald-200"
                            >
                              {formatDateTime(f.created_at ?? f.starts_at)}
                            </Link>
                          </td>
                          <td className={`${cellPadClass} text-center text-slate-300 tabular-nums whitespace-nowrap`}>
                            {formatLeadTime(f.forecast_lead_seconds ?? null)}
                          </td>
                          <td className={`${cellPadClass} text-white`}>
                            <Link
                              href={`/dashboard/table-tennis/matches/${encodeURIComponent(f.event_id)}`}
                              className="text-emerald-300 hover:text-emerald-200 font-semibold"
                            >
                              {f.home_name} — {f.away_name}
                            </Link>
                          </td>
                          <td className={`${cellPadClass} text-slate-400 whitespace-nowrap`}>
                            <span className="inline-flex items-center rounded-md border border-slate-600 bg-slate-800/60 px-2 py-1 text-xs">
                              {f.league_name ?? "—"}
                            </span>
                          </td>
                          <td className={`${cellPadClass} text-slate-100 ${compactMode ? "leading-4" : "leading-5"}`}>
                            {cleanForecastText(f.forecast_text)}
                          </td>
                          <td className={`${cellPadClass} text-center`}>
                            <span
                              className="inline-flex items-center rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-xs text-sky-200"
                              title="Класс качества прогноза: A — самый сильный, затем B, C и D."
                            >
                              {getQualityTierLabel(f)}
                            </span>
                          </td>
                          <td className={`${cellPadClass} text-center text-slate-200 tabular-nums whitespace-nowrap`}>
                            {f.forecast_odds != null ? f.forecast_odds.toFixed(2) : "—"}
                          </td>
                          <td className={`${cellPadClass} text-center text-slate-200 tabular-nums`}>
                            <div className="font-semibold">
                              {f.sets_score ?? "—"}
                            </div>
                            {formatScoreDetails(f) && (
                              <div className="text-[11px] text-slate-400">
                                ({formatScoreDetails(f)})
                              </div>
                            )}
                          </td>
                          <td className={`${cellPadClass} text-center`}>
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
              </>
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
                Страница {page} из {totalPages} · прогнозов {totalItems}
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

