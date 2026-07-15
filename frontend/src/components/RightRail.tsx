"use client";

import { Library, Network } from "lucide-react";
import { LibraryPanel } from "./LibraryPanel";
import { ExplorePanel } from "./ExplorePanel";
import type { Paper } from "@/lib/types";

type Tab = "library" | "explore";

export function RightRail({
  papers,
  sessionId,
  tab,
  setTab,
}: {
  papers: Paper[];
  sessionId: string;
  tab: Tab;
  setTab: (t: Tab) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 border-b border-line">
        <TabButton
          active={tab === "library"}
          onClick={() => setTab("library")}
          icon={<Library className="h-3.5 w-3.5" />}
          label="Library"
          badge={papers.length || undefined}
        />
        <TabButton
          active={tab === "explore"}
          onClick={() => setTab("explore")}
          icon={<Network className="h-3.5 w-3.5" />}
          label="Explore"
        />
      </div>

      <div className="flex-1 min-h-0">
        {tab === "library" && <LibraryPanel papers={papers} />}
        {tab === "explore" && <ExplorePanel key={sessionId} projectId={sessionId} />}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  badge?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-1.5 border-b-2 px-3 py-2.5 text-[12px] font-medium transition-colors ${
        active ? "border-indigo text-indigo" : "border-transparent text-ink-soft hover:text-ink"
      }`}
    >
      {icon}
      {label}
      {typeof badge === "number" && (
        <span
          className={`flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
            active ? "bg-indigo text-white" : "bg-paper-dim text-ink-soft"
          }`}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
