"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchMatches, type Match } from "@/lib/api";
import { MatchTable } from "@/components/MatchTable";

export default function UpcomingPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchMatches("matches/upcoming");
        if (!cancelled) setMatches(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
  }, []);

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
