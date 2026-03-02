"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchMatches, type Match } from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { useSubscription } from "@/contexts/SubscriptionContext";
import { getSportBySlug } from "@/lib/sports";

const MAX_MATCHES = 5;

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

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchMatches("matches/upcoming");
        if (!cancelled) setMatches(data.slice(0, MAX_MATCHES));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
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
      <main className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-xl font-bold text-white mb-2">{sport.name}</h1>
        <p className="text-slate-400 mb-4">Линия для этого вида спорта пока в разработке.</p>
        <Link href="/sports" className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  const byLeague = groupByLeague(matches);

  return (
    <main className="max-w-4xl mx-auto px-4 py-5">
      <Link href="/sports" className="text-slate-500 hover:text-slate-400 text-sm mb-1 inline-block">
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
