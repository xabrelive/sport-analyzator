"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchSignalsStats,
  fetchRecommendationsStats,
  fetchMeAccess,
  fetchMySignals,
  fetchVipChannelStats,
  type SignalStatsResponse,
  type RecommendationStatsResponse,
  type AccessSummaryResponse,
  type MySignalsResponse,
  type VipChannelStatsResponse,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";
import { SPORTS } from "@/lib/sports";

const DASHBOARD_CACHE_KEY = "view:dashboard";
const DASHBOARD_CACHE_MAX_AGE_MS = 60_000;
const STATS_DAYS = 7;

/** Slug в URL -> sport_key в API (table-tennis -> table_tennis). */
function sportSlugToKey(slug: string): string {
  return slug.replace(/-/g, "_");
}

function sportIcon(slug: string): string {
  switch (slug) {
    case "table-tennis":
      return "🏓";
    case "tennis":
      return "🎾";
    case "football":
      return "⚽";
    case "basketball":
      return "🏀";
    case "volleyball":
      return "🏐";
    case "hockey":
      return "🏒";
    default:
      return "📋";
  }
}

type CachedPayload = {
  stats: SignalStatsResponse | null;
  recStats: RecommendationStatsResponse | null;
  recStatsBySport: Record<string, RecommendationStatsResponse | null>;
  access: AccessSummaryResponse | null;
  mySignals: MySignalsResponse | null;
  vipChannel: VipChannelStatsResponse | null;
};

