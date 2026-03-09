"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  fetchRecommendationsStats,
  type RecommendationStatsItem,
} from "@/lib/api";

type CalcItem = RecommendationStatsItem & { selected: boolean };

function formatMatchStart(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function BetsCalculatorPage() {
  const [days, setDays] = useState(30);
  const [stake, setStake] = useState<string>("100");
  const [initialBank, setInitialBank] = useState<string>("10000");
  const [items, setItems] = useState<CalcItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRecommendationsStats({
      page: 1,
      per_page: 100,
      days,
      result_filter: "all",
    })
      .then((data) => {
        if (cancelled) return;
        const mapped: CalcItem[] = (data.items || []).map((it) => ({
          ...it,
          selected: it.correct !== null && it.odds_at_recommendation != null,
        }));
        setItems(mapped);
      })
      .catch(() => {
        if (!cancelled) setError("Не удалось загрузить список прогнозов");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const stakeNum = useMemo(() => {
    const v = parseFloat(stake.replace(",", "."));
    return Number.isFinite(v) && v > 0 ? v : 0;
  }, [stake]);

  const initialBankNum = useMemo(() => {
    const v = parseFloat(initialBank.replace(",", "."));
    return Number.isFinite(v) && v >= 0 ? v : 0;
  }, [initialBank]);

  const calc = useMemo(() => {
    let bank = initialBankNum;
    let used = 0;
    let wins = 0;
    let losses = 0;

    if (stakeNum <= 0 || items.length === 0) {
      return { bankStart: initialBankNum, bankFinal: bank, profit: 0, used, wins, losses };
    }

    for (const it of items) {
      if (!it.selected) continue;
      if (it.correct === true && it.odds_at_recommendation != null) {
        used += stakeNum;
        wins += 1;
        bank += stakeNum * (it.odds_at_recommendation - 1);
      } else if (it.correct === false) {
        used += stakeNum;
        losses += 1;
        bank -= stakeNum;
      }
    }

    return {
      bankStart: initialBankNum,
      bankFinal: bank,
      profit: bank - initialBankNum,
      used,
      wins,
      losses,
    };
  }, [items, stakeNum, initialBankNum]);

  const toggleAll = (value: boolean) => {
    setItems((prev) => prev.map((it) => ({ ...it, selected: value })));
  };

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-white">Калькулятор ставок</h1>
        <Link
          href="/stats"
          className="text-sm text-teal-400 hover:text-teal-300 hover:underline"
        >
          ← Назад к статистике
        </Link>
      </div>
      <p className="text-slate-400 text-sm mb-6">
        Калькулятор по сохранённым рекомендациям (линия и лайв). Можно задать
        размер банка и фиксированную ставку на каждый прогноз, а также выбрать,
        какие прогнозы учитывать.
      </p>

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6 mb-8">
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <div>
            <p className="text-slate-400 text-xs mb-1">Период по рекомендациям</p>
            <div className="flex flex-wrap gap-2">
              {[7, 14, 30].map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDays(d)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                    days === d
                      ? "bg-emerald-600 text-white"
                      : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                  }`}
                >
                  {d} дней
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="text-slate-400 text-xs mb-1">Начальный банк, ₽</p>
            <input
              type="number"
              min={0}
              step={100}
              value={initialBank}
              onChange={(e) => setInitialBank(e.target.value)}
              className="w-32 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
            />
          </div>

          <div>
            <p className="text-slate-400 text-xs mb-1">Ставка на каждый прогноз, ₽</p>
            <input
              type="number"
              min={0}
              step={10}
              value={stake}
              onChange={(e) => setStake(e.target.value)}
              className="w-32 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
            />
          </div>

          <div className="ml-auto flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => toggleAll(true)}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-200 hover:bg-slate-700"
            >
              Отметить все
            </button>
            <button
              type="button"
              onClick={() => toggleAll(false)}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-slate-800 text-slate-200 hover:bg-slate-700"
            >
              Снять всё
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-lg bg-slate-800/80 p-4">
            <p className="text-slate-400 text-xs mb-1">Начальный банк</p>
            <p className="text-xl font-semibold text-white">
              {calc.bankStart.toFixed(0)} ₽
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/80 p-4">
            <p className="text-slate-400 text-xs mb-1">Итоговый банк</p>
            <p className="text-xl font-semibold text-white">
              {calc.bankFinal.toFixed(0)} ₽
            </p>
            <p className="text-slate-500 text-xs mt-1">
              Ставок учтено: {calc.wins + calc.losses}, сумма ставок:{" "}
              {calc.used.toFixed(0)} ₽
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/80 p-4">
            <p className="text-slate-400 text-xs mb-1">Результат</p>
            <p
              className={`text-xl font-semibold ${
                calc.profit > 0
                  ? "text-emerald-400"
                  : calc.profit < 0
                  ? "text-rose-400"
                  : "text-slate-300"
              }`}
            >
              {calc.profit >= 0 ? "+" : ""}
              {calc.profit.toFixed(0)} ₽
            </p>
            <p className="text-slate-500 text-xs mt-1">
              Выиграло: {calc.wins}, проиграло: {calc.losses}
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
        <h2 className="text-lg font-semibold text-white mb-3">
          Список прогнозов для расчёта
        </h2>
        {loading ? (
          <p className="text-slate-500 text-sm">Загрузка прогнозов…</p>
        ) : error ? (
          <p className="text-rose-400 text-sm">{error}</p>
        ) : items.length === 0 ? (
          <p className="text-slate-500 text-sm">
            За выбранный период нет сохранённых рекомендаций.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="py-2 pr-2">
                    <span className="sr-only">В расчёт</span>
                  </th>
                  <th className="text-left py-2 pr-2">Лига</th>
                  <th className="text-left py-2 pr-2">Матч</th>
                  <th className="text-left py-2 pr-2 whitespace-nowrap">
                    Начало матча
                  </th>
                  <th className="text-left py-2 pr-2">Рекомендация</th>
                  <th className="text-left py-2 pr-2 whitespace-nowrap">
                    Кф. при рекомендации
                  </th>
                  <th className="text-left py-2 pr-2">Счёт</th>
                  <th className="text-left py-2 pr-2">Исход</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row, idx) => {
                  const disabledForCalc =
                    row.correct === null || row.odds_at_recommendation == null;
                  return (
                    <tr
                      key={`${row.match_id}-${row.created_at ?? idx}`}
                      className="border-b border-slate-700/60"
                    >
                      <td className="py-2 pr-2 text-center">
                        <input
                          type="checkbox"
                          checked={row.selected && !disabledForCalc}
                          disabled={disabledForCalc}
                          onChange={() =>
                            setItems((prev) =>
                              prev.map((it, i) =>
                                i === idx ? { ...it, selected: !it.selected } : it,
                              ),
                            )
                          }
                          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
                        />
                      </td>
                      <td className="py-2 pr-2 text-slate-400">
                        {row.league_name || "—"}
                      </td>
                      <td className="py-2 pr-2 text-slate-200">
                        {row.home_name} — {row.away_name}
                      </td>
                      <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                        {formatMatchStart(row.start_time)}
                      </td>
                      <td className="py-2 pr-2 text-slate-300">
                        {row.recommendation_text}
                      </td>
                      <td className="py-2 pr-2 text-slate-400 whitespace-nowrap">
                        {row.odds_at_recommendation != null
                          ? row.odds_at_recommendation.toFixed(2)
                          : "—"}
                      </td>
                      <td className="py-2 pr-2 text-slate-400 font-mono">
                        {row.final_score ?? "—"}
                      </td>
                      <td className="py-2 pr-2">
                        {row.correct === true && (
                          <span className="text-emerald-400">Угадали</span>
                        )}
                        {row.correct === false && (
                          <span className="text-rose-400">Не угадали</span>
                        )}
                        {row.correct === null && (
                          <span className="text-slate-500">Ожидает / не оценивается</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

