"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fetchMatchesOverview, type Match } from "@/lib/api";
import { MatchTable } from "@/components/MatchTable";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";
import { setCachedMatches, invalidateMatchIds } from "@/lib/matchCache";

const UPCOMING_CACHE_KEY = "view:upcoming";
/** Кэш только если свежее 60 сек */
const UPCOMING_CACHE_MAX_AGE_MS = 60_000;

export default function UpcomingPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isFetchingRef = useRef(false);
  const fetchAgainRef = useRef(false);

  const load = useCallback(async () => {
    if (isFetchingRef.current) {
      fetchAgainRef.current = true;
      return;
    }
    isFetchingRef.current = true;
    try {
      const { upcoming } = await fetchMatchesOverview({ limit_upcoming: 200, limit_live: 0 });
      setMatches(upcoming);
      setCachedMatches(upcoming);
      setCached<Match[]>(UPCOMING_CACHE_KEY, upcoming);
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
  }, []);

  useWebSocket((message) => {
    if (message?.type === "matches_updated") {
      const ids = Array.isArray(message.match_ids) ? message.match_ids : [];
      if (ids.length) invalidateMatchIds(ids);
      void load();
    }
  });

  useEffect(() => {
    const cached = getCached<Match[]>(UPCOMING_CACHE_KEY, UPCOMING_CACHE_MAX_AGE_MS);
    if (cached) {
      setMatches(cached);
      setLoading(false);
    }
    void load();
    const t = setInterval(() => void load(), 30_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <main className="max-w-6xl mx-auto p-6">
      <header className="border-b border-slate-700 pb-4 mb-6">
        <Link href="/" className="text-slate-400 hover:text-white mb-2 inline-block">
          ← Назад
        </Link>
        <h1 className="text-2xl font-bold text-white">Ближайшие матчи</h1>
      </header>
      {error && <p className="text-rose-400 mb-4">{error}</p>}
      {loading ? (
        <p className="text-slate-500">Загрузка...</p>
      ) : (
        <MatchTable matches={matches} />
      )}
    </main>
  );
}
