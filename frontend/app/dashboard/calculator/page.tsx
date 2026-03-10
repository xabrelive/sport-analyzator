"use client";

import StatsCalculator from "@/components/StatsCalculator";

export default function DashboardCalculatorPage() {
  return (
    <div className="p-6 md:p-8">
      <h1 className="font-display text-2xl font-bold text-white mb-2">
        Калькулятор
      </h1>
      <p className="text-slate-400 text-sm mb-6">
        Оцените, сколько вы могли бы выиграть при разных стратегиях и типах
        каналов. Позже данные будут основываться на реальной статистике.
      </p>
      <StatsCalculator />
    </div>
  );
}

