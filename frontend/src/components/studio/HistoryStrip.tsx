"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Clock, Image as ImageIcon, Loader2 } from "lucide-react";
import type { StudioVisualSpec } from "@/lib/types";
import { studioApi, resolveStudioAsset } from "@/lib/studio-api";

export function HistoryStrip({
  sessionId,
  onSelect,
}: {
  sessionId: string;
  onSelect: (spec: StudioVisualSpec) => void;
}) {
  const [visuals, setVisuals] = useState<StudioVisualSpec[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    studioApi.listSession(sessionId)
      .then((res) => setVisuals(res.visuals))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-ink-soft" />
      </div>
    );
  }

  if (!visuals.length) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-ink-soft">
        <Clock className="h-8 w-8 opacity-30 mb-3" />
        <p className="text-[13px]">No visuals generated yet in this session</p>
      </div>
    );
  }

  return (
    <div className="px-6 py-6">
      <h2 className="font-serif text-[16px] font-semibold text-ink mb-4">
        Session History
      </h2>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        {visuals.map((v, i) => (
          <motion.button
            key={v.visual_id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            onClick={() => onSelect(v)}
            className="group relative overflow-hidden rounded-xl border border-line bg-paper p-3 text-left shadow-sm transition-all hover:shadow-md hover:border-indigo/30"
          >
            {v.asset_path && (
              <img
                src={resolveStudioAsset(v.asset_path) ?? ""}
                alt={v.title}
                className="mb-2 h-28 w-full rounded-lg object-cover"
              />
            )}
            <p className="text-[12px] font-medium text-ink truncate">{v.title}</p>
            <p className="text-[10.5px] text-ink-soft mt-0.5">
              v{v.revision} · {new Date(v.created_at).toLocaleTimeString()}
            </p>
            <div className="absolute inset-0 flex items-center justify-center bg-ink/0 opacity-0 transition-all group-hover:bg-ink/5 group-hover:opacity-100">
              <span className="rounded-full bg-paper px-3 py-1 text-[11px] font-medium text-ink shadow-md">
                Open
              </span>
            </div>
          </motion.button>
        ))}
      </div>
    </div>
  );
}