"use client";
import { useEffect, useRef } from "react";
import { useEditor, EditorContent, type Editor } from "@tiptap/react";
import {
  hasFormatting, loadHtml, plainToHtml, singleLineExtensions,
  type ActiveField, type FieldKind,
} from "./ReportFormat";

export function RichField({ kind, text, html, disabled, onCommit, onActivate, onRelease }: {
  kind: Exclude<FieldKind, "body">;
  text: string;
  html?: string;
  disabled?: boolean;
  onCommit: (text: string, html: string) => void;
  onActivate: (a: ActiveField) => void;
  onRelease: (e: Editor) => void;
}) {
  const props = useRef({ text, html, onCommit, onActivate, onRelease, kind });
  useEffect(() => {
    props.current = { text, html, onCommit, onActivate, onRelease, kind };
  });

  const editor = useEditor({
    immediatelyRender: false,
    extensions: singleLineExtensions(),
    content: html || plainToHtml(text),
    editable: !disabled,
    editorProps: {
      attributes: { spellcheck: "false" },
      handleKeyDown: (_v, e) => e.key === "Enter",
    },
    onFocus: ({ editor: ed }) => props.current.onActivate({ editor: ed, kind: props.current.kind }),
    onBlur: ({ editor: ed }) => {
      props.current.onRelease(ed);
      const p = props.current;
      const t = ed.getText().replace(/\s+/g, " ").trim();
      if (!t) { loadHtml(ed, p.html || plainToHtml(p.text)); return; }
      const raw = ed.getHTML();
      const h = hasFormatting(raw) ? raw : "";
      if (t === p.text && h === (p.html ?? "")) return;
      p.onCommit(t, h);
    },
  });

  useEffect(() => { editor?.setEditable(!disabled); }, [editor, disabled]);

  useEffect(() => {
    if (!editor || editor.isFocused) return;
    const next = html || plainToHtml(text);
    if (editor.getHTML() !== next) loadHtml(editor, next);
  }, [editor, html, text]);

  return (
    <div className={`rp-field rp-field-${kind}`}>
      <EditorContent editor={editor} />
    </div>
  );
}