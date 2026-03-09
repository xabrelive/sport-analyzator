import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import Link from "next/link";

export const metadata = {
  title: "Преимущества — PingWin",
  description: "Почему PingWin: лайв, линия, статистика, уведомления, только аналитика.",
};

const items = [
  {
    title: "Только аналитика",
    text: "Мы предоставляем данные и оценки, без рекомендаций и призывов к действиям. Решения остаются за вами.",
  },
  {
    title: "Лайв и линия",
    text: "Матчи в реальном времени и предстоящие события: счёт по сетам и очкам, коэффициенты, контекст по турнирам.",
  },
  {
    title: "Статистика по игрокам",
    text: "Форма, история встреч, тренды — чтобы вы могли опираться на факты, а не на догадки.",
  },
  {
    title: "Вероятности по сетам",
    text: "Оценки на основе моделей и исторических данных. Информация носит справочный характер.",
  },
  {
    title: "Уведомления",
    text: "Telegram и email: получайте информацию о новых событиях и аналитике по выбранным видам спорта.",
  },
  {
    title: "Один аккаунт",
    text: "Вход по почте или Telegram — все данные и настройки в одном месте.",
  },
];

export default function AdvantagesPage() {
  return (
    <>
      <Header />
      <main className="min-h-screen">
        <div className="mx-auto max-w-4xl px-4 py-12 sm:py-16">
          <h1 className="font-display text-3xl font-bold text-white sm:text-4xl">
            Преимущества PingWin
          </h1>
          <p className="mt-2 text-slate-400">
            Что даёт сервис pingwin.pro
          </p>
          <ul className="mt-10 space-y-6">
            {items.map((item, i) => (
              <li
                key={i}
                className="rounded-xl border border-slate-700/80 bg-slate-800/30 p-5 transition hover:border-cyan-500/30"
              >
                <h2 className="font-semibold text-white">{item.title}</h2>
                <p className="mt-2 text-slate-400">{item.text}</p>
              </li>
            ))}
          </ul>
          <p className="mt-10">
            <Link href="/" className="text-cyan-400 hover:underline">
              ← На главную
            </Link>
          </p>
        </div>
        <Footer />
      </main>
    </>
  );
}
