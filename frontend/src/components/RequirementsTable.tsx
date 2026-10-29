"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Requirement } from "@/lib/types";
import { Badge, LevelBadge, ReqStatusBadge, SeverityBadge, cx } from "./ui";

export function RequirementsTable({ requirements, showEvidence = false, compact = false }: { requirements: Requirement[]; showEvidence?: boolean; compact?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr className="border-b border-slate-200">
            <th className="w-6 py-2" />
            <th className="py-2 pr-3">ID</th>
            <th className="py-2 pr-3">Requirement</th>
            <th className="py-2 pr-3">Category</th>
            <th className="py-2 pr-3">Origin</th>
            <th className="py-2 pr-3">Status</th>
            {!compact && <th className="py-2 pr-3">Evidence</th>}
          </tr>
        </thead>
        <tbody>
          {requirements.map((r) => {
            const expanded = open === r.id;
            return (
              <Fragment key={r.id}>
                <tr className={cx("border-b border-slate-100 align-top", expanded && "bg-slate-50")}>
                  <td className="py-2.5">
                    <button aria-label={expanded ? `Collapse ${r.id}` : `Expand ${r.id}`} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : r.id)} className="rounded p-0.5 text-slate-500 hover:bg-slate-200">
                      {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                  </td>
                  <td className="py-2.5 pr-3 font-mono text-xs text-slate-700">{r.id}</td>
                  <td className="py-2.5 pr-3">
                    <p className="font-medium text-slate-900">{r.title}</p>
                    {!compact && <p className="mt-0.5 text-xs text-slate-500">{r.status_reason}</p>}
                  </td>
                  <td className="py-2.5 pr-3"><span className="capitalize text-slate-700">{r.category}</span> <span className="text-xs text-slate-400">· {r.priority}</span></td>
                  <td className="py-2.5 pr-3"><Badge tone={r.origin === "confirmed" ? "brand" : r.origin === "assumption" ? "amber" : "neutral"}>{r.origin}</Badge></td>
                  <td className="py-2.5 pr-3"><ReqStatusBadge status={r.status} /></td>
                  {!compact && <td className="py-2.5 pr-3"><LevelBadge level={r.verification_level} /></td>}
                </tr>
                {expanded && (
                  <tr className="border-b border-slate-200 bg-slate-50">
                    <td />
                    <td colSpan={compact ? 5 : 6} className="pb-4 pr-3 text-[13px] text-slate-700">
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-1.5">
                          <p>{r.description}</p>
                          <p><span className="text-slate-500">Why:</span> {r.rationale}</p>
                          <p><span className="text-slate-500">Source:</span> {r.source}</p>
                          <p className="flex items-center gap-1"><span className="text-slate-500">Severity:</span> <SeverityBadge severity={r.severity} /></p>
                          <p><span className="text-slate-500">Verification:</span> {r.verification_method}</p>
                        </div>
                        <div className="space-y-1.5">
                          <p className="text-slate-500">Policies</p>
                          <div className="flex flex-wrap gap-1">{r.policies.length ? r.policies.map((p) => <Badge key={p} className="font-mono">{p}</Badge>) : <span className="text-slate-400">—</span>}</div>
                          <p className="text-slate-500">Terraform resources</p>
                          <div className="flex flex-wrap gap-1">{r.resources.length ? r.resources.map((p) => <code key={p} className="rounded bg-white px-1 py-0.5 text-xs ring-1 ring-slate-200">{p}</code>) : <span className="text-slate-400">—</span>}</div>
                          <p className="text-slate-500">Architecture decisions</p>
                          <p className="font-mono text-xs">{r.decisions.join(", ") || "—"}</p>
                        </div>
                      </div>
                      {showEvidence && r.evidence.length > 0 && (
                        <div className="mt-3">
                          <p className="text-slate-500">Evidence ({r.evidence.length})</p>
                          <ul className="mt-1 space-y-1">
                            {r.evidence.slice(0, 12).map((e, i) => (
                              <li key={i} className="flex gap-2 text-xs">
                                <Badge tone={e.outcome === "pass" ? "green" : e.outcome === "fail" ? "red" : "neutral"}>{e.outcome}</Badge>
                                <span className="font-mono text-slate-500">{e.source}</span>
                                <span className={e.kind === "simulated_check" ? "text-violet-700" : ""}>{e.detail}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
