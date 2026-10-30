"use client";

import { cn } from "cn";
import Image from "next/image";
import { useState } from "react";

export function AssetIcon({
  src,
  symbol,
  size = 28,
  className,
}: {
  src: string | null | undefined;
  symbol: string;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <span
        aria-hidden
        style={{ width: size, height: size }}
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-full bg-accent text-[10px] font-semibold text-muted-foreground",
          className,
        )}
      >
        {symbol.slice(0, 3)}
      </span>
    );
  }
  return (
    <Image
      src={src}
      alt=""
      width={size}
      height={size}
      // Tiny provider-hosted icons: optimizing them server-side costs more than it saves.
      unoptimized
      style={{ width: size, height: size }}
      onError={() => setFailed(true)}
      className={cn("shrink-0 rounded-full bg-accent", className)}
    />
  );
}
