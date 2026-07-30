"use client";
import { Component, type ReactNode } from "react";
import { X } from "lucide-react";

interface Props {
  children: ReactNode;
  onClose: () => void;
}
interface State {
  hasError: boolean;
}

export class PdfViewerBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: unknown) {
    console.error("PdfViewer crashed, isolated from AppShell:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="flex h-full w-full min-w-0 items-center justify-center p-6"
          style={{
            background: "rgba(20,21,26,0.62)",
            WebkitBackdropFilter: "blur(26px) saturate(160%)",
            backdropFilter: "blur(26px) saturate(160%)",
          }}
        >
          <div className="w-full max-w-sm rounded-xl border border-white/12 bg-white/5 p-6 text-center">
            <p className="text-[13.5px] text-white/90 mb-4">
              Couldn't open this PDF. The file may be missing, corrupted, or blocked.
            </p>
            <button
              onClick={this.props.onClose}
              className="inline-flex items-center gap-1.5 rounded-md bg-white/10 px-3 py-1.5 text-[12.5px] text-white/80 hover:bg-white/15"
            >
              <X className="h-3.5 w-3.5" />
              Close
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}