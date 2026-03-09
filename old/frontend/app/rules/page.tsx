import Link from "next/link";

export default function RulesPage() {
  return (
    <main className="max-w-3xl mx-auto px-4 py-12">
      <Link href="/" className="text-slate-400 hover:text-white text-sm mb-6 inline-block">← На главную</Link>
      <h1 className="text-3xl font-bold text-white mb-6">Правила использования</h1>
      <div className="prose prose-invert prose-slate max-w-none space-y-4 text-slate-300">
        <p>Используя сервис Sport Analyzator, вы соглашаетесь с настоящими правилами.</p>
        <ul className="list-disc pl-6 space-y-2">
          <li>Сервис предназначен для ознакомления с аналитическими данными по спортивным событиям.</li>
          <li>Запрещается использование данных в нарушение законодательства вашей юрисдикции.</li>
          <li>Регистрируясь, вы подтверждаете, что достигли возраста, с которого разрешено использование подобных сервисов.</li>
          <li>Мы оставляем за собой право ограничить или прекратить доступ к сервису без предварительного уведомления.</li>
        </ul>
        <p>По вопросам обращайтесь через контакты, указанные на сайте.</p>
      </div>
    </main>
  );
}
