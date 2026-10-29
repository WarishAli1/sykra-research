"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Editor } from "@tiptap/react";
import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Check, ChevronDown, IndentDecrease,
  IndentIncrease, Italic, List, ListOrdered, MoveVertical, Minus, Plus, RemoveFormatting, Underline,
} from "lucide-react";

export type Align = "left" | "center" | "right" | "justify";
export type DocFormat = { font: string; size: number; spacing: number; align: Align };

export const FONTS = [
  { label: "Times New Roman", css: '"Times New Roman",Times,serif' },
  { label: "Georgia", css: "Georgia,serif" },
  { label: "Cambria", css: "Cambria,Georgia,serif" },
  { label: "Arial", css: "Arial,Helvetica,sans-serif" },
  { label: "Calibri", css: "Calibri,Carlito,Arial,sans-serif" },
  { label: "Verdana", css: "Verdana,sans-serif" },
];
export const DEFAULT_FORMAT: DocFormat = { font: "Times New Roman", size: 12, spacing: 1.5, align: "justify" };

const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24];
const SPACINGS = [1, 1.15, 1.5, 2];
const ALIGNS = [
  { value: "left", label: "Left", Icon: AlignLeft },
  { value: "center", label: "Center", Icon: AlignCenter },
  { value: "right", label: "Right", Icon: AlignRight },
  { value: "justify", label: "Justify", Icon: AlignJustify },
] as const;

// Buttons must not steal focus from the section editor, or it would blur and close.
const keepFocus = (e: React.MouseEvent) => e.preventDefault();

function Btn({ title, active, disabled, onClick, children }: {
  title: string; active?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode;
}) {
  return (
    <button type="button" title={title} aria-label={title} aria-pressed={active} disabled={disabled}
      onMouseDown={keepFocus} onClick={onClick} className={`rp-tb-btn${active ? " is-active" : ""}`}>
      {children}
    </button>
  );
}

function Dropdown({ title, trigger, triggerClass = "", children }: {
  title: string; trigger: ReactNode; triggerClass?: string; children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button type="button" title={title} aria-label={title} aria-haspopup="menu" aria-expanded={open}
        onMouseDown={keepFocus} onClick={() => setOpen((o) => !o)} className={`rp-tb-btn ${triggerClass}`}>
        {trigger}<ChevronDown className="rp-chev" />
      </button>
      {open && <div className="rp-menu" role="menu" onMouseDown={keepFocus}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

function Item({ selected, onClick, children, style }: {
  selected?: boolean; onClick: () => void; children: ReactNode; style?: React.CSSProperties;
}) {
  return (
    <button type="button" role="menuitem" className="rp-menu-item" style={style} onClick={onClick}>
      {selected && <Check className="rp-check" />}{children}
    </button>
  );
}

export function ReportToolbar({ editor, fmt, onChange }: {
  editor: Editor | null; fmt: DocFormat; onChange: (f: DocFormat) => void;
}) {
  const set = (patch: Partial<DocFormat>) => onChange({ ...fmt, ...patch });
  const run = (fn: (c: ReturnType<Editor["chain"]>) => ReturnType<Editor["chain"]>) => editor && fn(editor.chain().focus()).run();
  const is = (name: string) => !!editor?.isActive(name);
  const CurrentAlign = ALIGNS.find((a) => a.value === fmt.align)!.Icon;

  return (
    <div className="rp-toolbar" role="toolbar" aria-label="Report formatting">
      <Dropdown title="Font" triggerClass="rp-tb-font" trigger={<span style={{ fontFamily: FONTS.find((f) => f.label === fmt.font)?.css }}>{fmt.font}</span>}>
        {(close) => FONTS.map((f) => (
          <Item key={f.label} selected={f.label === fmt.font} style={{ fontFamily: f.css }}
            onClick={() => { set({ font: f.label }); close(); }}>{f.label}</Item>
        ))}
      </Dropdown>

      <span className="rp-tb-sep" />

      <Btn title="Decrease font size" disabled={fmt.size <= SIZES[0]} onClick={() => set({ size: Math.max(SIZES[0], fmt.size - 1) })}><Minus /></Btn>
      <Dropdown title="Font size" triggerClass="rp-tb-size" trigger={<span>{fmt.size}</span>}>
        {(close) => SIZES.map((n) => (
          <Item key={n} selected={n === fmt.size} onClick={() => { set({ size: n }); close(); }}>{n}</Item>
        ))}
      </Dropdown>
      <Btn title="Increase font size" disabled={fmt.size >= SIZES[SIZES.length - 1]} onClick={() => set({ size: Math.min(SIZES[SIZES.length - 1], fmt.size + 1) })}><Plus /></Btn>

      <span className="rp-tb-sep" />

      <Btn title="Bold" active={is("bold")} disabled={!editor} onClick={() => run((c) => c.toggleBold())}><Bold /></Btn>
      <Btn title="Italic" active={is("italic")} disabled={!editor} onClick={() => run((c) => c.toggleItalic())}><Italic /></Btn>
      <Btn title="Underline" active={is("underline")} disabled={!editor} onClick={() => run((c) => c.toggleUnderline())}><Underline /></Btn>

      <span className="rp-tb-sep" />

      <Dropdown title="Align" trigger={<CurrentAlign />}>
        {(close) => ALIGNS.map(({ value, label, Icon }) => (
          <Item key={value} selected={value === fmt.align} onClick={() => { set({ align: value }); close(); }}><Icon />{label}</Item>
        ))}
      </Dropdown>
      <Dropdown title="Line spacing" trigger={<MoveVertical />}>
        {(close) => SPACINGS.map((n) => (
          <Item key={n} selected={n === fmt.spacing} onClick={() => { set({ spacing: n }); close(); }}>{n.toFixed(n === 1.15 ? 2 : 1)}</Item>
        ))}
      </Dropdown>

      <span className="rp-tb-sep" />

      <Btn title="Bulleted list" active={is("bulletList")} disabled={!editor} onClick={() => run((c) => c.toggleBulletList())}><List /></Btn>
      <Btn title="Numbered list" active={is("orderedList")} disabled={!editor} onClick={() => run((c) => c.toggleOrderedList())}><ListOrdered /></Btn>
      <Btn title="Decrease indent" disabled={!editor} onClick={() => run((c) => c.liftListItem("listItem"))}><IndentDecrease /></Btn>
      <Btn title="Increase indent" disabled={!editor} onClick={() => run((c) => c.sinkListItem("listItem"))}><IndentIncrease /></Btn>

      <span className="rp-tb-sep" />

      <Btn title="Clear formatting" disabled={!editor} onClick={() => run((c) => c.unsetAllMarks().clearNodes())}><RemoveFormatting /></Btn>
    </div>
  );
}