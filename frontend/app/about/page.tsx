import Link from "next/link";

export default function AboutPage() {
  return (
    <main className="max-w-3xl mx-auto px-4 py-12">
      <Link href="/" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">← На главную</Link>
      <h1 className="text-3xl font-bold text-white mb-6">Как это работает</h1>
      <div className="prose prose-invert prose-slate max-w-none space-y-4 text-slate-300">
        <p>Sport Analyzator агрегирует данные о матчах и коэффициентах из открытых источников и партнёрских API.</p>
        <h2 className="text-xl font-semibold text-white mt-6">Что вы видите</h2>
        <ul className="list-disc pl-6 space-y-2">
          <li><strong>Линия</strong> — предстоящие матчи и коэффициенты на разные исходы.</li>
          <li><strong>Лайв</strong> — матчи в реальном времени, счёт по сетам.</li>
          <li><strong>Результаты</strong> — завершённые матчи и победители.</li>
          <li><strong>Статистика по игрокам</strong> — победы/поражения, проценты по сетам, типичные порядки сетов.</li>
        </ul>
        <p>Данные обновляются автоматически. Аналитика носит информационный характер и не является рекомендацией к действию.</p>
      </div>
    </main>
  );
}
