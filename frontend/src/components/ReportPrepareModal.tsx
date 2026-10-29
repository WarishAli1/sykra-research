"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { ReportPrepareResponse, ReportRecord, ReportRole, ReportType } from "@/lib/types";

const TYPES: { value: ReportType; label: string }[] = [
  { value: "general", label: "General" },
  { value: "scientific_research", label: "Scientific research" },
  { value: "field_survey", label: "Field survey" },
  { value: "business_operational", label: "Business / operational" },
  { value: "financial_ledger", label: "Financial / ledger" },
  { value: "technical_project", label: "Technical project" },
];
const ROLES: ReportRole[] = ["count", "percentage", "amount", "rate", "measurement", "other"];
const NUMERIC_RE = /^[-+\u2212\u2013(]?\s*\d[\d.,]*\)?$/;

export function toConfirmed(r: ReportRecord): ReportRecord {
  return {
    id: r.id, field_name: r.field_name, value_raw: r.value_raw.trim(), unit: r.unit ?? null, role: r.role,
    unit_of_analysis: r.unit_of_analysis ?? null, ledger_side: r.ledger_side ?? null,
    numerator_ref: r.numerator_ref ?? null, denominator_ref: r.denominator_ref ?? null,
    original_text: r.original_text ?? "",
  };
}

export function ReportPrepareModal({
  data, onConfirm, onCancel,
}: {
  data: ReportPrepareResponse;
  onConfirm: (type: ReportType, records: ReportRecord[]) => void;
  onCancel: () => void;
}) {
  const [rows, setRows] = useState<ReportRecord[]>(data.records);
  const [type, setType] = useState<ReportType>(data.suggested_type);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const edit = (i: number, patch: Partial<ReportRecord>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const remove = (i: number) =>
    setRows((rs) => {
      const gone = rs[i].id;
      return rs.filter((_, j) => j !== i).map((r) => ({
        ...r,
        numerator_ref: r.numerator_ref === gone ? null : r.numerator_ref,
        denominator_ref: r.denominator_ref === gone ? null : r.denominator_ref,
      }));
    });

  const invalid = rows.some((r) => !NUMERIC_RE.test(r.value_raw.trim()));

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4" onMouseDown={onCancel}>
      <div
        role="dialog" aria-modal="true" aria-label="Confirm your data"
        onMouseDown={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-[760px] flex-col rounded-2xl border border-line bg-paper shadow-xl shadow-black/20"
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="font-serif text-[18px] font-semibold text-ink">Confirm your data</h2>
            <p className="mt-1 text-caption text-ink-soft">
              These values will be used exactly as shown. Correct or remove anything that is wrong.
            </p>
            {(data.suggested_execution_path || data.working_title) && (
              <p className="mt-1 text-micro text-ink-soft">
                {data.suggested_execution_path
                  ? `Execution path: ${data.suggested_execution_path}`
                  : ""}
                {data.suggested_execution_path && data.working_title ? " · " : ""}
                {data.working_title ? `Working title: ${data.working_title}` : ""}
              </p>
            )}
          </div>
          <button onClick={onCancel} aria-label="Close" className="rounded-lg p-1.5 text-ink-soft hover:bg-paper-dim hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 overflow-y-auto px-5 py-4">
          {data.truncated && (
            <p className="rounded-md border border-line bg-paper-dim/60 px-3 py-2 text-caption text-ink-soft">
              Your input was long, so only the first part was analysed.
            </p>
          )}
          {data.dropped_count > 0 && (
            <p className="rounded-md border border-line bg-paper-dim/60 px-3 py-2 text-caption text-ink-soft">
              {data.dropped_count} value(s) could not be verified against your text and were left out.
            </p>
          )}

          <label className="flex items-center gap-2 text-caption text-ink">
            Report type
            <select value={type} onChange={(e) => setType(e.target.value as ReportType)}
                    className="rounded-md border border-line bg-paper px-2 py-1 text-caption">
              {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>

          {rows.length === 0 ? (
            <p className="text-caption text-ink-soft">
              {data.extraction_failed
                ? "Figures couldn't be read automatically. The report will be written from your description only."
                : "No numeric data was found. The report will be written without user figures."}
            </p>
          ) : (
            <table className="w-full text-caption">
              <thead>
                <tr className="text-left text-micro uppercase tracking-wide text-ink-soft">
                  <th className="pb-1 pr-2">Field</th><th className="pb-1 pr-2">Value</th><th className="pb-1 pr-2">Unit</th>
                  <th className="pb-1 pr-2">Type</th><th className="pb-1 pr-2">From your text</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const bad = !NUMERIC_RE.test(r.value_raw.trim());
                  return (
                    <tr key={r.id} className="border-t border-line align-top">
                      <td className="py-1.5 pr-2">
                        <input value={r.field_name} onChange={(e) => edit(i, { field_name: e.target.value })}
                               className="w-full rounded border border-line bg-paper px-1.5 py-1" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <input value={r.value_raw} onChange={(e) => edit(i, { value_raw: e.target.value })} aria-invalid={bad}
                               className={`w-24 rounded border bg-paper px-1.5 py-1 ${bad ? "border-danger" : "border-line"}`} />
                      </td>
                      <td className="py-1.5 pr-2">
                        <input value={r.unit ?? ""} onChange={(e) => edit(i, { unit: e.target.value })}
                               className="w-20 rounded border border-line bg-paper px-1.5 py-1" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <select value={r.role} onChange={(e) => edit(i, { role: e.target.value as ReportRole })}
                                className="rounded border border-line bg-paper px-1 py-1">
                          {ROLES.map((x) => <option key={x} value={x}>{x}</option>)}
                        </select>
                      </td>
                      <td className="max-w-[180px] truncate py-1.5 pr-2 text-ink-soft" title={r.original_text}>{r.original_text}</td>
                      <td className="py-1.5">
                        <button onClick={() => remove(i)} aria-label="Remove row"
                                className="rounded p-1 text-ink-soft hover:bg-paper-dim hover:text-danger">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {invalid && <p className="text-caption text-danger">Each value must be a number (for example 328, -500 or 37.5).</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3">
          <button onClick={onCancel} className="rounded-lg px-3 py-1.5 text-caption text-ink-soft hover:bg-paper-dim hover:text-ink">
            Cancel
          </button>
          <button onClick={() => onConfirm(type, rows.map(toConfirmed))} disabled={invalid}
                  className="rounded-lg bg-accent px-3.5 py-1.5 text-caption font-medium text-white transition hover:bg-accent-dark disabled:opacity-40">
            Generate report
          </button>
        </div>
      </div>
    </div>
  );
}