"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BarChart3,
  GitBranch,
  Layers,
  Network,
  Plus,
  Clock,
  Shield,
  ShieldCheck,
  AlertTriangle,
  Eye,
  EyeOff,
} from "lucide-react";
import type {
  StudioVisualSpec,
  StudioDraftRequest,
  StudioConversationContext,
} from "@/lib/types";
import { studioApi, resolveStudioAsset } from "@/lib/studio-api";
import { DataInputPanel } from "./DataInputPanel";
import { SpecEditorPanel } from "./SpecEditorPanel";
import { PreviewCanvas } from "./PreviewCanvas";
import { HistoryStrip } from "./HistoryStrip";

type StudioMode = "create" | "draft" | "edit" | "browse";

export function StudioView({
  sessionId,
  getConversationContext,
}: {
  sessionId: string;
  getConversationContext?: () => StudioConversationContext | null;
}) {
  const [mode, setMode] = useState<StudioMode>("create");
  const [currentSpec, setCurrentSpec] = useState<StudioVisualSpec | null>(null);
  const [assetUrl, setAssetUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [history, setHistory] = useState<StudioVisualSpec[]>([]);
  const [showEditor, setShowEditor] = useState(true);

  const handleGenerate = useCallback(async (spec: StudioVisualSpec) => {
    setIsGenerating(true);
    try {
      const result = await studioApi.generate(spec);
      setCurrentSpec({ ...spec, ...result });
      setAssetUrl(resolveStudioAsset(result.asset_path));
      setMode("edit");
      const sessionData = await studioApi.listSession(sessionId);
      setHistory(sessionData.visuals);
    } catch (e) {
      console.error("Studio generation failed:", e);
    } finally {
      setIsGenerating(false);
    }
  }, [sessionId]);

  const handleRevise = useCallback(async (spec: StudioVisualSpec) => {
    if (!spec.visual_id) return;
    setIsGenerating(true);
    try {
      const result = await studioApi.revise(spec.visual_id, spec);
      setCurrentSpec({ ...spec, ...result });
      setAssetUrl(resolveStudioAsset(result.asset_path));
    } catch (e) {
      console.error("Studio revision failed:", e);
    } finally {
      setIsGenerating(false);
    }
  }, []);

  const handleDraft = useCallback(
    async (req: Omit<StudioDraftRequest, "session_id">) => {
      setIsGenerating(true);

      try {
        const result = await studioApi.draft({
          session_id: sessionId,
          ...req,
        });

        setCurrentSpec(result.spec);
        setAssetUrl(resolveStudioAsset(result.asset_path));
        setMode("draft");
      } catch (e) {
        console.error("Studio draft generation failed:", e);
      } finally {
        setIsGenerating(false);
      }
    },
    [sessionId]
  );

  const handleCommitDraft = useCallback(async () => {
    if (!currentSpec) return;

    setIsGenerating(true);

    try {
      const result = await studioApi.generate(currentSpec);

      setCurrentSpec({ ...currentSpec, ...result });
      setAssetUrl(resolveStudioAsset(result.asset_path));
      setMode("edit");

      const sessionData = await studioApi.listSession(sessionId);
      setHistory(sessionData.visuals);
    } catch (e) {
      console.error("Studio draft commit failed:", e);
    } finally {
      setIsGenerating(false);
    }
  }, [currentSpec, sessionId]);

  const handleDiscardDraft = useCallback(() => {
    setCurrentSpec(null);
    setAssetUrl(null);
    setMode("create");
  }, []);

  const handleSelectFromHistory = useCallback((spec: StudioVisualSpec) => {
    setCurrentSpec(spec);
    setAssetUrl(resolveStudioAsset(spec.asset_path));
    setMode("edit");
    setShowEditor(true);
  }, []);

  const groundingBadge = currentSpec?.grounding?.level;

  return (
    <div className="flex h-full flex-col bg-paper overflow-hidden">
      <div className="shrink-0 border-b border-line bg-paper/80 backdrop-blur-sm">
        <div className="flex items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div>
              <h1 className="font-serif text-[18px] font-semibold text-ink tracking-tight">
                Sykra Studio
              </h1>
              <p className="text-[11px] text-ink-soft">
                Research-grade visuals, grounded in evidence
              </p>
            </div>
          </div>

          {/* Grounding Badge */}
          <AnimatePresence>
            {groundingBadge && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                className="flex items-center gap-1.5"
              >
                <GroundingBadge level={groundingBadge} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Mode Toggle */}
          <div className="flex items-center gap-1 rounded-lg bg-paper-dim p-1">
            <ModeButton
              active={mode === "create"}
              onClick={() => { setMode("create"); setCurrentSpec(null); setAssetUrl(null); }}
              icon={<Plus className="h-3.5 w-3.5" />}
              label="New"
            />
            <ModeButton
              active={mode === "edit"}
              onClick={() => setMode("edit")}
              icon={<Eye className="h-3.5 w-3.5" />}
              label="Edit"
              disabled={!currentSpec}
            />
            <ModeButton
              active={mode === "browse"}
              onClick={() => setMode("browse")}
              icon={<Clock className="h-3.5 w-3.5" />}
              label="History"
            />
          </div>
        </div>
      </div>

      {/* ─── Main Content ─── */}
      <div className="flex flex-1 min-h-0">
        <AnimatePresence mode="wait">
          {mode === "create" && (
            <motion.div
              key="create"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
              className="flex-1 overflow-y-auto"
            >
              <DataInputPanel
                sessionId={sessionId}
                onGenerate={handleGenerate}
                onDraft={handleDraft}
                getConversationContext={getConversationContext}
                isGenerating={isGenerating}
              />
            </motion.div>
          )}

          {(mode === "edit" || mode === "draft") && currentSpec && (
            <motion.div
              key="edit"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="flex flex-1 min-h-0"
            >
              {/* Preview */}
            <div className="flex-1 min-w-0 flex flex-col">
              {mode === "draft" && (
                <div className="mx-6 mt-6 flex items-center justify-between rounded-xl border border-indigo/30 bg-indigo-tint/40 px-4 py-3">
                  <div>
                    <p className="text-[12.5px] font-semibold text-ink">
                      Draft preview
                    </p>
                    <p className="text-[11px] text-ink-soft">
                      Not saved to history yet. Keep it, refine it, or discard it.
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleDiscardDraft}
                      className="rounded-lg border border-line bg-paper px-3 py-2 text-[12px] font-medium text-ink-soft hover:text-ink"
                    >
                      Discard
                    </button>

                    <button
                      onClick={handleCommitDraft}
                      disabled={isGenerating}
                      className="rounded-lg bg-indigo px-3 py-2 text-[12px] font-semibold text-white hover:bg-indigo-dark disabled:opacity-50"
                    >
                      {isGenerating ? "Saving..." : "Keep this version"}
                    </button>
                  </div>
                </div>
              )}

              <PreviewCanvas
                assetUrl={assetUrl}
                title={currentSpec.title}
                caption={currentSpec.caption}
                isGenerating={isGenerating}
                grounding={currentSpec.grounding}
                isDraft={mode === "draft"}
              />
              </div>

              {/* Editor Sidebar */}
              <AnimatePresence>
                {showEditor && (
                  <motion.div
                    initial={{ width: 0, opacity: 0 }}
                    animate={{ width: 320, opacity: 1 }}
                    exit={{ width: 0, opacity: 0 }}
                    transition={{ duration: 0.25, ease: "easeInOut" }}
                    className="shrink-0 border-l border-line overflow-hidden"
                  >
                    <SpecEditorPanel
                      spec={currentSpec}
                      onRevise={handleRevise}
                      isGenerating={isGenerating}
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Toggle Editor Button */}
              <button
                onClick={() => setShowEditor(!showEditor)}
                className="shrink-0 w-6 flex items-center justify-center border-l border-line bg-paper-dim/50 hover:bg-paper-dim transition-colors"
              >
                {showEditor ? (
                  <EyeOff className="h-3 w-3 text-ink-soft" />
                ) : (
                  <Eye className="h-3 w-3 text-ink-soft" />
                )}
              </button>
            </motion.div>
          )}

          {mode === "browse" && (
            <motion.div
              key="browse"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              transition={{ duration: 0.2 }}
              className="flex-1 overflow-y-auto"
            >
              <HistoryStrip
                sessionId={sessionId}
                onSelect={handleSelectFromHistory}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}


function ModeButton({
  active,
  onClick,
  icon,
  label,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11.5px] font-medium transition-all ${
        active
          ? "bg-paper text-ink shadow-sm shadow-black/5"
          : "text-ink-soft hover:text-ink"
      } ${disabled ? "opacity-40 cursor-not-allowed" : ""}`}
    >
      {icon}
      {label}
    </button>
  );
}

function GroundingBadge({ level }: { level: string }) {
  const config = {
    user_provided: {
      icon: <Shield className="h-3 w-3" />,
      label: "User data",
      color: "text-gold border-gold/30 bg-gold-tint",
    },
    grounded: {
      icon: <ShieldCheck className="h-3 w-3" />,
      label: "Grounded",
      color: "text-indigo border-indigo/30 bg-indigo-tint",
    },
    mixed: {
      icon: <Shield className="h-3 w-3" />,
      label: "Mixed",
      color: "text-gold border-gold/30 bg-gold-tint",
    },
    illustrative: {
      icon: <AlertTriangle className="h-3 w-3" />,
      label: "Illustrative",
      color: "text-danger border-danger/30 bg-danger/5",
    },
    draft: {
      icon: <Shield className="h-3 w-3" />,
      label: "AI draft",
      color: "text-indigo border-indigo/30 bg-indigo-tint",
    },
  }[level] ?? { icon: <Shield className="h-3 w-3" />, label: level, color: "text-ink-soft border-line bg-paper-dim" };

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10.5px] font-medium ${config.color}`}>
      {config.icon}
      {config.label}
    </span>
  );
}