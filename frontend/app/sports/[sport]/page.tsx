"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchMatchesOverview,
  fetchMatchRecommendations,
  fetchRecommendationsStats,
  type Match,
  type RecommendationStatsResponse,
} from "@/lib/api";
import { LineMatchRow } from "@/components/LineMatchRow";
import { MatchCard } from "@/components/MatchCard";
import { getSportBySlug } from "@/lib/sports";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";
import { setCachedMatches, invalidateMatchIds } from "@/lib/matchCache";

/** Slug в URL -> sport_key в API. */
function sportSlugToKey(slug: string): string {
  return slug.replace(/-/g, "_");
}

const UPCOMING_LIMIT = 200;
const LINE_TABLE_MAX = 5;
const LIVE_PREVIEW_MAX = 3;
const SPORT_PAGE_CACHE_MAX_AGE_MS = 60_000;

function hasWinnerOdds(match: Match): boolean {
  const odds = match.odds_snapshots ?? [];
  let hasHome = false;
  let hasAway = false;
  for (const o of odds) {
    const market = (o.market || "").toLowerCase();
    if (market !== "winner" && market !== "win" && market !== "92_1") continue;
    const sel = (o.selection || "").toLowerCase();
    if (sel === "home" || sel === "1") hasHome = true;
    if (sel === "away" || sel === "2") hasAway = true;
  }
  return hasHome && hasAway;
}

function sortMatchesByStart(matches: Match[]): Match[] {
  return [...matches].sort((a, b) => (a.start_time || "").localeCompare(b.start_time || ""));
}

type SportCachePayload = {
  recStats: RecommendationStatsResponse | null;
  lineMatches: Match[];
  liveMatches: Match[];
  modelRecs: Record<string, string | null>;
};

