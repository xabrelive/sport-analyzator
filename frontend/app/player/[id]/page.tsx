"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchPlayer,
  fetchPlayerStats,
  fetchPlayerMatches,
  type Match,
  type Player as PlayerType,
  type PlayerStats as PlayerStatsType,
} from "@/lib/api";
import { MatchCard } from "@/components/MatchCard";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PlayerMatchResultCard } from "@/components/PlayerMatchResultCard";
import { PlayerStatsBlock } from "@/components/PlayerStatsBlock";

export default function PlayerPage() {
  const params = useParams();
  const id = params?.id as string | undefined;
  const [player, setPlayer] = useState<PlayerType | null>(null);
  const [stats, setStats] = useState<PlayerStatsType | null>(null);
  const [finished, setFinished] = useState<Match[]>([]);
  const [upcoming, setUpcoming] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    Promise.all([
      fetchPlayer(id),
      fetchPlayerStats(id),
      fetchPlayerMatches(id, { status: "finished", limit: 200 }),
      fetchPlayerMatches(id, { status: "scheduled", limit: 100 }),
    ])
      .then(([p, s, fin, upc]) => {
        if (!cancelled) {
          setPlayer(p);
          setStats(s);
          setFinished(fin);
          setUpcoming(upc);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Ошибка");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
  }, [id]);

  if (!id || loading) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-6">
        <p className="text-slate-500">{loading ? "Загрузка..." : "Нет id"}</p>
      </main>
    );
  }
  if (error || !player) {
    return (
      <main className="max-w-4xl mx-auto px-4 py-6">
        <p className="text-rose-400">{error ?? "Игрок не найден"}</p>
        <Link href="/line" className="text-slate-400 hover:text-white mt-2 inline-block">
          ← К линии
        </Link>
      </main>
    );
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-6">
      <Link href="/line" className="text-slate-400 hover:text-white text-sm mb-4 inline-block">
        ← К линии
      </Link>
      <div className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <PlayerAvatar player={player} size="lg" />
          <div>
            <h1 className="text-2xl font-bold text-white">{player.name}</h1>
            {player.country ? (
              <p className="text-slate-500 text-sm mt-0.5">{player.country}</p>
            ) : null}
          </div>
        </div>
        <p className="text-slate-500 text-sm mb-4">Статистика за всё время</p>
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wider">Матчей</div>
              <div className="text-xl font-semibold text-white">{stats.total_matches}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wider">Побед</div>
              <div className="text-xl font-semibold text-emerald-400">{stats.wins}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wider">Поражений</div>
              <div className="text-xl font-semibold text-rose-400">{stats.losses}</div>
            </div>
            <div>
              <div className="text-slate-500 text-xs uppercase tracking-wider">% побед</div>
              <div className="text-xl font-semibold text-white">
                {stats.win_rate != null ? `${(stats.win_rate * 100).toFixed(1)}%` : "–"}
              </div>
            </div>
          </div>
        )}
      </div>

      {stats && (
        <div className="mb-8">
          <PlayerStatsBlock title="Статистика по сетам и порядкам" playerId={null} playerName={player.name} stats={stats} compact={false} />
        </div>
      )}

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-white mb-3">Прошедшие матчи</h2>
        {finished.length === 0 ? (
          <p className="text-slate-500">Нет завершённых матчей</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {finished.map((m) => (
              <PlayerMatchResultCard key={m.id} match={m} playerId={id} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white mb-3">Предстоящие матчи</h2>
        {upcoming.length === 0 ? (
          <p className="text-slate-500">Нет предстоящих матчей</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {upcoming.map((m) => (
              <MatchCard key={m.id} match={m} showOdds />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
