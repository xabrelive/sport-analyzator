"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getTableTennisForecasts, type TableTennisForecastItem } from "@/lib/api";

type CalcChannel = "free" | "paid" | "vip" | "bot_signals";
type CalcItem = TableTennisForecastItem & { selected: boolean };

const PER_PAGE_OPTIONS = [20, 50, 100];

type PeriodFilter = "today" | "1d" | "7d" | "30d";

const PERIODS: Array<{ id: PeriodFilter; label: string }> = [
  { id: "today", label: "Сегодня" },
  { id: "1d", label: "1 день" },
  { id: "7d", label: "7 дней" },
  { id: "30d", label: "30 дней" },
];

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

const CALC_TABS: Array<{ id: CalcChannel; label: string }> = [
  { id: "free", label: "Бесплатный канал" },
  { id: "paid", label: "Платная подписка" },
  { id: "bot_signals", label: "Сигналы из бота" },
  { id: "vip", label: "Вип канал" },
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

function cleanForecastText(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text) return "Недостаточно данных для расчёта";
  return text
    .replace(/\s*\(\d+(?:[.,]\d+)?%\)/g, "")
    .replace(/%/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

type LoadForecastsResult = {
  items: TableTennisForecastItem[];
  only_resolved?: boolean;
  forecast_purchase_url?: string;
};

async function loadAllForecasts(params: {
  channel: CalcChannel;
  date_from?: string;
  date_to?: string;
}): Promise<LoadForecastsResult> {
  const pageSize = 250;
  const first = await getTableTennisForecasts({
    page: 1,
    page_size: pageSize,
    channel: params.channel,
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

function getForecastOdds(item: TableTennisForecastItem): number {
  if (item.forecast_odds != null && item.forecast_odds > 0) return item.forecast_odds;
  if (item.odds_used != null && item.odds_used > 0) return item.odds_used;
  if (item.pick_side === "home" && item.odds_1 != null && item.odds_1 > 0) return item.odds_1;
  if (item.pick_side === "away" && item.odds_2 != null && item.odds_2 > 0) return item.odds_2;
  if (item.odds_1 != null && item.odds_1 > 0) return item.odds_1;
  if (item.odds_2 != null && item.odds_2 > 0) return item.odds_2;
  return 1.5;
}

export default function StatsCalculator() {
  const [channel, setChannel] = useState<CalcChannel>("paid");
  const [period, setPeriod] = useState<PeriodFilter | null>("7d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [bank, setBank] = useState("10000");
  const [stake, setStake] = useState("100");
  const [items, setItems] = useState<CalcItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(50);
  const [sortByStart, setSortByStart] = useState<"asc" | "desc">("desc");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [onlyResolved, setOnlyResolved] = useState(false);
  const [forecastPurchaseUrl, setForecastPurchaseUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setLoading(true);
      setError(null);
      setPage(1);
      try {
        let from: string | undefined;
        let to: string | undefined;
        if (period) {
          const range = getRange(period);
          from = range.date_from;
          to = range.date_to;
        } else if (dateFrom && dateTo) {
          from = dateFrom;
          to = dateTo;
        } else {
          const range = getRange("7d");
          from = range.date_from;
          to = range.date_to;
        }
        const result = await loadAllForecasts({
          channel,
          date_from: from,
          date_to: to,
        });
        if (cancelled) return;
        const mapped = result.items.map((it) => ({
          ...it,
          selected: it.status === "hit" || it.status === "miss",
        }));
        setItems(mapped);
        setOnlyResolved(Boolean(result.only_resolved));
        setForecastPurchaseUrl(result.forecast_purchase_url ?? null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Не удалось загрузить прогнозы");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [channel, period, dateFrom, dateTo]);

  const bankNum = useMemo(() => {
    const v = parseFloat(bank.replace(",", "."));
    return Number.isFinite(v) && v >= 0 ? v : 0;
  }, [bank]);
  const stakeNum = useMemo(() => {
    const v = parseFloat(stake.replace(",", "."));
    return Number.isFinite(v) && v > 0 ? v : 0;
  }, [stake]);

  const calc = useMemo(() => {
    let cur = bankNum;
    let wins = 0;
    let losses = 0;
    let bets = 0;
    for (const it of items) {
      if (!it.selected) continue;
      if (it.status === "miss") {
        cur -= stakeNum;
        losses += 1;
        bets += 1;
      } else if (it.status === "hit") {
        const kf = getForecastOdds(it);
        cur -= stakeNum;
        cur += stakeNum * kf;
        wins += 1;
        bets += 1;
      }
    }
    return {
      bankStart: bankNum,
      bankFinal: cur,
      profit: cur - bankNum,
      wins,
      losses,
      bets,
    };
  }, [items, bankNum, stakeNum]);

  const sortedItems = useMemo(
    () =>
      [...items].sort((a, b) => {
        const ta = a.starts_at ?? 0;
        const tb = b.starts_at ?? 0;
        return sortByStart === "desc" ? tb - ta : ta - tb;
      }),
    [items, sortByStart],
  );
  const totalPages = Math.max(1, Math.ceil(sortedItems.length / perPage));
  const currentPage = Math.min(page, totalPages);
  const pageItems = useMemo(
    () => sortedItems.slice((currentPage - 1) * perPage, currentPage * perPage),
    [sortedItems, currentPage, perPage],
  );

  const toggleAll = (checked: boolean) => {
    setItems((prev) => prev.map((x) => ({ ...x, selected: checked })));
  };


  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
      <h2 className="text-lg font-semibold text-white mb-2">Калькулятор ставок</h2>
      <p className="text-slate-400 text-sm mb-4">
        Расчет по реальным прогнозам выбранной вкладки. Можно исключать любые события чекбоксами.
      </p>

      {onlyResolved && forecastPurchaseUrl && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 mb-4">
          <Link
            href={forecastPurchaseUrl}
            className="text-amber-200 hover:text-amber-100 font-medium"
          >
            Чтобы увидеть текущие и новые прогнозы — приобретите подписку на аналитику или доступ в VIP канал
          </Link>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-b border-slate-700 pb-2">
        {CALC_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setChannel(tab.id)}
            className={`px-3 py-1.5 rounded-t-md text-sm ${
              channel === tab.id
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
              setDateFrom("");
              setDateTo("");
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
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => {
            setDateFrom(e.target.value);
            setPeriod(null);
          }}
          className="rounded-md bg-slate-800 border border-slate-600 px-2 py-1 text-sm text-slate-200"
        />
        <span className="text-slate-500 self-center">—</span>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => {
            setDateTo(e.target.value);
            setPeriod(null);
          }}
          className="rounded-md bg-slate-800 border border-slate-600 px-2 py-1 text-sm text-slate-200"
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><p className="text-slate-400 text-xs mb-1">Начальный банк</p><p className="text-xl font-semibold text-white">{calc.bankStart.toFixed(2)}</p></div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><p className="text-slate-400 text-xs mb-1">Итоговый банк</p><p className="text-xl font-semibold text-white">{calc.bankFinal.toFixed(2)}</p></div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><p className="text-slate-400 text-xs mb-1">Результат</p><p className={`text-xl font-semibold ${calc.profit >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{calc.profit >= 0 ? "+" : ""}{calc.profit.toFixed(2)}</p></div>
        <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><p className="text-slate-400 text-xs mb-1">Ставок (W/L)</p><p className="text-xl font-semibold text-slate-200">{calc.bets} ({calc.wins}/{calc.losses})</p></div>
      </div>

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
              <span className="text-slate-500">Начальный банк:</span>
              <input
                type="number"
                min={0}
                value={bank}
                onChange={(e) => setBank(e.target.value)}
                className="w-28 rounded bg-slate-800 border border-slate-600 px-2 py-1 text-sm text-slate-200"
              />
            </label>
            <label className="flex items-center gap-2 text-slate-300 text-sm">
              <span className="text-slate-500">Ставка:</span>
              <input
                type="number"
                min={0}
                value={stake}
                onChange={(e) => setStake(e.target.value)}
                className="w-28 rounded bg-slate-800 border border-slate-600 px-2 py-1 text-sm text-slate-200"
              />
            </label>
            <label className="flex items-center gap-2 text-slate-300 text-sm">
              <span className="text-slate-500">На странице:</span>
              <select
                value={perPage}
                onChange={(e) => {
                  setPerPage(Number(e.target.value));
                  setPage(1);
                }}
                className="rounded bg-slate-800 border border-slate-600 text-slate-200 px-2 py-1 text-sm"
              >
                {PER_PAGE_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
            <div className="flex gap-2">
              <button type="button" onClick={() => toggleAll(true)} className="px-3 py-1.5 rounded border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">Отметить все</button>
              <button type="button" onClick={() => toggleAll(false)} className="px-3 py-1.5 rounded border border-slate-700 bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">Снять все</button>
            </div>
          </div>
        </div>
      </section>

      {loading && <p className="text-slate-400 text-sm">Загрузка прогнозов…</p>}
      {error && <p className="text-rose-400 text-sm">{error}</p>}
      {!loading && !error && (
        <>
          <div className="rounded-lg border border-slate-700 bg-slate-800/40 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs sm:text-sm">
                <thead>
                  <tr className="border-b border-slate-700 bg-slate-800/80 text-slate-300">
                  <th className="px-4 py-3 text-left font-medium" />
                  <th className="px-4 py-3 text-left font-medium">Матч</th>
                  <th
                    className="px-4 py-3 text-left font-medium cursor-pointer hover:text-white select-none"
                    onClick={() => setSortByStart((d) => (d === "desc" ? "asc" : "desc"))}
                    title="Сортировка по дате и времени начала матча"
                  >
                    Начало {sortByStart === "desc" ? "↓" : "↑"}
                  </th>
                  <th className="px-4 py-3 text-left font-medium">Прогноз</th>
                  <th className="px-4 py-3 text-left font-medium">Кф для расчёта</th>
                  <th className="px-4 py-3 text-left font-medium">Статус</th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((it, idx) => (
                    <tr key={`${it.id ?? it.event_id}-${(currentPage - 1) * perPage + idx}`} className="border-b border-slate-700/60">
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={it.selected}
                          onChange={() =>
                            setItems((prev) =>
                              prev.map((x) => (x === it ? { ...x, selected: !x.selected } : x)),
                            )
                          }
                          className="h-4 w-4 rounded border-slate-600 bg-slate-800"
                        />
                      </td>
                      <td className="px-4 py-3 text-slate-200">{it.home_name} — {it.away_name}</td>
                      <td className="px-4 py-3 text-slate-400 whitespace-nowrap">{formatDateTime(it.starts_at)}</td>
                      <td className="px-4 py-3 text-slate-300">{cleanForecastText(it.forecast_text)}</td>
                      <td className="px-4 py-3 text-slate-300 tabular-nums">{getForecastOdds(it).toFixed(2)}</td>
                      <td className="px-4 py-3">
                        {it.status === "hit" ? <span className="text-emerald-400">Угадан</span> :
                         it.status === "miss" ? <span className="text-rose-400">Не угадан</span> :
                         <span className="text-slate-500">{it.status}</span>}
                      </td>
                    </tr>
                ))}
                </tbody>
              </table>
            </div>
          </div>
          {totalPages > 1 && (
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Назад
              </button>
              <span className="text-slate-400 text-xs md:text-sm">
                Страница {currentPage} из {totalPages} · событий {sortedItems.length}
              </span>
              <button
                type="button"
                className="rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 disabled:opacity-50"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Вперёд
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

