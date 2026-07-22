"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type DropdownItem<T extends string> = {
  value: T;
  label: string;
  hint?: string;
};

type DropdownProps<T extends string> = {
  value: T;
  items: DropdownItem<T>[];
  onChange: (value: T) => void;
};

export function Dropdown<T extends string>({
  value,
  items,
  onChange,
}: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClick);
    return () =>
      document.removeEventListener("mousedown", handleClick);
  }, []);

  const selected = items.find((i) => i.value === value);

  return (
    <div className="relative shrink-0" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[11px] font-medium text-ink-soft hover:text-ink hover:bg-paper/60 transition-colors"
      >
        {selected?.label}
        <ChevronDown className="h-3 w-3" />
      </button>

      {open && (
        <div className="absolute right-0 bottom-full z-20 mb-1.5 w-56 rounded-lg border border-line bg-paper shadow-lg shadow-black/10 py-1">
          {items.map((item) => (
            <button
              key={item.value}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
              className={`flex w-full flex-col items-start gap-0.5 px-3 py-1.5 text-left text-[11.5px] hover:bg-paper-dim ${
                value === item.value
                  ? "text-indigo font-medium"
                  : "text-ink"
              }`}
            >
              <span>{item.label}</span>

              {item.hint && (
                <span className="text-[10.5px] font-normal text-ink-soft">
                  {item.hint}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}