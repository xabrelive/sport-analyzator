"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  fetchSignalsStats,
  fetchMatches,
  type Match,
  type SignalStatsResponse,
} from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { getSportBySlug } from "@/lib/sports";
import { useSubscription } from "@/contexts/SubscriptionContext";

const TOP_LINE = 6;
const TOP_LIVE = 6;

function isToday(iso: string): boolean {
  const d = new Date(iso);
  const now = new Date();
  return d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
}

export default function SportPage() {
  const params = useParams();
  const sportSlug = params.sport as string;
  const sport = getSportBySlug(sportSlug);
  const [stats, setStats] = useState<SignalStatsResponse | null>(null);
  const [lineMatches, setLineMatches] = useState<Match[]>([]);
  const [liveMatches, setLiveMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const { hasFullAccess } = useSubscription();

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const [statsRes, upcomingRes, liveRes] = await Promise.all([
          fetchSignalsStats(7),
          fetchMatches("matches/upcoming", { limit: 100 }),
          fetchMatches("matches/live"),
        ]);
        if (cancelled) return;
        setStats(statsRes);
        const todayLine = upcomingRes.filter((m) => isToday(m.start_time)).slice(0, TOP_LINE);
        setLineMatches(todayLine.length > 0 ? todayLine : upcomingRes.slice(0, TOP_LINE));
        setLiveMatches(liveRes.slice(0, TOP_LIVE));
      } catch {
        if (!cancelled) setStats(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const t = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [sport?.available]);

  if (!sport) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-8">
        <p className="text-rose-400">Вид спорта не найден</p>
        <Link href="/sports" className="text-teal-400 hover:underline mt-2 inline-block">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  if (!sport.available) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-12">
        <h1 className="text-2xl font-bold text-white mb-2">{sport.name}</h1>
        <p className="text-slate-400 mb-6">Раздел в разработке. Скоро здесь появится статистика и матчи.</p>
        <Link href="/sports" className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-bold text-white mb-1">{sport.name}</h1>
      <p className="text-slate-500 text-sm mb-6">
        Основная статистика по сигналам и аналитике, топ матчей в линии и лайве на сегодня.
      </p>

      {/* Статистика по сигналам и аналитике */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <h2 className="text-lg font-semibold text-white mb-4">Статистика за 7 дней</h2>
        {loading ? (
          <p className="text-slate-500">Загрузка...</p>
        ) : stats ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-lg bg-slate-800/80 p-4 text-center">
              <p className="text-2xl font-bold text-white">{stats.total}</p>
              <p className="text-slate-400 text-sm">Сигналов</p>
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
          <p className="text-slate-500">Не удалось загрузить статистику</p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Link
            href="/signals"
            className="text-sm text-teal-400 hover:text-teal-300"
          >
            Все сигналы →
          </Link>
          <Link
            href="/dashboard"
            className="text-sm text-teal-400 hover:text-teal-300"
          >
            Дашборд →
          </Link>
        </div>
      </section>

      {/* Топ матчей в линии сегодня */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">В линии сегодня</h2>
          <Link href="/line" className="text-sm text-teal-400 hover:text-teal-300">
            Вся линия →
          </Link>
        </div>
        <p className="text-slate-500 text-sm mb-4">
          Матчи на сегодня, на которые стоит обратить внимание.
        </p>
        {loading ? (
          <p className="text-slate-500">Загрузка...</p>
        ) : lineMatches.length === 0 ? (
          <p className="text-slate-500 py-4">Нет предстоящих матчей на сегодня</p>
        ) : (
          <div className="space-y-2">
            {lineMatches.map((m) => (
              <MatchCard
                key={m.id}
                match={m}
                showOdds
                compact
                showStartsIn
                showAnalyticsBlur={!hasFullAccess}
              />
            ))}
          </div>
        )}
      </section>

      {/* Топ матчей в лайве */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Сейчас в лайве</h2>
          <Link href="/live" className="text-sm text-teal-400 hover:text-teal-300">
            Весь лайв →
          </Link>
        </div>
        <p className="text-slate-500 text-sm mb-4">
          Текущие матчи в прямом эфире.
        </p>
        {loading ? (
          <p className="text-slate-500">Загрузка...</p>
        ) : liveMatches.length === 0 ? (
          <p className="text-slate-500 py-4">Нет матчей в прямом эфире</p>
        ) : (
          <div className="space-y-2">
            {liveMatches.map((m) => (
              <MatchCard
                key={m.id}
                match={m}
                compact
                showAnalyticsBlur={!hasFullAccess}
              />
            ))}
          </div>
        )}
      </section>

      <div className="flex flex-wrap gap-2">
        <Link href="/line" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Линия
        </Link>
        <Link href="/live" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Лайв
        </Link>
        <Link href="/results" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Результаты
        </Link>
        <Link href="/signals" className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Сигналы
        </Link>
      </div>
    </main>
  );
}
