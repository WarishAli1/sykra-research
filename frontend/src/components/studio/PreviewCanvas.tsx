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
          </div>
        </motion.div>
      ) : assetUrl ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="w-full max-w-2xl"
        >
          <div className="overflow-hidden rounded-2xl border border-line bg-paper shadow-sm shadow-black/5">
            <img
              src={assetUrl}
              alt={title}
              className="w-full object-contain"
            />
          </div>
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