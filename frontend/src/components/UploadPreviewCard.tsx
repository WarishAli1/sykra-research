import { FileText, Loader2, X } from "lucide-react";

export function UploadPreviewCard({ 
  filename, 
  status, 
  progress, 
  fileUrl, 
  onOpen, 
  onClose 
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
}) {
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
  const icon =
  status === "uploading"
    ? <Loader2 className="h-4 w-4 text-indigo animate-spin" />
    : status === "processing"
    ? <Loader2 className="h-4 w-4 text-indigo animate-spin" />
    : <FileText className="h-4 w-4 text-indigo" />;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-paper-dim/50 px-3 py-2 mb-2">
      <div className="shrink-0">
        {icon}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-[12.5px] font-medium text-ink truncate">
          {filename}
        </p>

        <p className="text-[10.5px] text-ink-soft">
          {progress}
        </p>
      </div>
    </div>
  );
}