"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Play, Square } from "lucide-react";
import { api } from "@/lib/api";
import { useOperation } from "@/lib/project-context";
import type { Operation, PipelineStep } from "@/lib/types";
import { Alert, Button, StepIcon } from "./ui";

export function useValidation(projectId: string, onFinished: (op: Operation) => void) {
  const [opId, setOpId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const op = useOperation(opId, (o) => {
    onFinished(o);
  });
  const running = Boolean(opId) && (!op || op.status === "queued" || op.status === "running");
  async function start() {
    setError(null);
    try {
      const { operation_id } = await api<{ operation_id: string }>(`/projects/${projectId}/validate`, { method: "POST" });
      setOpId(operation_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function cancel() {
    if (opId) await api(`/operations/${opId}/cancel`, { method: "POST" }).catch(() => undefined);
  }
  return { start, cancel, running, op, error };
}

export function ValidationControls({ v, label = "Run validation & security scan" }: { v: ReturnType<typeof useValidation>; label?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={v.start} loading={v.running}><Play className="h-4 w-4" />{v.running ? "Running…" : label}</Button>
      {v.running && <Button variant="secondary" onClick={v.cancel}><Square className="h-3.5 w-3.5" />Cancel</Button>}
      {v.running && v.op && <span className="text-xs text-slate-500">{v.op.progress}</span>}
      {v.error && <Alert tone="red" className="w-full">{v.error}</Alert>}
      {v.op && ["failed", "cancelled", "interrupted"].includes(v.op.status) && <Alert tone="amber" className="w-full" title={`Operation ${v.op.status}`}>{v.op.error}</Alert>}
    </div>
  );
}

export function StepsList({ steps }: { steps: PipelineStep[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ol className="divide-y divide-slate-100">
      {steps.map((s) => (
        <li key={s.name} className="py-2">
          <button className="flex w-full items-start gap-2 text-left" onClick={() => setOpen(open === s.name ? null : s.name)} aria-expanded={open === s.name} disabled={!s.output}>
            <StepIcon status={s.status} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-900">{s.name} <span className="text-xs font-normal text-slate-500">{s.status}</span></span>
              <span className="block text-xs text-slate-600">{s.summary}</span>
            </span>
            {s.output && (open === s.name ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />)}
          </button>
          {open === s.name && s.output && <pre className="mt-2 max-h-72 overflow-auto rounded bg-slate-900 p-3 text-[11.5px] leading-relaxed text-slate-100">{s.output}</pre>}
        </li>
      ))}
    </ol>
  );
}
