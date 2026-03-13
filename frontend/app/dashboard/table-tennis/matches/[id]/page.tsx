"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getTableTennisMatchCardV2, type TableTennisMatchCardV2 } from "@/lib/api";

function formatDateTime(ts: number | undefined): string {
  if (ts == null) return "—";
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function formatMatchStatus(status: string | null | undefined): string {
  if (!status) return "—";
  if (status === "scheduled") return "Ожидается";
  if (status === "live") return "В игре";
  if (status === "finished") return "Завершен";
  if (status === "cancelled") return "Отменен";
  if (status === "postponed") return "Перенесен";
  return status;
}

function matchStatusClass(status: string | null | undefined): string {
  if (status === "finished") return "text-emerald-400";
  if (status === "live") return "text-sky-300";
  if (status === "cancelled") return "text-amber-300";
  if (status === "postponed") return "text-amber-300";
  if (status === "scheduled") return "text-sky-300";
  return "text-white";
}

function toSignalLevel(value: number | null | undefined): string {
  if (value == null) return "умеренный";
  if (value >= 75) return "очень сильный";
  if (value >= 65) return "сильный";
  if (value >= 55) return "рабочий";
  return "осторожный";
}

function toEdgeLevel(value: number | null | undefined): string {
  if (value == null) return "умеренный перевес";
  if (value >= 10) return "заметный перевес";
  if (value >= 5) return "хороший перевес";
  if (value >= 2) return "небольшой перевес";
  return "минимальный перевес";
}

function buildHumanSummary(card: TableTennisMatchCardV2 | null): string {
  const forecast = card?.forecast_v2;
  if (!forecast?.forecast_text) return "По этому матчу пока недостаточно подтвержденных данных для понятного вывода.";
  const confidence = toSignalLevel(forecast.probability_pct ?? forecast.confidence_score ?? forecast.confidence_pct ?? null);
  const edge = toEdgeLevel(forecast.edge_pct ?? null);
  return `Модель видит ${edge} и дает ${confidence} сигнал в пользу исхода «${forecast.forecast_text}».`;
}

function factorToHumanText(
  factor: NonNullable<NonNullable<TableTennisMatchCardV2["forecast_v2"]>["factors"]>[number]
): string {
  const key = factor.factor_key || "";
  const dir = (factor.direction || "neutral") as "home" | "away" | "neutral";
  const strong = Math.abs(Number(factor.contribution ?? 0)) >= 0.1;

  const sideText = dir === "home" ? "П1" : dir === "away" ? "П2" : "";

  if (key === "form_delta") {
    if (!sideText) return "По форме за последние 90 дней явного преимущества ни у одной стороны нет.";
    return strong
      ? `${sideText} заметно лучше по форме за последние 90 дней.`
      : `${sideText} немного лучше по форме за последние 90 дней.`;
  }

  if (key === "h2h_home_wr") {
    if (!sideText) return "По очным встречам явного преимущества нет.";
    return strong
      ? `${sideText} имеет явное преимущество по очным встречам.`
      : `${sideText} чуть лучше по очным встречам.`;
  }

  if (key === "fatigue_delta") {
    if (!sideText) return "По усталости серьёзного перекоса нет.";
    return strong
      ? `${sideText} заметно свежее по усталости к этому матчу.`
      : `${sideText} немного свежее по усталости.`;
  }

  // Fallback для любых новых факторов
  if (!sideText) return "Дополнительный фактор без явного перекоса.";
  return strong
    ? `${sideText} имеет заметное преимущество по дополнительному фактору.`
    : `${sideText} чуть лучше по дополнительному фактору.`;
}

type FormItem = NonNullable<
  NonNullable<NonNullable<TableTennisMatchCardV2["player_context"]>["home"]>["last5_form"]
>[number];

function renderFormBadges(form: FormItem[] | undefined) {
  if (!form || form.length === 0) {
    return <span className="text-slate-500 text-xs">Нет данных по последним матчам</span>;
  }
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {form.map((item, idx) => {
        const isWin = item.result === "W";
        return (
          <Link
            key={`${item.event_id}-${idx}`}
            href={`/dashboard/table-tennis/matches/${encodeURIComponent(item.event_id)}`}
            className={
              isWin
                ? "inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 text-[11px] font-semibold px-1.5 hover:bg-emerald-500/30"
                : "inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-rose-500/20 border border-rose-400/40 text-rose-300 text-[11px] font-semibold px-1.5 hover:bg-rose-500/30"
            }
            title={`${isWin ? "Победа" : "Поражение"}${item.opponent_name ? ` vs ${item.opponent_name}` : ""}${item.sets_score ? ` · ${item.sets_score}` : ""}`}
          >
            {item.result}
          </Link>
        );
      })}
    </div>
  );
}

