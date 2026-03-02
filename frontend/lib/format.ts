"use client";

import type { Match, MatchScore } from "@/lib/api";

/** Счёт по сетам в формате НТ: (7-11 8-11 12-10 4-2*) — текущий сет с * (по is_completed из API). */
export function formatSetScoresTT(scores: MatchScore[] | undefined, isLive: boolean): string {
  if (!scores?.length) return "-";
  const sorted = scores.slice().sort((a, b) => a.set_number - b.set_number);
  const parts = sorted.map((s) => {
    const str = `${s.home_score}-${s.away_score}`;
    const isCurrent = isLive && s.is_completed === false;
    return isCurrent ? `${str}*` : str;
  });
  return `(${parts.join(" ")})`;
}

/** Короткое имя: "Фамилия Им" */
export function shortName(fullName: string): string {
  const parts = fullName.trim().split(/\s+/);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0];
  const first = parts[0];
  const second = parts[1];
  const initial = second.length >= 2 ? second.slice(0, 2) : second[0] ?? "";
  return `${first} ${initial}`;
}

export function scoreBySets(scores: MatchScore[] | undefined): string {
  if (!scores?.length) return "-";
  return scores
    .slice()
    .sort((a, b) => a.set_number - b.set_number)
    .map((s) => `${s.home_score}:${s.away_score}`)
    .join(", ");
}

/** «По сетам» — из API (home_sets_won, away_sets_won); если нет — считаем по завершённым сетам из scores. */
export function setsTotal(match: Match): string {
  if (match.home_sets_won != null && match.away_sets_won != null && (match.home_sets_won > 0 || match.away_sets_won > 0)) {
    return `${match.home_sets_won}:${match.away_sets_won}`;
  }
  if (!match.scores?.length) return "0:0";
  let home = 0;
  let away = 0;
  const sorted = match.scores.slice().sort((a, b) => a.set_number - b.set_number);
  for (const s of sorted) {
    if (s.home_score > s.away_score) home += 1;
    else if (s.away_score > s.home_score) away += 1;
  }
  return `${home}:${away}`;
}

/** Для отображения: список сетов с подписью (завершён/текущий). */
export interface SetDisplayItem {
  set_number: number;
  home_score: number;
  away_score: number;
  isCurrent: boolean;
}

/** Для отображения: список сетов с подписью (завершён/текущий). is_completed из API. */
export function getSetsDisplay(scores: MatchScore[] | undefined, isLive: boolean): SetDisplayItem[] {
  if (!scores?.length) return [];
  const sorted = scores.slice().sort((a, b) => a.set_number - b.set_number);
  return sorted.map((s) => ({
    set_number: s.set_number,
    home_score: s.home_score,
    away_score: s.away_score,
    isCurrent: isLive && s.is_completed === false,
  }));
}

/** Текст «через N ч M мин» до начала матча или время начала, если уже скоро/прошло */
export function formatHoursUntil(iso: string): string {
  const start = new Date(iso).getTime();
  if (Number.isNaN(start)) return "—";
  const now = Date.now();
  const diffMs = start - now;
  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

  if (diffMs <= 0) {
    const d = new Date(iso);
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }
  if (hours >= 1) {
    if (minutes >= 1) return `через ${hours} ч ${minutes} мин`;
    return `через ${hours} ч`;
  }
  if (minutes >= 1) return `через ${minutes} мин`;
  return "менее минуты";
}

/** Время в формате ЧЧ:ММ (только часы и минуты). */
export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

/** Время для истории коэффициентов (модалка). */
export function formatOddsTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatStartTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const dateStr = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
  const timeStr = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${dateStr}, ${timeStr}`;
}

/** Дата и время с годом (для начала/окончания матча). */
export function formatDateTimeWithYear(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const dateStr = d.toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" });
  const timeStr = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${dateStr}, ${timeStr}`;
}

export interface PlayerSetOutcome {
  set_number: number;
  myScore: number;
  oppScore: number;
  won: boolean;
}

export interface PlayerMatchOutcome {
  isWin: boolean;
  opponentName: string;
  opponentId: string | null;
  setsTotal: string;
  sets: PlayerSetOutcome[];
}

/** Исход матча для игрока: данные из API (home_sets_won, away_sets_won, is_completed); счёт по сетам через setsTotal. */
export function getPlayerMatchOutcome(match: Match, playerId: string): PlayerMatchOutcome | null {
  const scores = match.scores?.slice().sort((a, b) => a.set_number - b.set_number) ?? [];
  const isHome = match.home_player?.id === playerId;
  const opponent = isHome ? match.away_player : match.home_player;
  const won = match.result?.winner_id === playerId;
  const totalStr = setsTotal(match);
  const [homeWonStr, awayWonStr] = totalStr.split(":");
  const homeWon = parseInt(homeWonStr ?? "0", 10) || 0;
  const awayWon = parseInt(awayWonStr ?? "0", 10) || 0;
  const mySetWins = isHome ? homeWon : awayWon;
  const oppSetWins = isHome ? awayWon : homeWon;
  const sets: PlayerSetOutcome[] = scores.map((s) => {
    const myScore = isHome ? s.home_score : s.away_score;
    const oppScore = isHome ? s.away_score : s.home_score;
    return {
      set_number: s.set_number,
      myScore,
      oppScore,
      won: s.is_completed === true && myScore > oppScore,
    };
  });
  return {
    isWin: won,
    opponentName: opponent?.name ?? "?",
    opponentId: opponent?.id ?? null,
    setsTotal: `${mySetWins}:${oppSetWins}`,
    sets,
  };
}
