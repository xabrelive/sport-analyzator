"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchMatches, type Match } from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useAuth } from "@/contexts/AuthContext";
import { useSubscription, FREE_LIVE_MATCHES_LIMIT } from "@/contexts/SubscriptionContext";
import { getSportBySlug } from "@/lib/sports";

const MAX_MATCHES = 5;

export default function SportLivePage() {
  const params = useParams();
  const sportSlug = params.sport as string;
  const sport = getSportBySlug(sportSlug);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const connected = useWebSocket();
  const { isAuthenticated } = useAuth();
  const { hasFullAccess } = useSubscription();

  const displayMatches = isAuthenticated && !hasFullAccess
    ? matches.slice(0, FREE_LIVE_MATCHES_LIMIT)
    : matches.slice(0, MAX_MATCHES);
  const hasMoreThanFree = matches.length > FREE_LIVE_MATCHES_LIMIT && isAuthenticated && !hasFullAccess;

  useEffect(() => {
    if (!sport?.available) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const data = await fetchMatches("matches/live");
        if (!cancelled) setMatches(data.slice(0, MAX_MATCHES));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const t = setInterval(load, 5000); // лайв обновляется на бэке каждые 2–3 сек
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
        <p className="text-slate-400 mb-4">Лайв для этого вида спорта пока в разработке.</p>
        <Link href="/sports" className="text-teal-400 hover:underline">
          ← К видам спорта
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <Link href="/sports" className="text-slate-500 hover:text-slate-400 text-sm mb-1 inline-block">
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
              <Link href="/pricing#analytics" className="text-teal-400 hover:underline">Полный лайв по подписке</Link>
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
