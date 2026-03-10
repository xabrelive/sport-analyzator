"use client";

export default function DashboardPage() {
  return (
    <div className="p-6 md:p-8">
      <h1 className="font-display text-2xl font-bold text-white mb-2">
        Дашборд
      </h1>
      <p className="text-slate-400 text-sm mb-8">
        Личный кабинет PingWin. Здесь будет аналитика по матчам, подписки и настройки.
      </p>
      <div className="rounded-xl border border-slate-700/80 bg-slate-800/40 p-6">
        <h2 className="font-semibold text-white mb-2">Скоро</h2>
        <ul className="text-slate-400 text-sm space-y-1">
          <li>• Лайв и линия матчей</li>
          <li>• Статистика по игрокам</li>
          <li>• Уведомления в Telegram и на почту</li>
        </ul>
      </div>
    </div>
  );
}