export default function DashboardPage() {
  const [stats, setStats] = useState<SignalStatsResponse | null>(null);
  const [recStats, setRecStats] = useState<RecommendationStatsResponse | null>(null);
  const [recStatsBySport, setRecStatsBySport] = useState<Record<string, RecommendationStatsResponse | null>>({});
  const [access, setAccess] = useState<AccessSummaryResponse | null>(null);
  const [mySignals, setMySignals] = useState<MySignalsResponse | null>(null);
  const [vipChannel, setVipChannel] = useState<VipChannelStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const { isAuthenticated } = useAuth();
  const isFetchingRef = useRef(false);
  const fetchAgainRef = useRef(false);

  const loadData = useCallback(async () => {
    if (isFetchingRef.current) {
      fetchAgainRef.current = true;
      return;
    }
    isFetchingRef.current = true;
    setLoading(true);
    try {
      const availableSports = SPORTS.filter((s) => s.available);
      const [signalsRes, recRes, ...perSportResults] = await Promise.all([
        fetchSignalsStats(STATS_DAYS),
        fetchRecommendationsStats({ days: STATS_DAYS, per_page: 1 }).catch(() => null),
        ...availableSports.map(async (sport) => {
          const data = await fetchRecommendationsStats({
            days: STATS_DAYS,
            per_page: 1,
            sport_key: sportSlugToKey(sport.slug),
          }).catch(() => null);
          return [sport.slug, data] as const;
        }),
      ]);
      setStats(signalsRes);
      setRecStats(recRes);
      setRecStatsBySport(Object.fromEntries(perSportResults));
    } catch {
      setStats(null);
      setRecStats(null);
      setRecStatsBySport({});
    } finally {
      isFetchingRef.current = false;
      setLoading(false);
      if (fetchAgainRef.current) {
        fetchAgainRef.current = false;
        void loadData();
      }
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    Promise.all([
      fetchMeAccess().then((d) => {
        if (!cancelled) setAccess(d);
      }),
      fetchMySignals(30).then((d) => {
        if (!cancelled) setMySignals(d);
      }).catch(() => {
        if (!cancelled) setMySignals(null);
      }),
    ]);
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    let cancelled = false;
    fetchVipChannelStats(STATS_DAYS)
      .then((d) => {
        if (!cancelled) setVipChannel(d);
      })
      .catch(() => {
        if (!cancelled) setVipChannel(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") void loadData();
  });

  useEffect(() => {
    const cached = getCached<CachedPayload>(DASHBOARD_CACHE_KEY, DASHBOARD_CACHE_MAX_AGE_MS);
    if (cached) {
      setStats(cached.stats);
      setRecStats(cached.recStats);
      setRecStatsBySport(cached.recStatsBySport ?? {});
      setAccess(cached.access);
      setMySignals(cached.mySignals);
      setVipChannel(cached.vipChannel);
      setLoading(false);
    }
    void loadData();
    const t = setInterval(() => void loadData(), 30_000);
    return () => clearInterval(t);
  }, [loadData]);

  useEffect(() => {
    if (loading) return;
    setCached(DASHBOARD_CACHE_KEY, { stats, recStats, recStatsBySport, access, mySignals, vipChannel });
  }, [stats, recStats, recStatsBySport, access, mySignals, vipChannel, loading]);

  return (
    <main className="max-w-4xl mx-auto px-4 py-6">
      <h1 className="text-2xl font-bold text-white mb-1">Дашборд</h1>
      <p className="text-slate-500 text-sm mb-8">
        Статистика по видам спорта. Прогнозы и сигналы за {STATS_DAYS} дней. Оформите подписку для полного доступа.
      </p>

      {isAuthenticated && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5 mb-8">
          <h2 className="text-base font-semibold text-white mb-3">Мои подписки</h2>
          {access == null ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-300 text-sm">Аналитика:</span>
                {access.tg_analytics.has ? (
                  <span className="text-emerald-400 text-sm">
                    до {access.tg_analytics.valid_until ?? ""}
                    {access.tg_analytics.scope === "all" ? " · все виды" : ` · ${access.tg_analytics.sport_key ?? "один вид"}`}
                  </span>
                ) : (
                  <span className="text-slate-500 text-sm">нет доступа</span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-300 text-sm">Сигналы:</span>
                {access.signals.has ? (
                  <span className="text-emerald-400 text-sm">
                    до {access.signals.valid_until ?? ""}
                    {access.signals.scope === "all" ? " · все виды" : ` · ${access.signals.sport_key ?? "один вид"}`}
                  </span>
                ) : (
                  <span className="text-slate-500 text-sm">нет доступа</span>
                )}
              </div>
              <Link href="/pricing" prefetch={false} className="text-teal-400 hover:text-teal-300 text-sm font-medium">
                Управление тарифами →
              </Link>
            </div>
          )}
        </section>
      )}

      {isAuthenticated && (
        <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5 mb-8">
          <h2 className="text-base font-semibold text-white mb-3">Мои сигналы</h2>
          <p className="text-slate-500 text-sm mb-3">Что было отправлено вам в личку (TG/почта)</p>
          {mySignals == null ? (
            <p className="text-slate-500 text-sm">Загрузка...</p>
          ) : (
            <div className="grid grid-cols-4 gap-2">
              <div className="text-center">
                <p className="text-lg font-bold text-white">{mySignals.total}</p>
                <p className="text-slate-500 text-xs">всего</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-emerald-400">{mySignals.won}</p>
                <p className="text-slate-500 text-xs">зашло</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-rose-400">{mySignals.lost}</p>
                <p className="text-slate-500 text-xs">не зашло</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-slate-400">{mySignals.pending}</p>
                <p className="text-slate-500 text-xs">ожидают</p>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-5 mb-8">
        <h2 className="text-base font-semibold text-white mb-1">Публикации в платном канале (VIP)</h2>
        <p className="text-slate-500 text-sm mb-4">Сколько отправлено в канал, сколько сыграло за последние {STATS_DAYS} дней</p>
        {vipChannel == null ? (
          <p className="text-slate-500 text-sm">Загрузка...</p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <div className="text-center rounded-lg bg-slate-800/50 py-3 px-2">
              <p className="text-xl font-bold text-white">{vipChannel.total}</p>
              <p className="text-slate-500 text-xs">отправлено</p>
            </div>
            <div className="text-center rounded-lg bg-slate-800/50 py-3 px-2">
              <p className="text-xl font-bold text-emerald-400">{vipChannel.won}</p>
              <p className="text-slate-500 text-xs">зашло</p>
            </div>
            <div className="text-center rounded-lg bg-slate-800/50 py-3 px-2">
              <p className="text-xl font-bold text-rose-400">{vipChannel.lost}</p>
              <p className="text-slate-500 text-xs">не зашло</p>
            </div>
            <div className="text-center rounded-lg bg-slate-800/50 py-3 px-2">
              <p className="text-xl font-bold text-slate-400">{vipChannel.pending}</p>
              <p className="text-slate-500 text-xs">в игре</p>
            </div>
            <div className="text-center rounded-lg bg-slate-800/50 py-3 px-2">
              <p className="text-xl font-bold text-slate-500">{vipChannel.missed ?? 0}</p>
              <p className="text-slate-500 text-xs">отмена / нет данных</p>
            </div>
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-4">По видам спорта</h2>
        <div className="space-y-6">
          {SPORTS.map((sport) => {
            const available = sport.available;
            return (
              <article
                key={sport.slug}
                className={`rounded-xl border bg-slate-900/60 overflow-hidden ${
                  available ? "border-slate-700/80" : "border-slate-700/50 opacity-80"
                }`}
              >
                <div className="p-4 flex flex-wrap items-center gap-4">
                  <span className="text-3xl" aria-hidden>
                    {sportIcon(sport.slug)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <h3 className="text-lg font-semibold text-white">{sport.name}</h3>
                    {!available && (
                      <p className="text-slate-500 text-sm mt-0.5">В разработке</p>
                    )}
                  </div>
                  {available && (
                    <Link
                      href={`/sports/${sport.slug}`}
                      prefetch={false}
                      className="shrink-0 px-4 py-2 rounded-xl bg-slate-700 text-slate-200 hover:bg-slate-600 text-sm font-medium"
                    >
                      Открыть
                    </Link>
                  )}
                </div>

                {available && (
                  <>
                    <div className="px-4 pb-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div className="rounded-lg border border-slate-700/80 bg-slate-800/50 p-4">
                        <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                          Статистика прогнозов ({STATS_DAYS} дн.)
                        </p>
                        {loading && !recStatsBySport[sport.slug] && !recStats ? (
                          <p className="text-slate-500 text-sm">Загрузка...</p>
                        ) : (recStatsBySport[sport.slug] ?? recStats) ? (
                          (() => {
                            const s = recStatsBySport[sport.slug] ?? recStats!;
                            return (
                              <div className="grid grid-cols-4 gap-2">
                                <div className="text-center">
                                  <p className="text-lg font-bold text-white">{s.total}</p>
                                  <p className="text-slate-500 text-xs">всего</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-emerald-400">{s.correct}</p>
                                  <p className="text-slate-500 text-xs">угадано</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-rose-400">{s.wrong}</p>
                                  <p className="text-slate-500 text-xs">проиграно</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-slate-400">{s.pending}</p>
                                  <p className="text-slate-500 text-xs">ожидают</p>
                                </div>
                              </div>
                            );
                          })()
                        ) : (
                          <p className="text-slate-500 text-sm">Нет данных</p>
                        )}
                      </div>
                      <div className="rounded-lg border border-slate-700/80 bg-slate-800/50 p-4">
                        <p className="text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
                          Показатели сигналов ({STATS_DAYS} дн.)
                        </p>
                        {loading && !recStatsBySport[sport.slug] && !recStats ? (
                          <p className="text-slate-500 text-sm">Загрузка...</p>
                        ) : (recStatsBySport[sport.slug] ?? recStats) ? (
                          (() => {
                            const s = recStatsBySport[sport.slug] ?? recStats!;
                            return (
                              <div className="grid grid-cols-4 gap-2">
                                <div className="text-center">
                                  <p className="text-lg font-bold text-white">{s.total}</p>
                                  <p className="text-slate-500 text-xs">сигналов</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-emerald-400">{s.correct}</p>
                                  <p className="text-slate-500 text-xs">выиграло</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-rose-400">{s.wrong}</p>
                                  <p className="text-slate-500 text-xs">проиграло</p>
                                </div>
                                <div className="text-center">
                                  <p className="text-lg font-bold text-slate-400">{s.pending}</p>
                                  <p className="text-slate-500 text-xs">ожидают</p>
                                </div>
                              </div>
                            );
                          })()
                        ) : (
                          <p className="text-slate-500 text-sm">Не удалось загрузить</p>
                        )}
                      </div>
                    </div>

                    <div className="px-4 pb-4 flex flex-wrap gap-3">
                      <Link
                        href="/pricing"
                        prefetch={false}
                        className="px-4 py-2 rounded-xl bg-teal-600 hover:bg-teal-500 text-white font-medium text-sm transition-colors"
                      >
                        Купить аналитику
                      </Link>
                      <Link
                        href="/pricing"
                        prefetch={false}
                        className="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-200 font-medium text-sm transition-colors"
                      >
                        Купить сигналы
                      </Link>
                    </div>
                  </>
                )}

                {!available && (
                  <div className="px-4 pb-4 flex flex-wrap gap-3">
                    <Link
                      href="/pricing"
                      prefetch={false}
                      className="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 font-medium text-sm transition-colors"
                    >
                      Купить аналитику
                    </Link>
                    <Link
                      href="/pricing"
                      prefetch={false}
                      className="px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-slate-300 font-medium text-sm transition-colors"
                    >
                      Купить сигналы
                    </Link>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">Разделы</h2>
        <div className="flex flex-wrap gap-2">
          <Link href="/sports" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Виды спорта
          </Link>
          <Link href="/line" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Линия
          </Link>
          <Link href="/live" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Лайв
          </Link>
          <Link href="/stats" prefetch={false} className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 hover:bg-slate-700 text-sm">
            Статистика
          </Link>
        </div>
      </section>
    </main>
  );
}
