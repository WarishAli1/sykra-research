"use client";

import { motion } from "framer-motion";
import { Loader2, ImageOff } from "lucide-react";
import type { StudioGroundingSummary } from "@/lib/types";

export function PreviewCanvas({
  assetUrl,
  title,
  caption,
  isGenerating,
  grounding,
  isDraft,
}: {
  assetUrl: string | null;
  title: string;
  caption?: string | null;
  isGenerating: boolean;
  grounding?: StudioGroundingSummary;
  isDraft?: boolean;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center p-8 bg-paper-dim/30">
      {isGenerating ? (
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex flex-col items-center gap-4"
        >
          <div className="relative">
            <div className="h-16 w-16 rounded-2xl border-2 border-indigo/20 flex items-center justify-center">
              <Loader2 className="h-7 w-7 animate-spin text-indigo" />
            </div>
            <div className="absolute -inset-2 rounded-3xl border border-indigo/10 animate-pulse" />
          </div>

          <div className="text-center">
            <p className="text-[13px] font-medium text-ink">
              Rendering your visual
            </p>
            <p className="text-[11.5px] text-ink-soft mt-1">
              Applying Sykra theme and grounding checks...
            </p>
          </div>
        </motion.div>
      ) : assetUrl ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="w-full max-w-2xl"
        >
          {isDraft && (
            <div className="mb-3 flex justify-center">
              <span className="rounded-full border border-indigo/30 bg-indigo-tint px-3 py-1 text-[11px] font-medium text-indigo">
                Draft preview
              </span>
            </div>
          )}

          <div className="rounded-2xl border border-line bg-paper p-4 shadow-xl shadow-black/5">
            <img
              src={assetUrl}
              alt={title}
              className="w-full rounded-xl object-contain"
            />
          </div>

          {title && (
            <p className="mt-4 text-center font-serif text-[15px] font-semibold text-ink">
              {title}
            </p>
          )}

          {caption && (
            <p className="mt-1 text-center text-[12px] italic text-ink-soft">
              {caption}
            </p>
          )}

          {grounding && grounding.citations.length > 0 && (
            <p className="mt-2 text-center text-[11px] text-ink-soft">
              Sources: {grounding.citations.map((c) => `[${c}]`).join(" ")}
            </p>
          )}
        </motion.div>
      ) : (
        <div className="flex flex-col items-center gap-3 text-ink-soft">
          <ImageOff className="h-10 w-10 opacity-30" />
          <p className="text-[13px]">No visual generated yet</p>
        </div>
      )}
    </div>
  );
}