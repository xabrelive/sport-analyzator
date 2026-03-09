"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fetchSignals, fetchSignalsStats, type SignalItem, type SignalStatsResponse } from "@/lib/api";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";

const SIGNALS_CACHE_KEY = "view:signals";
const SIGNALS_CACHE_MAX_AGE_MS = 60_000;

export default function SignalsPage() {
  const [signals, setSignals] = useState<SignalItem[]>([]);
  const [stats, setStats] = useState<SignalStatsResponse | null>(null);
  const [loadingSignals, setLoadingSignals] = useState(true);
  const [loadingStats, setLoadingStats] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const isFetchingSignalsRef = useRef(false);
  const fetchSignalsAgainRef = useRef(false);

  const loadSignals = useCallback(async () => {
    if (isFetchingSignalsRef.current) {
      fetchSignalsAgainRef.current = true;
      return;
    }
    isFetchingSignalsRef.current = true;
    try {
      const list = await fetchSignals({ limit: 50, offset: 0 });
      setSignals(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка");
    } finally {
      isFetchingSignalsRef.current = false;
      setLoadingSignals(false);
      if (fetchSignalsAgainRef.current) {
        fetchSignalsAgainRef.current = false;
        void loadSignals();
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoadingStats(true);
    fetchSignalsStats(days)
      .then((d) => { if (!cancelled) setStats(d); })
      .catch(() => { if (!cancelled) setStats(null); })
      .finally(() => { if (!cancelled) setLoadingStats(false); });
    return () => { cancelled = true; };
  }, [days]);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      void loadSignals();
      if (!loadingStats) setLoadingStats(true);
      fetchSignalsStats(days)
        .then((d) => setStats(d))
        .catch(() => setStats(null))
        .finally(() => setLoadingStats(false));
    }
  });

  useEffect(() => {
    const cached = getCached<{
      signals: SignalItem[];
      stats: SignalStatsResponse | null;
      days: number;
    }>(SIGNALS_CACHE_KEY, SIGNALS_CACHE_MAX_AGE_MS);
    if (!cached) return;
    setSignals(cached.signals);
    setStats(cached.stats);
    setDays(cached.days);
    setLoadingSignals(false);
    setLoadingStats(false);
  }, []);

  useEffect(() => {
    void loadSignals();
    const t = setInterval(() => void loadSignals(), 30_000);
    return () => clearInterval(t);
  }, [loadSignals]);

  useEffect(() => {
    if (loadingSignals || loadingStats) return;
    setCached(SIGNALS_CACHE_KEY, { signals, stats, days });
  }, [signals, stats, days, loadingSignals, loadingStats]);

  return (
    <main className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-xl font-bold text-white mb-2">Сигналы</h1>
      <p className="text-slate-500 text-sm mb-6">
        Статистика и список выданных сигналов. Данные только для информации.
      </p>

      {error && <p className="text-rose-400 mb-4">{error}</p>}

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-4">Статистика</h2>
        <div className="flex flex-wrap gap-2 mb-4">
          {[7, 14, 30].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`px-4 py-2 rounded-lg text-sm font-medium ${
                days === d
                  ? "bg-teal-600 text-white"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {d} дней
            </button>
          ))}
        </div>
        {loadingStats ? (
          <p className="text-slate-500 text-sm">Загрузка...</p>
        ) : stats ? (
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
        ) : (
          <p className="text-slate-500 text-sm">Не удалось загрузить статистику</p>
        )}
      </section>

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Последние сигналы</h2>
        {loadingSignals ? (
          <p className="text-slate-500 text-sm">Загрузка...</p>
        ) : signals.length === 0 ? (
          <p className="text-slate-500 text-sm">Сигналов пока нет</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="text-left py-2 pr-3">Дата</th>
                  <th className="text-left py-2 pr-3">Матч</th>
                  <th className="text-left py-2 pr-3">Рынок / исход</th>
                  <th className="text-left py-2">Результат</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.id} className="border-b border-slate-700/60">
                    <td className="py-2 pr-3 text-slate-400">
                      {s.created_at ? new Date(s.created_at).toLocaleString("ru-RU") : "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <Link
                        href={`/match/${s.match_id}`}
                        className="text-teal-400 hover:underline"
                      >
                        Матч
                      </Link>
                    </td>
                    <td className="py-2 pr-3 text-slate-300">
                      {s.market_type} · {s.selection}
                    </td>
                    <td className="py-2 text-slate-300">{s.outcome ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="mt-6 text-slate-500 text-sm">
        <Link href="/stats" className="text-teal-400 hover:underline">
          Подробная статистика по дням →
        </Link>
      </p>
    </main>
  );
}
