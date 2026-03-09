"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMatchesOverview, type Match } from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { getSportBySlug } from "@/lib/sports";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";
import { setCachedMatches, invalidateMatchIds } from "@/lib/matchCache";

const MAX_MATCHES = 5;
/** Кэш только если свежее 60 сек */
const SPORT_LINE_CACHE_MAX_AGE_MS = 60_000;

function groupByLeague(matches: Match[]): Map<string | null, Match[]> {
  const map = new Map<string | null, Match[]>();
  for (const m of matches) {
    const key = m.league?.id ?? null;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  return map;
}

export default function SportLinePage() {
  const params = useParams();
  const sportSlug = params.sport as string;
  const sport = getSportBySlug(sportSlug);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { hasFullAccess } = useSubscription();
  const isFetchingRef = useRef(false);
  const fetchAgainRef = useRef(false);

  const cacheKey = `view:sport:${sportSlug}:line`;

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
      const { upcoming } = await fetchMatchesOverview({ limit_upcoming: 50, limit_live: 0 });
      const limited = upcoming.slice(0, MAX_MATCHES);
      setMatches(limited);
      setCachedMatches(limited);
      setCached<Match[]>(cacheKey, limited);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка загрузки");
    } finally {
      isFetchingRef.current = false;
      setLoading(false);
      if (fetchAgainRef.current) {
        fetchAgainRef.current = false;
        void load();
      }
    }
  }, [cacheKey, sport?.available]);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      const ids = Array.isArray(message.match_ids) ? message.match_ids : [];
      if (ids.length) invalidateMatchIds(ids);
      void load();
    }
  });

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    const cached = getCached<Match[]>(cacheKey, SPORT_LINE_CACHE_MAX_AGE_MS);
    if (cached) {
      setMatches(cached);
      setLoading(false);
    }
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [cacheKey, load, sport?.available]);

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
      <main className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-xl font-bold text-white mb-2">{sport.name}</h1>
        <p className="text-slate-400 mb-4">Линия для этого вида спорта пока в разработке.</p>
        <Link href="/sports" prefetch={false} className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  const byLeague = groupByLeague(matches);

  return (
    <main className="max-w-4xl mx-auto px-4 py-5">
      <Link href="/sports" prefetch={false} className="text-slate-500 hover:text-slate-400 text-sm mb-1 inline-block">
        ← Виды спорта
      </Link>
      <h1 className="text-xl font-bold text-white mb-1">Линия · {sport.name}</h1>
      <p className="text-slate-500 text-sm mb-4">Ближайшие матчи (до 5)</p>
      {error && <p className="text-rose-400 mb-4">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : (
        <div className="space-y-6">
          {Array.from(byLeague.entries()).map(([leagueId, leagueMatches]) => {
            const name = leagueMatches[0]?.league?.name ?? "Без лиги";
            return (
              <section key={leagueId ?? "no-league"}>
                <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                  {name}
                </h2>
                <div className="space-y-2">
                  {leagueMatches.map((m) => (
                    <MatchCard key={m.id} match={m} showOdds compact showAnalyticsBlur={!hasFullAccess} />
                  ))}
                </div>
              </section>
            );
          })}
          {matches.length === 0 && (
            <p className="text-slate-500 py-8">Нет предстоящих матчей</p>
          )}
        </div>
      )}
    </main>
  );
}
