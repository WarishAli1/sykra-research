import { Extension, Mark, Node } from "@tiptap/core";
import type { Editor } from "@tiptap/react";
import { DOMParser as PMDOMParser } from "@tiptap/pm/model";
import StarterKit from "@tiptap/starter-kit";
import { Table } from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import { Markdown } from "tiptap-markdown";

export type Align = "left" | "center" | "right" | "justify";
export type FieldKind = "title" | "heading" | "body";
export type ActiveField = { editor: Editor; kind: FieldKind };

export const FONTS = ["Times New Roman", "Georgia", "Cambria", "Arial", "Calibri", "Verdana"];
export const SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32];
export const SPACINGS = [1, 1.15, 1.5, 2];

export const FIELD_DEFAULTS: Record<FieldKind, { font: string; size: number; spacing: number; align: Align; bold: boolean }> = {
  title: { font: "Times New Roman", size: 18, spacing: 1.2, align: "center", bold: true },
  heading: { font: "Times New Roman", size: 16, spacing: 1.2, align: "left", bold: true },
  body: { font: "Times New Roman", size: 12, spacing: 1.5, align: "justify", bold: false },
};

export const isBoldWeight = (w: string | null | undefined) =>
  !!w && (w === "bold" || w === "bolder" || Number(w) >= 600);

type TextFormatAttrs = { fontFamily: string | null; fontSize: number | null; fontWeight: string | null };
const EMPTY: TextFormatAttrs = { fontFamily: null, fontSize: null, fontWeight: null };

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    reportFormat: {
      setTextFormat: (patch: Partial<TextFormatAttrs>) => ReturnType;
      setBlockFormat: (patch: { textAlign?: Align | null; lineHeight?: number | null }) => ReturnType;
    };
  }
}

export const TextFormat = Mark.create({
  name: "textFormat",
  addAttributes() {
    return { fontFamily: { default: null }, fontSize: { default: null }, fontWeight: { default: null } };
  },
  parseHTML() {
    return [{
      tag: "span",
      getAttrs: (el) => {
        const s = (el as HTMLElement).style;
        const fontFamily = (s.fontFamily || "").split(",")[0].replace(/["']/g, "").trim() || null;
        const n = parseFloat(s.fontSize);
        const fontSize = !isFinite(n) ? null : s.fontSize.endsWith("pt") ? n : s.fontSize.endsWith("px") ? Math.round(n * 0.75 * 2) / 2 : null;
        const fontWeight = s.fontWeight || null;
        if (!fontFamily && !fontSize && !fontWeight) return false;
        return { fontFamily, fontSize, fontWeight };
      },
    }];
  },
  renderHTML({ mark }) {
    const a = mark.attrs as TextFormatAttrs;
    const css: string[] = [];
    if (a.fontFamily) css.push(`font-family:'${a.fontFamily}'`);
    if (a.fontSize) css.push(`font-size:${a.fontSize}pt`);
    if (a.fontWeight) css.push(`font-weight:${a.fontWeight}`);
    return ["span", { style: css.join(";") }, 0];
  },
});

export const BlockFormat = Extension.create({
  name: "blockFormat",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "heading"],
      attributes: {
        textAlign: {
          default: null,
          parseHTML: (el: HTMLElement) => (["left", "center", "right", "justify"].includes(el.style.textAlign) ? el.style.textAlign : null),
          renderHTML: (a: Record<string, unknown>) => (a.textAlign ? { style: `text-align:${a.textAlign}` } : {}),
        },
        lineHeight: {
          default: null,
          parseHTML: (el: HTMLElement) => { const n = parseFloat(el.style.lineHeight); return isFinite(n) && !el.style.lineHeight.endsWith("%") ? n : null; },
          renderHTML: (a: Record<string, unknown>) => (a.lineHeight ? { style: `line-height:${a.lineHeight}` } : {}),
        },
      },
    }];
  },
  addCommands() {
    return {
      setTextFormat: (patch) => ({ state, tr, dispatch }) => {
        const type = state.schema.marks.textFormat;
        if (!type) return false;
        if (!dispatch) return true;
        const merge = (existing?: Record<string, unknown>) => {
          const m = { ...EMPTY, ...(existing ?? {}), ...patch };
          return Object.values(m).every((v) => v == null) ? null : m;
        };
        const { from, to, empty, $from } = state.selection;
        if (empty) {
          const ex = type.isInSet(state.storedMarks ?? $from.marks());
          const m = merge(ex?.attrs);
          tr.removeStoredMark(type);
          if (m) tr.addStoredMark(type.create(m));
          return true;
        }
        state.doc.nodesBetween(from, to, (node, pos) => {
          if (!node.isText) return;
          const s = Math.max(pos, from);
          const e = Math.min(pos + node.nodeSize, to);
          const m = merge(type.isInSet(node.marks)?.attrs);
          tr.removeMark(s, e, type);
          if (m) tr.addMark(s, e, type.create(m));
        });
        return true;
      },
      setBlockFormat: (patch) => ({ state, tr, dispatch }) => {
        if (!dispatch) return true;
        const { from, to } = state.selection;
        state.doc.nodesBetween(from, to, (node, pos) => {
          if (node.type.name !== "paragraph" && node.type.name !== "heading") return;
          const attrs = { ...node.attrs };
          if ("textAlign" in patch) attrs.textAlign = patch.textAlign ?? null;
          if ("lineHeight" in patch) attrs.lineHeight = patch.lineHeight ?? null;
          tr.setNodeMarkup(pos, undefined, attrs);
        });
        return true;
      },
    };
  },
});

