import { ReactNode } from "react";

export function Timeline({ children }: { children: ReactNode }) {
  return (
    <div className="relative pl-6">
      <div className="absolute left-[7px] top-2 bottom-2 w-px bg-line" />
      <div className="space-y-6">
        {children}
      </div>
    </div>
  );
}