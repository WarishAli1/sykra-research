"use client";

import { useLocalStorageFlag } from "@/lib/theme";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { DiagramStudio } from "@/components/studio/ui/DiagramStudio";

const PALETTE_KEY = "sykra:studio-palette-open";

export function StudioView({ sessionId, onToggleChat, chatOpen }: { sessionId: string; getConversationContext?: () => unknown; onToggleChat?: () => void; chatOpen?: boolean }) {
  const [paletteOpen, setPaletteOpen] = useLocalStorageFlag(PALETTE_KEY, true);
  const toggle = () => setPaletteOpen((open) => !open);

  return (
    <div className="studio-view relative flex min-h-0 flex-1 overflow-hidden" data-palette={paletteOpen ? "open" : "closed"}>
      <DiagramStudio sessionId={sessionId} onToggleChat={onToggleChat} chatOpen={chatOpen} />
      <button
        type="button"
        onClick={toggle}
        aria-label={paletteOpen ? "Collapse shapes panel" : "Expand shapes panel"}
        title={paletteOpen ? "Collapse shapes panel" : "Expand shapes panel"}
        className="studio-palette-toggle"
      >
        {paletteOpen ? <PanelLeftClose className="h-3.5 w-3.5" /> : <PanelLeftOpen className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}