const SingleLineDoc = Node.create({ name: "doc", topNode: true, content: "block" });

export const singleLineExtensions = () => [
  StarterKit.configure({
    document: false, heading: false, bulletList: false, orderedList: false, listItem: false,
    blockquote: false, codeBlock: false, horizontalRule: false, code: false, strike: false, hardBreak: false,
  }),
  SingleLineDoc, TextFormat, BlockFormat,
];

export const bodyExtensions = () => [
  StarterKit, Table, TableRow, TableHeader, TableCell,
  Markdown.configure({ html: true }), TextFormat, BlockFormat,
];


export function loadHtml(editor: Editor, html: string) {
  const body = new window.DOMParser().parseFromString(html, "text/html").body;
  const doc = PMDOMParser.fromSchema(editor.schema).parse(body);
  editor.view.dispatch(
    editor.state.tr.replaceWith(0, editor.state.doc.content.size, doc.content).setMeta("addToHistory", false),
  );
}

export const escHtml = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
export const plainToHtml = (t: string) => `<p>${escHtml(t)}</p>`;
export const hasFormatting = (html: string) => /\sstyle="/i.test(html);

export function editorMarkdown(editor: Editor): string {
  type MdStorage = { markdown: { getMarkdown(): string } };
  return (editor.storage as unknown as MdStorage).markdown
    .getMarkdown()
    .replace(/<\/?span\b[^>]*>/g, "")
    .replace(/\\\[(\d{1,3})\\\]/g, "[$1]");
}

export const DOCX_STYLE = {
  title: "font-family:'Times New Roman';font-weight:bold;font-size:18pt;text-align:center;",
  heading: "font-family:'Times New Roman';font-weight:bold;font-size:16pt;",
  body: "font-family:'Times New Roman';font-size:12pt;line-height:1.5;text-align:justify;",
};

export function styleParagraphs(html: string, base: string) {
  return html.replace(/<(p|li)((?:\s[^>]*)?)>/g, (_m, tag: string, attrs: string) => {
    const own = /\sstyle="([^"]*)"/.exec(attrs);
    const rest = attrs.replace(/\sstyle="[^"]*"/, "");
    return `<${tag}${rest} style="${base}${own ? own[1] : ""}">`;
  });
}

export function headingHtml(tag: "h1" | "h2", text: string, html: string | undefined, base: string) {
  const m = html ? /^\s*<p([^>]*)>([\s\S]*)<\/p>\s*$/.exec(html) : null;
  if (m) {
    const own = /\sstyle="([^"]*)"/.exec(m[1]);
    return `<${tag} style="${base}${own ? own[1] : ""}">${m[2]}</${tag}>`;
  }
  return `<${tag} style="${base}">${escHtml(text)}</${tag}>`;
}