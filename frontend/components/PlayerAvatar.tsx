"use client";

import Image from "next/image";
import { useState } from "react";
import type { Player } from "@/lib/api";
import { getPlayerImageUrl } from "@/lib/api";

export interface PlayerAvatarProps {
  player: Pick<Player, "name" | "image_id"> | null | undefined;
  size?: "sm" | "md" | "lg";
  className?: string;
}

const sizePx = { sm: 32, md: 48, lg: 80 };
const sizeClasses = {
  sm: "w-8 h-8 text-xs",
  md: "w-12 h-12 text-sm",
  lg: "w-20 h-20 text-lg",
};

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function PlayerAvatar({ player, size = "md", className = "" }: PlayerAvatarProps) {
  const [imgError, setImgError] = useState(false);
  const url = player ? getPlayerImageUrl(player.image_id) : null;
  const showImage = Boolean(url && player && !imgError);
  const sizeClass = sizeClasses[size];
  const px = sizePx[size];

  if (!player) {
    return (
      <div
        className={`${sizeClass} rounded-full bg-slate-700 flex items-center justify-center text-slate-500 shrink-0 ${className}`}
        aria-hidden
      >
        ?
      </div>
    );
  }

  if (showImage) {
    return (
      <Image
        src={url!}
        alt=""
        width={px}
        height={px}
        className={`${sizeClass} rounded-full object-cover bg-slate-800 shrink-0 ${className}`}
        unoptimized
        onError={() => setImgError(true)}
      />
    );
  }

  return (
    <div
      className={`${sizeClass} rounded-full bg-slate-700 flex items-center justify-center text-slate-300 font-semibold shrink-0 ${className}`}
      aria-hidden
    >
      {getInitials(player.name)}
    </div>
  );
}
