/**
 * Кэш матчей по id. Заполняется при загрузке списков (линия/лайв).
 * При обновлении не подменяем новый счёт старым: пишем в кэш только если данные новее.
 */
import type { Match } from "./api";

const byId = new Map<string, Match>();

/** Прогресс счёта для сравнения (больше = новее по ходу матча). */
function scoreProgress(m: Match): number {
  if (!m.scores?.length) return 0;
  const sorted = m.scores.slice().sort((a, b) => a.set_number - b.set_number);
  return sorted.reduce(
    (acc, s) => acc + s.set_number * 1000 + (s.home_score ?? 0) + (s.away_score ?? 0),
    0
  );
}

/**
 * true, если a «новее» b (можно безопасно заменить b на a).
 * Сначала по updated_at, иначе по прогрессу счёта и статусу finished.
 */
export function isMatchNewerThan(a: Match, b: Match): boolean {
  const aUtc = a.updated_at ? new Date(a.updated_at).getTime() : 0;
  const bUtc = b.updated_at ? new Date(b.updated_at).getTime() : 0;
  if (aUtc && bUtc) return aUtc > bUtc;
  if (aUtc) return true;
  if (bUtc) return false;
  if (a.status === "finished" && b.status !== "finished") return true;
  if (b.status === "finished" && a.status !== "finished") return false;
  return scoreProgress(a) > scoreProgress(b);
}

/** Возвращает тот из двух матчей, который новее (или a при равенстве). */
export function pickNewerMatch(a: Match, b: Match): Match {
  return isMatchNewerThan(b, a) ? b : a;
}

/** Список матчей, где каждый элемент заменён на более новую версию из кэша, если есть. */
export function mergeMatchesWithCache(matches: Match[]): Match[] {
  return matches.map((m) => {
    const cached = byId.get(m.id);
    return cached && isMatchNewerThan(cached, m) ? cached : m;
  });
}

export function getCachedMatch(id: string): Match | null {
  return byId.get(id) ?? null;
}

/** Пишет матчи в кэш, не перезаписывая более новые данные более старыми. */
export function setCachedMatches(matches: Match[]): void {
  for (const m of matches) {
    if (!m?.id) continue;
    const existing = byId.get(m.id);
    if (!existing || isMatchNewerThan(m, existing)) byId.set(m.id, m);
  }
}

export function invalidateMatchIds(ids: string[]): void {
  for (const id of ids) {
    byId.delete(id);
  }
}
