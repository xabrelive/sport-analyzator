"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function AdminPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/users");
  }, [router]);
  return (
    <div className="min-h-[40vh] flex items-center justify-center">
      <span className="text-slate-400">Переход в раздел пользователей…</span>
    </div>
  );
}