export default function TableTennisMatchCardPage() {
  const params = useParams();
  const id = typeof params.id === "string" ? params.id : "";
  const [card, setCard] = useState<TableTennisMatchCardV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTableTennisMatchCardV2(id)
      .then((res) => !cancelled && setCard(res))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "Ошибка загрузки"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) return <div className="p-6 md:p-8"><p className="text-slate-400">Загрузка…</p></div>;
  if (error) return <div className="p-6 md:p-8"><p className="text-rose-400">{error}</p></div>;
  if (!card?.match) return <div className="p-6 md:p-8"><p className="text-slate-400">Матч не найден.</p></div>;

  const m = card.match;
  const f2 = card.forecast_v2;
  const homeCtx = card.player_context?.home;
  const awayCtx = card.player_context?.away;
  const h2h = card.player_context?.h2h;
  const setsLine = m.sets
    ? Object.keys(m.sets)
        .sort((a, b) => Number(a) - Number(b))
        .map((k) => {
          const s = m.sets?.[k];
          if (!s || (s.home == null && s.away == null)) return null;
          return `${s.home ?? ""}-${s.away ?? ""}`;
        })
        .filter(Boolean)
        .join(" ")
    : "";

  const analyticsLocked = card.forecast_locked ?? false;

  return (
    <div className="p-6 md:p-8 space-y-8">
      <div>
        <Link href="/dashboard/table-tennis/line" className="text-slate-400 hover:text-white text-sm mb-2 inline-block">← Линия</Link>
        <h1 className="font-display text-2xl font-bold text-white">{m.home_name} — {m.away_name}</h1>
        <p className="text-slate-400 text-sm mt-1">{m.league_name} · {formatDateTime(m.time)}</p>
      </div>

      {analyticsLocked && card.forecast_purchase_url && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3">
          <Link href={card.forecast_purchase_url} className="text-amber-200 hover:text-amber-100 font-medium">
            {card.forecast_locked_message ?? "Для просмотра аналитики и статистики приобретите подписку на аналитику"}
          </Link>
        </div>
      )}

      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Статистика матча</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Статус</span><p className={`font-semibold ${matchStatusClass(m.status)}`}>{formatMatchStatus(m.status)}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Кф П1 / П2 (старт)</span><p className="text-white font-semibold tabular-nums">{m.odds_1 != null ? m.odds_1.toFixed(2) : "—"} / {m.odds_2 != null ? m.odds_2.toFixed(2) : "—"}</p></div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3"><span className="text-slate-400 text-sm">Счёт по сетам</span><p className="text-emerald-300 font-semibold tabular-nums">{m.sets_score ?? "—"}</p>{setsLine ? <p className="text-xs text-slate-400">({setsLine})</p> : null}</div>
          {!analyticsLocked && (
            <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
              <span className="text-slate-400 text-sm">Прематч‑прогноз</span>
              <p className="text-emerald-300 font-semibold text-sm mt-0.5">
                {f2?.forecast_text ?? "—"}
              </p>
              {f2?.probability_pct != null && (
                <p className="text-xs text-slate-400 mt-1">
                  Вероятность модели: {f2.probability_pct.toFixed(1)}%
                </p>
              )}
              {f2?.edge_pct != null && (
                <p className="text-xs text-slate-400 mt-1">
                  Edge: {f2.edge_pct.toFixed(2)}% · Кф: {f2.odds_used != null ? f2.odds_used.toFixed(2) : "—"}
                </p>
              )}
            </div>
          )}
        </div>
      </section>

      {!analyticsLocked && (
      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">Игроки</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-2">
              <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(m.home_id)}`} className="hover:text-emerald-200">{m.home_name}</Link>
            </p>
            <p className="text-slate-300 text-sm">
              До этого матча: {homeCtx?.wins ?? 0}-{homeCtx?.losses ?? 0} (winrate {homeCtx?.win_rate != null ? `${homeCtx.win_rate.toFixed(1)}%` : "—"}).
            </p>
            <div className="mt-2">
              <p className="text-slate-400 text-xs mb-1">Форма (последние 5):</p>
              {renderFormBadges(homeCtx?.last5_form)}
            </div>
            <p className="text-slate-400 text-xs mt-1">Побед в очных встречах с соперником: {homeCtx?.h2h_wins ?? 0}</p>
          </div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-2">
              <Link href={`/dashboard/table-tennis/players/${encodeURIComponent(m.away_id)}`} className="hover:text-emerald-200">{m.away_name}</Link>
            </p>
            <p className="text-slate-300 text-sm">
              До этого матча: {awayCtx?.wins ?? 0}-{awayCtx?.losses ?? 0} (winrate {awayCtx?.win_rate != null ? `${awayCtx.win_rate.toFixed(1)}%` : "—"}).
            </p>
            <div className="mt-2">
              <p className="text-slate-400 text-xs mb-1">Форма (последние 5):</p>
              {renderFormBadges(awayCtx?.last5_form)}
            </div>
            <p className="text-slate-400 text-xs mt-1">Побед в очных встречах с соперником: {awayCtx?.h2h_wins ?? 0}</p>
          </div>
        </div>
        <p className="text-slate-400 text-xs mt-2">
          Очные встречи до старта этого матча: {h2h?.home_wins ?? 0}-{h2h?.away_wins ?? 0} (всего {h2h?.total ?? 0}).
        </p>
        <div className="mt-2 rounded-lg bg-slate-900/50 border border-slate-700/50 px-3 py-2">
          <p className="text-slate-300 text-xs">
            Мини-таймлайн формы: слева более недавние матчи. Зеленый `W` — победа, красный `L` — поражение.
          </p>
        </div>
      </section>
      )}

      {!analyticsLocked && (
      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">
          V2 Explainability
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <span className="text-slate-400 text-sm">Краткое обоснование</span>
            <p className="text-slate-200 text-sm mt-1">
              {buildHumanSummary(card)}
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <p className="text-white font-semibold mb-1">Что повлияло на выбор</p>
            {f2?.factors && f2.factors.length > 0 ? (
              <ul className="space-y-2 text-xs text-slate-200">
                {f2.factors.map((factor) => (
                  <li key={`${factor.factor_key}-${factor.rank}`}>
                    {factorToHumanText(factor)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-slate-500 text-xs">Пояснения модели пока не доступны.</p>
            )}
          </div>
        </div>
      </section>
      )}

      {!analyticsLocked && card.ml_analytics && (
      <section>
        <h2 className="text-lg font-semibold text-white mb-3 border-b border-slate-700 pb-2">
          ML‑аналитика
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
            <span className="text-slate-400 text-sm">Вероятности (П1)</span>
            <p className="text-white font-semibold tabular-nums mt-0.5">
              Матч: {(card.ml_analytics.p_match * 100).toFixed(1)}% · Сет1: {(card.ml_analytics.p_set1 * 100).toFixed(1)}% · Сет2: {(card.ml_analytics.p_set2 * 100).toFixed(1)}%
            </p>
            <p className="text-xs text-slate-500 mt-1">
              {card.ml_analytics.model_used ? "XGBoost + Monte Carlo" : "Monte Carlo"}
            </p>
          </div>
          {card.ml_analytics.features && (
            <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
              <span className="text-slate-400 text-sm">Фичи (Elo, форма, усталость, H2H)</span>
              <ul className="text-xs text-slate-200 mt-1 space-y-0.5">
                <li>Elo: {card.ml_analytics.features.elo_p1.toFixed(0)} vs {card.ml_analytics.features.elo_p2.toFixed(0)} (Δ {card.ml_analytics.features.elo_diff > 0 ? "+" : ""}{card.ml_analytics.features.elo_diff})</li>
                <li>Форма: {card.ml_analytics.features.form_diff > 0 ? "+" : ""}{card.ml_analytics.features.form_diff.toFixed(3)}</li>
                <li>Усталость: {card.ml_analytics.features.fatigue_diff > 0 ? "+" : ""}{card.ml_analytics.features.fatigue_diff}</li>
                <li>H2H: {card.ml_analytics.features.h2h_count} матчей{card.ml_analytics.features.h2h_p1_wr != null ? ` · WR П1: ${(card.ml_analytics.features.h2h_p1_wr * 100).toFixed(1)}%` : ""}</li>
                <li>Выборка: {card.ml_analytics.features.sample_size} матчей</li>
              </ul>
            </div>
          )}
          {card.ml_analytics.value_signals && card.ml_analytics.value_signals.length > 0 && (
            <div className="rounded-lg bg-slate-800/80 border border-slate-700/60 px-4 py-3">
              <span className="text-slate-400 text-sm">Value‑сигналы</span>
              <ul className="text-xs text-slate-200 mt-1 space-y-1">
                {card.ml_analytics.value_signals.map((s, i) => (
                  <li key={i}>
                    {s.market} {s.side}: кф {s.odds.toFixed(2)}, p={((s.probability ?? 0) * 100).toFixed(1)}%, EV {((s.ev ?? 0) * 100).toFixed(1)}%
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        {!card.ml_analytics.features && (
          <p className="text-slate-500 text-xs mt-2">Фичи не рассчитаны (игроки не в ML‑базе или недостаточно истории).</p>
        )}
      </section>
      )}
    </div>
  );
}

