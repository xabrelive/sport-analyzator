"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchMatchesLive, type Match } from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuth } from "@/contexts/AuthContext";
import { useSubscription, FREE_LIVE_MATCHES_LIMIT } from "@/contexts/SubscriptionContext";
import { getSportBySlug } from "@/lib/sports";
import { getCached, setCached } from "@/lib/viewCache";
import { setCachedMatches, invalidateMatchIds } from "@/lib/matchCache";
/** Кэш только если свежее 15 сек */
const SPORT_LIVE_CACHE_MAX_AGE_MS = 15_000;

export default function SportLivePage() {
  const params = useParams();
  const sportSlug = params.sport as string;
  const sport = getSportBySlug(sportSlug);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const connected = useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      const ids = Array.isArray(message.match_ids) ? message.match_ids : [];
      if (ids.length) invalidateMatchIds(ids);
      void load();
    }
  });
  const { isAuthenticated } = useAuth();
  const { hasFullAccess } = useSubscription();
  const isFetchingRef = useRef(false);
  const fetchAgainRef = useRef(false);

  const displayMatches =
    isAuthenticated && !hasFullAccess ? matches.slice(0, FREE_LIVE_MATCHES_LIMIT) : matches;
  const hasMoreThanFree =
    matches.length > FREE_LIVE_MATCHES_LIMIT && isAuthenticated && !hasFullAccess;

  const cacheKey = `view:sport:${sportSlug}:live`;

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
      const { live } = await fetchMatchesLive(200);
      const onlyLive = (live ?? []).filter((m) => (m.status || "").toLowerCase() === "live");
      setMatches(onlyLive);
      setCachedMatches(onlyLive);
      setCached<Match[]>(cacheKey, onlyLive);
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

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    const cached = getCached<Match[]>(cacheKey, SPORT_LIVE_CACHE_MAX_AGE_MS);
    if (cached) {
      setMatches(cached);
      setLoading(false);
    }
    void load();
    const t = setInterval(() => void load(), 5000);
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
        <p className="text-slate-400 mb-4">Лайв для этого вида спорта пока в разработке.</p>
        <Link href="/sports" prefetch={false} className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <Link href="/sports" prefetch={false} className="text-slate-500 hover:text-slate-400 text-sm mb-1 inline-block">
            ← Виды спорта
          </Link>
          <h1 className="text-xl font-bold text-white mb-1">Лайв · {sport.name}</h1>
          <p className="text-slate-500 text-sm">Текущий счёт по сетам и очкам</p>
        </div>
        <span className={`text-sm ${connected ? "text-emerald-400" : "text-slate-500"}`}>
          {connected ? "● Online" : "○ Offline"}
        </span>
      </div>
      {error && <p className="text-rose-400 mb-4">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : matches.length === 0 ? (
        <p className="text-slate-500 py-8">Нет матчей в прямом эфире</p>
      ) : (
        <>
          {hasMoreThanFree && (
            <p className="text-slate-400 text-sm mb-3">
              Бесплатно показаны первые {FREE_LIVE_MATCHES_LIMIT} матчей.{" "}
              <Link href="/pricing#analytics" prefetch={false} className="text-teal-400 hover:underline">Полный лайв по подписке</Link>
            </p>
          )}
          <div className="space-y-2">
            {displayMatches.map((m) => (
              <MatchCard key={m.id} match={m} compact showAnalyticsBlur={!hasFullAccess} />
            ))}
          </div>
        </>
      )}
    </main>
  );
}
