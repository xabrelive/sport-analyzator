"use client";

import { useMemo, useState } from "react";

type CalcChannel = "free" | "paid" | "vip" | "signals";

const CHANNEL_LABELS: Record<CalcChannel, string> = {
  free: "Бесплатный канал",
  paid: "Платная аналитика",
  vip: "VIP чат",
  signals: "Сигналы от бота",
};

// Условные коэффициенты: сколько ставок в день и средняя прибыль на ставку (в коэффициентах от суммы ставки)
const CHANNEL_PRESETS: Record<
  CalcChannel,
  { betsPerDay: number; profitPerBet: number }
> = {
  free: { betsPerDay: 3, profitPerBet: 0.05 },
  paid: { betsPerDay: 5, profitPerBet: 0.08 },
  vip: { betsPerDay: 3, profitPerBet: 0.12 },
  signals: { betsPerDay: 2, profitPerBet: 0.1 },
};

export default function StatsCalculator() {
  const [channel, setChannel] = useState<CalcChannel>("free");
  const [days, setDays] = useState<number | null>(30);
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");

  const [stake, setStake] = useState<string>("100");
  const [initialBank, setInitialBank] = useState<string>("10000");

  const stakeNum = useMemo(() => {
    const v = parseFloat(stake.replace(",", "."));
    return Number.isFinite(v) && v > 0 ? v : 0;
  }, [stake]);

  const initialBankNum = useMemo(() => {
    const v = parseFloat(initialBank.replace(",", "."));
    return Number.isFinite(v) && v >= 0 ? v : 0;
  }, [initialBank]);

  const periodDays = useMemo(() => {
    if (dateFrom && dateTo) {
      const from = new Date(dateFrom);
      const to = new Date(dateTo);
      const diff = Math.floor(
        (to.getTime() - from.getTime()) / (1000 * 60 * 60 * 24),
      );
      return diff >= 0 ? diff + 1 : 0;
    }
    if (days != null) return days;
    if (dateFrom && !dateTo) return 1;
    if (!dateFrom && dateTo) return 1;
    return 0;
  }, [days, dateFrom, dateTo]);

  const calc = useMemo(() => {
    const bankStart = initialBankNum;
    if (stakeNum <= 0 || periodDays <= 0) {
      return {
        bankStart,
        bankFinal: bankStart,
        profit: 0,
        bets: 0,
      };
    }
    const { betsPerDay, profitPerBet } = CHANNEL_PRESETS[channel];
    const bets = betsPerDay * periodDays;
    const profit = bets * stakeNum * profitPerBet;
    const bankFinal = bankStart + profit;
    return { bankStart, bankFinal, profit, bets };
  }, [initialBankNum, stakeNum, periodDays, channel]);

  const handlePresetPeriod = (preset: "today" | 1 | 7 | 14 | 30) => {
    const today = new Date().toISOString().slice(0, 10);
    if (preset === "today") {
      setDateFrom(today);
      setDateTo(today);
      setDays(null);
    } else {
      setDays(preset);
      setDateFrom("");
      setDateTo("");
    }
  };

  const todayIso = new Date().toISOString().slice(0, 10);
  const isTodayActive =
    !days && dateFrom === todayIso && dateTo === todayIso;
  const isDaysActive = (d: number) => !dateFrom && !dateTo && days === d;

  return (
    <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Калькулятор ставок</h2>
      </div>
      <p className="text-slate-400 text-sm mb-4">
        Введите начальный банк и размер фиксированной ставки. Мы покажем,
        сколько вы могли бы выиграть при условной эффективности каналов
        за выбранный период. Позже данные будут браться из реальной статистики.
      </p>

      <div className="flex flex-wrap items-center gap-4 mb-4">
        <div className="inline-flex rounded-lg bg-slate-800 p-1">
          {(["free", "paid", "vip", "signals"] as CalcChannel[]).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setChannel(c)}
              className={`px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md ${
                channel === c
                  ? "bg-teal-600 text-white"
                  : "text-slate-300 hover:bg-slate-700"
              }`}
            >
              {CHANNEL_LABELS[c]}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs sm:text-sm">
          <span className="text-slate-400">Период:</span>
          <button
            type="button"
            onClick={() => handlePresetPeriod("today")}
            className={`px-3 py-1.5 rounded-lg ${
              isTodayActive
                ? "bg-emerald-600 text-white"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            Сегодня
          </button>
          {[1, 7, 14, 30].map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => handlePresetPeriod(d as 1 | 7 | 14 | 30)}
              className={`px-3 py-1.5 rounded-lg ${
                isDaysActive(d)
                  ? "bg-emerald-600 text-white"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {d === 1 ? "1 день" : `${d} дней`}
            </button>
          ))}
          <div className="flex items-center gap-1">
            <span className="text-slate-400">Период:</span>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setDays(null);
              }}
              className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
            />
            <span className="text-slate-400">—</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setDays(null);
              }}
              className="rounded-lg bg-slate-800 border border-slate-600 px-2 py-1 text-xs text-white"
            />
          </div>
        </div>
      </div>

      <section className="rounded-xl border border-slate-700/80 bg-slate-900/60 p-4 sm:p-6 mb-2">
        <div className="flex flex-wrap items-center gap-4 mb-4">
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
            <p className="text-slate-400 text-xs mb-1">
              Ставка на каждый прогноз, ₽
            </p>
            <input
              type="number"
              min={0}
              step={10}
              value={stake}
              onChange={(e) => setStake(e.target.value)}
              className="w-32 rounded-lg bg-slate-800 border border-slate-600 px-2 py-1.5 text-sm text-white"
            />
          </div>

          <p className="text-slate-500 text-xs max-w-xs">
            Расчёт основан на условном количестве ставок и средней доходности
            для каждого типа канала за выбранный период.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-lg bg-slate-800/80 p-4">
            <p className="text-slate-400 text-xs mb-1">Начальный банк</p>
            <p className="text-xl font-semibold text-white">
              {calc.bankStart.toFixed(0)} ₽
            </p>
          </div>
          <div className="rounded-lg bg-slate-800/80 p-4">
            <p className="text-slate-400 text-xs mb-1">
              Итоговый банк (гипотетически)
            </p>
            <p className="text-xl font-semibold text-white">
              {calc.bankFinal.toFixed(0)} ₽
            </p>
            <p className="text-slate-500 text-xs mt-1">
              Ставок за период: {calc.bets} (период: {periodDays} дн.)
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
          </div>
        </div>
      </section>
    </section>
  );
}