export default function SportPage() {
  const params = useParams();
  const sportSlug = params.sport as string;
  const sport = getSportBySlug(sportSlug);
  const [recStats, setRecStats] = useState<RecommendationStatsResponse | null>(null);
  const [lineMatches, setLineMatches] = useState<Match[]>([]);
  const [liveMatches, setLiveMatches] = useState<Match[]>([]);
  const [modelRecs, setModelRecs] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(true);
  const { hasFullAccess } = useSubscription();
  const isFetchingRef = useRef(false);
  const fetchAgainRef = useRef(false);
  const knownRecIdsRef = useRef<Set<string>>(new Set());

  const cacheKey = `view:sport:${sportSlug}:overview`;

  const loadRecommendationsFor = useCallback(async (items: Match[]) => {
    const missing = items
      .filter(hasWinnerOdds)
      .map((m) => m.id)
      .filter((id) => !knownRecIdsRef.current.has(id));
    if (missing.length === 0) return;
    const recs = await fetchMatchRecommendations(missing);
    const nonNullEntries = Object.entries(recs).filter(([, value]) => Boolean(value));
    if (nonNullEntries.length === 0) return;
    for (const [id] of nonNullEntries) knownRecIdsRef.current.add(id);
    setModelRecs((prev) => ({ ...prev, ...Object.fromEntries(nonNullEntries) }));
  }, []);

  const load = useCallback(async () => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    if (isFetchingRef.current) {
      fetchAgainRef.current = true;
      return;
    }
    isFetchingRef.current = true;
    try {
      const [overview, recStatsRes] = await Promise.all([
        fetchMatchesOverview({ limit_live: LIVE_PREVIEW_MAX * 2, limit_upcoming: UPCOMING_LIMIT }),
        fetchRecommendationsStats({ days: 7, per_page: 1, sport_key: sportSlugToKey(sportSlug) }).catch(() => null),
      ]);
      setRecStats(recStatsRes);
      const upcoming = overview.upcoming ?? [];
      const live = overview.live ?? [];
      const withOdds = upcoming.filter(hasWinnerOdds);
      await loadRecommendationsFor(withOdds);
      setLineMatches(withOdds);
      setLiveMatches(live.slice(0, LIVE_PREVIEW_MAX));
      setCachedMatches([...withOdds, ...live]);
      setCached<SportCachePayload>(cacheKey, {
        recStats: recStatsRes,
        lineMatches: withOdds,
        liveMatches: live.slice(0, LIVE_PREVIEW_MAX),
        modelRecs: {},
      });
    } catch {
      setRecStats(null);
    } finally {
      isFetchingRef.current = false;
      setLoading(false);
      if (fetchAgainRef.current) {
        fetchAgainRef.current = false;
        void load();
      }
    }
  }, [cacheKey, loadRecommendationsFor, sport?.available]);

  const loadMatchesOnly = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    try {
      const { upcoming, live } = await fetchMatchesOverview({ limit_live: LIVE_PREVIEW_MAX * 2, limit_upcoming: UPCOMING_LIMIT });
      await loadRecommendationsFor(upcoming.filter(hasWinnerOdds));
      setLineMatches(upcoming.filter(hasWinnerOdds));
      setLiveMatches((live ?? []).slice(0, LIVE_PREVIEW_MAX));
      setCachedMatches([...upcoming, ...(live ?? [])]);
    } finally {
      isFetchingRef.current = false;
    }
  }, [loadRecommendationsFor]);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      const ids = Array.isArray(message.match_ids) ? message.match_ids : [];
      if (ids.length) invalidateMatchIds(ids);
      void loadMatchesOnly();
    }
  });

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    const cached = getCached<SportCachePayload>(cacheKey, SPORT_PAGE_CACHE_MAX_AGE_MS);
    if (cached) {
      setRecStats(cached.recStats);
      setLineMatches(cached.lineMatches);
      setLiveMatches(cached.liveMatches ?? []);
      setLoading(false);
      if (cached.lineMatches.length > 0) void loadRecommendationsFor(cached.lineMatches);
    }
    void load();
    const t = setInterval(() => void loadMatchesOnly(), 30_000);
    return () => clearInterval(t);
  }, [cacheKey, load, loadMatchesOnly, loadRecommendationsFor, sport?.available]);

  const lineTableRows = useMemo(() => {
    return sortMatchesByStart(lineMatches).slice(0, LINE_TABLE_MAX);
  }, [lineMatches]);

  if (!sport) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-8">
        <p className="text-rose-400">Вид спорта не найден</p>
        <Link href="/sports" prefetch={false} className="text-teal-400 hover:underline mt-2 inline-block">
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
        <Link href="/sports" prefetch={false} className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">{sport.name}</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Статистика прогнозов и сигналов, предстоящие матчи с коэффициентами.
          </p>
        </div>
        <Link
          href="/sports"
          prefetch={false}
          className="text-slate-500 hover:text-slate-400 text-sm shrink-0"
        >
          ← Виды спорта
        </Link>
      </div>

      {/* Основные показатели: статистика и сигналы */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        <div className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5">
          <h2 className="text-base font-semibold text-white mb-3">Статистика прогнозов</h2>
          <p className="text-slate-500 text-xs mb-3">За 7 дней (аналитика матчей)</p>
          {loading && !recStats ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : recStats ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                  <p className="text-xl font-bold text-white">{recStats.total}</p>
                  <p className="text-slate-400 text-xs">Всего</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                  <p className="text-xl font-bold text-emerald-400">{recStats.correct}</p>
                  <p className="text-slate-400 text-xs">Угадано</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                  <p className="text-xl font-bold text-rose-400">{recStats.wrong}</p>
                  <p className="text-slate-400 text-xs">Проиграно</p>
                </div>
                <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                  <p className="text-xl font-bold text-slate-400">{recStats.pending}</p>
                  <p className="text-slate-400 text-xs">Ожидают</p>
                </div>
              </div>
              {recStats.correct + recStats.wrong > 0 && (
                <p className="mt-2 text-slate-400 text-xs">
                  Угадывание: {((recStats.correct / (recStats.correct + recStats.wrong)) * 100).toFixed(0)}%
                </p>
              )}
            </>
          ) : (
            <p className="text-slate-500 text-sm">Нет данных</p>
          )}
        </div>
        <div className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5">
          <h2 className="text-base font-semibold text-white mb-3">Показатели сигналов</h2>
          <p className="text-slate-500 text-xs mb-3">За 7 дней</p>
          {loading && !recStats ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : recStats ? (
            <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                <p className="text-xl font-bold text-white">{recStats.total}</p>
                <p className="text-slate-400 text-xs">Сигналов</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                <p className="text-xl font-bold text-emerald-400">{recStats.correct}</p>
                <p className="text-slate-400 text-xs">Выиграло</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                <p className="text-xl font-bold text-rose-400">{recStats.wrong}</p>
                <p className="text-slate-400 text-xs">Проиграло</p>
              </div>
              <div className="rounded-lg bg-slate-800/80 p-3 text-center">
                <p className="text-xl font-bold text-slate-400">{recStats.pending}</p>
                <p className="text-slate-400 text-xs">Ожидают</p>
              </div>
            </div>
            {recStats.correct + recStats.wrong > 0 && (
              <p className="mt-2 text-slate-400 text-xs">
                Угадывание: {((recStats.correct / (recStats.correct + recStats.wrong)) * 100).toFixed(0)}%
              </p>
            )}
            </>
          ) : (
            <p className="text-slate-500 text-sm">Не удалось загрузить</p>
          )}
        </div>
      </section>

      {/* Кнопки купить — ведут на тарифы */}
      <div className="flex flex-wrap gap-3 mb-8">
        <Link
          href="/pricing"
          prefetch={false}
          className="px-5 py-2.5 rounded-xl bg-teal-600 hover:bg-teal-500 text-white font-medium text-sm transition-colors"
        >
          Купить аналитику
        </Link>
        <Link
          href="/pricing"
          prefetch={false}
          className="px-5 py-2.5 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium text-sm transition-colors"
        >
          Купить сигналы
        </Link>
      </div>

      {/* Предстоящие матчи — только с коэффициентами, обновление по WebSocket */}
      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 overflow-hidden mb-8">
        <div className="px-4 py-3 border-b border-slate-700/80 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Предстоящие матчи</h2>
          <Link href="/line" prefetch={false} className="text-sm text-teal-400 hover:text-teal-300">
            Вся линия →
          </Link>
        </div>
        <div className="overflow-x-auto">
          {loading && lineMatches.length === 0 ? (
            <p className="p-6 text-slate-500">Загрузка...</p>
          ) : lineTableRows.length === 0 ? (
            <p className="p-6 text-slate-500">Нет предстоящих матчей с коэффициентами</p>
          ) : (
            <>
              <p className="px-4 pt-2 text-slate-500 text-xs">Показано до {LINE_TABLE_MAX} ближайших по времени</p>
              <table className="w-full min-w-[640px]">
              <thead>
                <tr className="border-b border-slate-700/80 text-left text-xs text-slate-500 uppercase tracking-wider">
                  <th className="py-2.5 pr-3 font-medium">Время</th>
                  <th className="py-2.5 pr-3 font-medium">П1</th>
                  <th className="py-2.5 pr-2 font-medium text-right">Кф</th>
                  <th className="py-2.5 px-1 font-medium text-center">—</th>
                  <th className="py-2.5 pl-2 font-medium text-left">Кф</th>
                  <th className="py-2.5 pr-3 font-medium text-right">П2</th>
                  <th className="py-2.5 pr-3 font-medium">Вероятность</th>
                  <th className="py-2.5 pl-2 font-medium">Прогноз</th>
                </tr>
              </thead>
              <tbody>
                {lineTableRows.map((m) => (
                  <LineMatchRow
                    key={m.id}
                    match={m}
                    recommendation={modelRecs[m.id] ?? null}
                    showAnalyticsBlur={!hasFullAccess}
                  />
                ))}
              </tbody>
            </table>
            </>
          )}
        </div>
      </section>

      {/* Сейчас в лайве */}
      {liveMatches.length > 0 && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Сейчас в лайве</h2>
            <Link href="/live" prefetch={false} className="text-sm text-teal-400 hover:text-teal-300">
              Весь лайв →
            </Link>
          </div>
          <div className="space-y-2">
            {liveMatches.map((m) => (
              <MatchCard key={m.id} match={m} compact showAnalyticsBlur={!hasFullAccess} />
            ))}
          </div>
        </section>
      )}

      {/* Быстрые ссылки */}
      <div className="flex flex-wrap gap-2">
        <Link href="/line" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Линия
        </Link>
        <Link href="/live" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Лайв
        </Link>
        <Link href="/results" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Результаты
        </Link>
        <Link href="/signals" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Сигналы
        </Link>
        <Link href="/stats" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
          Статистика
        </Link>
      </div>
    </main>
  );
}
