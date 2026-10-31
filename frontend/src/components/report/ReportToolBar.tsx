"use client";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, Bold, Check, ChevronDown, IndentDecrease,
  IndentIncrease, Italic, List, ListOrdered, MoveVertical, Minus, Plus, RemoveFormatting, Underline,
} from "lucide-react";
import {
  FIELD_DEFAULTS, FONTS, SIZES, SPACINGS, isBoldWeight,
  type ActiveField, type Align,
} from "./ReportFormat";

const ALIGNS = [
  { value: "left", label: "Left", Icon: AlignLeft },
  { value: "center", label: "Center", Icon: AlignCenter },
  { value: "right", label: "Right", Icon: AlignRight },
  { value: "justify", label: "Justify", Icon: AlignJustify },
] as const;

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

function Dropdown({ title, trigger, triggerClass = "", disabled, children }: {
  title: string; trigger: ReactNode; triggerClass?: string; disabled?: boolean;
  children: (close: () => void) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const isOpen = open && !disabled;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isOpen) return;
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [isOpen]);
  return (
    <div ref={ref} className="relative">
      <button type="button" title={title} aria-label={title} aria-haspopup="menu" aria-expanded={isOpen} disabled={disabled}
        onMouseDown={keepFocus} onClick={() => setOpen((o) => !o)} className={`rp-tb-btn ${triggerClass}`}>
        {trigger}<ChevronDown className="rp-chev" />
      </button>
      {isOpen && <div className="rp-menu" role="menu" onMouseDown={keepFocus}>{children(() => setOpen(false))}</div>}
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

const SCOPE = { title: "Title", heading: "Heading", body: "Text" } as const;

export function ReportToolbar({ active }: { active: ActiveField | null }) {
  const editor = active && !active.editor.isDestroyed ? active.editor : null;
  const kind = active?.kind ?? "body";
  const d = FIELD_DEFAULTS[kind];
  const off = !editor;

  const tf = (editor?.getAttributes("textFormat") ?? {}) as { fontFamily?: string | null; fontSize?: number | null; fontWeight?: string | null };
  const blk = (editor?.getAttributes("paragraph") ?? {}) as { textAlign?: Align | null; lineHeight?: number | null };
  const font = tf.fontFamily || d.font;
  const size = tf.fontSize || d.size;
  const align = (blk.textAlign || d.align) as Align;
  const spacing = blk.lineHeight || d.spacing;
  const bold = kind === "body" ? !!editor?.isActive("bold") : isBoldWeight(tf.fontWeight ?? (d.bold ? "700" : "400"));
  const CurrentAlign = ALIGNS.find((a) => a.value === align)!.Icon;
  const isBody = kind === "body";

  const chain = () => editor!.chain().focus();
  const setSize = (n: number) => chain().setTextFormat({ fontSize: n }).run();
  const stepSize = (dir: 1 | -1) => {
    const next = dir > 0 ? SIZES.find((n) => n > size) : [...SIZES].reverse().find((n) => n < size);
    if (next) setSize(next);
  };
  const toggleBold = () => (isBody ? chain().toggleBold().run() : chain().setTextFormat({ fontWeight: bold ? "400" : "700" }).run());
  const clearAll = () => {
    if (isBody) chain().unsetAllMarks().clearNodes().setBlockFormat({ textAlign: null, lineHeight: null }).run();
    else chain().unsetAllMarks().setBlockFormat({ textAlign: null, lineHeight: null }).run();
  };

  return (
    <div className="rp-toolbar" role="toolbar" aria-label="Report formatting">
      <span className="rp-tb-scope" title="Formatting applies to the current selection only">{off ? "Select text" : SCOPE[kind]}</span>
      <span className="rp-tb-sep" />

      <Dropdown title="Font" triggerClass="rp-tb-font" disabled={off} trigger={<span style={{ fontFamily: `'${font}'` }}>{font}</span>}>
        {(close) => FONTS.map((f) => (
          <Item key={f} selected={f === font} style={{ fontFamily: `'${f}'` }}
            onClick={() => { chain().setTextFormat({ fontFamily: f }).run(); close(); }}>{f}</Item>
        ))}
      </Dropdown>

      <span className="rp-tb-sep" />

      <Btn title="Decrease font size" disabled={off || size <= SIZES[0]} onClick={() => stepSize(-1)}><Minus /></Btn>
      <Dropdown title="Font size" triggerClass="rp-tb-size" disabled={off} trigger={<span>{size}</span>}>
        {(close) => SIZES.map((n) => (
          <Item key={n} selected={n === size} onClick={() => { setSize(n); close(); }}>{n}</Item>
        ))}
      </Dropdown>
      <Btn title="Increase font size" disabled={off || size >= SIZES[SIZES.length - 1]} onClick={() => stepSize(1)}><Plus /></Btn>

      <span className="rp-tb-sep" />

      <Btn title="Bold" active={bold} disabled={off} onClick={toggleBold}><Bold /></Btn>
      <Btn title="Italic" active={!!editor?.isActive("italic")} disabled={off} onClick={() => chain().toggleItalic().run()}><Italic /></Btn>
      <Btn title="Underline" active={!!editor?.isActive("underline")} disabled={off} onClick={() => chain().toggleUnderline().run()}><Underline /></Btn>

      <span className="rp-tb-sep" />

      <Dropdown title="Align" disabled={off} trigger={<CurrentAlign />}>
        {(close) => ALIGNS.map(({ value, label, Icon }) => (
          <Item key={value} selected={value === align} onClick={() => { chain().setBlockFormat({ textAlign: value }).run(); close(); }}><Icon />{label}</Item>
        ))}
      </Dropdown>
      <Dropdown title="Line spacing" disabled={off} trigger={<MoveVertical />}>
        {(close) => SPACINGS.map((n) => (
          <Item key={n} selected={n === spacing} onClick={() => { chain().setBlockFormat({ lineHeight: n }).run(); close(); }}>{n.toFixed(n === 1.15 ? 2 : 1)}</Item>
        ))}
      </Dropdown>

      <span className="rp-tb-sep" />

      <Btn title="Bulleted list" active={!!editor?.isActive("bulletList")} disabled={off || !isBody} onClick={() => chain().toggleBulletList().run()}><List /></Btn>
      <Btn title="Numbered list" active={!!editor?.isActive("orderedList")} disabled={off || !isBody} onClick={() => chain().toggleOrderedList().run()}><ListOrdered /></Btn>
      <Btn title="Decrease indent" disabled={off || !isBody} onClick={() => chain().liftListItem("listItem").run()}><IndentDecrease /></Btn>
      <Btn title="Increase indent" disabled={off || !isBody} onClick={() => chain().sinkListItem("listItem").run()}><IndentIncrease /></Btn>

      <span className="rp-tb-sep" />

      <Btn title="Clear formatting" disabled={off} onClick={clearAll}><RemoveFormatting /></Btn>
    </div>
  );
}