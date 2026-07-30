import { AlertCircle, FileText, Loader2, Square, X } from "lucide-react";

export function UploadPreviewCard({ 
  filename, 
  status, 
  progress, 
  fileUrl, 
  onOpen, 
  onClose,
  onCancel 
}: { 
  filename: string; 
  status:
  | "idle"
  | "uploading"
  | "processing"
  | "done"
  | "error"; 
  progress?: string; 
  fileUrl?: string; 
  onOpen: () => void; 
  onClose: () => void;
  onCancel?: () => void;
}) {
  if (status === "error") {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 mb-2">
        <AlertCircle className="h-4 w-4 text-danger shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[12.5px] font-medium text-ink truncate">{filename}</p>
          <p className="text-[10.5px] text-danger">{progress || "Upload failed"}</p>
        </div>
        <button
          onClick={onClose}
          aria-label="Dismiss"
          className="text-ink-soft hover:text-danger shrink-0"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  if (status === "done") {
    return (
      <div 
        className="flex items-center gap-2 rounded-lg border border-line bg-paper-dim/50 px-3 py-2 mb-2 cursor-pointer hover:bg-paper-dim"
        onClick={onOpen}
      >
        <FileText className="h-4 w-4 text-indigo shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[12.5px] font-medium text-ink truncate">{filename}</p>
          <p className="text-[10.5px] text-ink-soft">Click to view PDF</p>
        </div>
        <button 
          onClick={(e) => { e.stopPropagation(); onClose(); }} 
          className="text-ink-soft hover:text-danger"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }
  const isUploading = status === "uploading" || status === "processing";
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-paper-dim/50 px-3 py-2 mb-2">
      <div className="shrink-0">
        {isUploading ? <Loader2 className="h-4 w-4 text-indigo animate-spin" /> : <FileText className="h-4 w-4 text-indigo" />}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-medium text-ink truncate">
          {filename}
        </p>

        <p className="text-[10.5px] text-ink-soft">
          {progress}
        </p>
      </div>

      {isUploading && (
        <>
          <button 
            onClick={onCancel}
            aria-label="Cancel upload"
            title="Stop upload"
            className="flex h-6 w-6 items-center justify-center rounded text-ink-soft hover:bg-paper-dim hover:text-danger"
          >
            <Square className="h-3 w-3 fill-current" />
          </button>
          <button 
            onClick={onClose}
            aria-label="Close"
            className="text-ink-soft hover:text-danger"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  );
}