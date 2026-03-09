import { Header } from "@/components/Header";
import { Footer } from "@/components/Footer";
import Link from "next/link";

export const metadata = {
  title: "О проекте — PingWin",
  description: "Что такое PingWin: спортивная аналитика, только данные, без призывов к ставкам.",
};

export default function AboutPage() {
  return (
    <>
      <Header />
      <main className="min-h-screen">
        <article className="mx-auto max-w-3xl px-4 py-12 sm:py-16">
          <h1 className="font-display text-3xl font-bold text-white sm:text-4xl">
            О проекте PingWin
          </h1>
          <p className="mt-2 text-slate-400">
            pingwin.pro — сервис спортивной аналитики
          </p>
          <div className="prose prose-invert mt-10 max-w-none prose-p:text-slate-300 prose-li:text-slate-300 prose-a:text-cyan-400 prose-a:no-underline hover:prose-a:underline">
            <p>
              <strong>PingWin</strong> предоставляет исключительно аналитическую информацию по спортивным событиям: статистику по игрокам и командам, данные по матчам в режиме лайв и линия, оценки вероятностей на основе имеющихся данных.
            </p>
            <p>
              Мы не даём рекомендаций по ставкам и не призываем к заключению пари. Любые решения о использовании информации в личных целях пользователь принимает самостоятельно и на свой страх и риск.
            </p>
            <p>
              Регистрация и вход возможны по электронной почте или через Telegram. После входа доступны разделы с лайв-матчами, линией, статистикой по игрокам и уведомлениями по выбранным видам спорта.
            </p>
            <p>
              По вопросам сотрудничества и обратной связи: канал в Telegram{" "}
              <a href="https://t.me/PingwinBets" target="_blank" rel="noopener noreferrer">
                @PingwinBets
              </a>
              , почта{" "}
              <a href="mailto:info@pingwin.pro">info@pingwin.pro</a>.
            </p>
          </div>
          <p className="mt-10">
            <Link href="/" className="text-cyan-400 hover:underline">
              ← На главную
            </Link>
          </p>
        </article>
        <Footer />
      </main>
    </>
  );
}
