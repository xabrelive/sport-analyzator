"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { fetchFinishedMatches, type Match } from "@/lib/api";
import { MatchTable } from "@/components/MatchTable";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCached, setCached } from "@/lib/viewCache";

const FINISHED_CACHE_KEY = "view:finished";
const FINISHED_CACHE_MAX_AGE_MS = 120_000;

export default function FinishedPage() {
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
      const data = await fetchFinishedMatches({ limit: 200 });
      setMatches(data.items);
      setCached<Match[]>(FINISHED_CACHE_KEY, data.items);
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
    if (message?.type === "matches_updated") void load();
  });

  useEffect(() => {
    const cached = getCached<Match[]>(FINISHED_CACHE_KEY, FINISHED_CACHE_MAX_AGE_MS);
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
        <h1 className="text-2xl font-bold text-white">Завершённые</h1>
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
