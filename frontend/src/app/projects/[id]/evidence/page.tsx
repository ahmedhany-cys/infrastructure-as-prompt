"use client";

import { useEffect, useState } from "react";
import { CheckSquare, Printer, Square } from "lucide-react";
import { api, downloadUrl } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import type { ArchOption, Requirement } from "@/lib/types";
import { Alert, Badge, Button, LevelBadge, ReqStatusBadge, SeverityBadge, Spinner } from "@/components/ui";

interface Report {
  generated_at: string; deployment_mode: string; simulated: boolean;
  project: { name: string; status: string; description: string };
  lifecycle_stages: { id: string; label: string; reached: boolean }[];
  requirements_summary: Record<string, number>; requirements: Requirement[]; unresolved: string[];
  architecture: ArchOption | null;
  latest_scan: { status: string; config_sha256: string; at: string; summary: Record<string, number | boolean | string>; steps: { name: string; status: string; summary: string }[];
    policy_results: { policy_id: string; severity: string; outcome: string; resource: string | null; message: string }[]; external_findings: unknown[] } | null;
  plans: { id: string; kind: string; status: string; mode: string; headline: string | null; plan_sha256: string; created_at: string }[];
  deployments: { id: string; kind: string; mode: string; status: string; started_at: string; resources: unknown[]; verification: { requirement: string; check: string; outcome: string; detail: string }[] }[];
  limitations: string[];
}

export default function EvidencePage() {
  const { project } = useProject();
  const [rep, setRep] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Report>(`/projects/${project.id}/evidence`).then(setRep).catch((e: Error) => setError(e.message)); }, [project.id]);
  if (error) return <Alert tone="red">{error}</Alert>;
  if (!rep) return <Spinner />;
  const fails = rep.latest_scan?.policy_results.filter((r) => r.outcome === "fail") ?? [];

  return (
    <article className="mx-auto max-w-4xl space-y-6 rounded-lg border border-slate-200 bg-white p-6 sm:p-8 print:border-0 print:p-0">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-500">Evidence report</p>
          <h2 className="text-2xl font-semibold text-slate-900">{rep.project.name}</h2>
          <p className="text-sm text-slate-600">Generated {new Date(rep.generated_at).toLocaleString()} · mode {rep.deployment_mode} · status {rep.project.status}</p>
        </div>
        <div className="no-print flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />Print / save as PDF</Button>
          <Button variant="secondary" onClick={() => downloadUrl(`/projects/${project.id}/evidence?format=md`)}>Markdown</Button>
          <Button variant="secondary" onClick={() => downloadUrl(`/projects/${project.id}/evidence?format=json-download`)}>JSON</Button>
        </div>
      </header>
      {rep.simulated && <Alert tone="blue" title="SIMULATION">Deployment results in this report come from the simulation adapter. No AWS resources were created and no requirement was verified against a live environment.</Alert>}

      <section className="print-break">
        <h3 className="font-semibold text-slate-900">Lifecycle</h3>
        <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
          {rep.lifecycle_stages.map((s) => (
            <li key={s.id} className="flex items-center gap-2">{s.reached ? <CheckSquare className="h-4 w-4 text-emerald-600" /> : <Square className="h-4 w-4 text-slate-300" />}<span className={s.reached ? "text-slate-900" : "text-slate-500"}>{s.label}</span></li>
          ))}
        </ul>
      </section>

      <section className="print-break">
        <h3 className="font-semibold text-slate-900">Requirements and verification</h3>
        <p className="mt-1 text-sm text-slate-600">{Object.entries(rep.requirements_summary).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ")}</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[640px] text-xs">
            <thead className="text-left text-slate-500"><tr className="border-b"><th className="py-1.5">ID</th><th>Requirement</th><th>Status</th><th>Evidence level</th><th>Policies</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {rep.requirements.map((r) => (
                <tr key={r.id} className="align-top"><td className="py-1.5 pr-2 font-mono">{r.id}</td><td className="pr-2"><p className="font-medium text-slate-900">{r.title}</p><p className="text-slate-500">{r.status_reason}</p></td>
                  <td className="pr-2"><ReqStatusBadge status={r.status} /></td><td className="pr-2"><LevelBadge level={r.verification_level} /></td><td className="font-mono">{r.policies.join(", ") || "—"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {rep.architecture && (
        <section className="print-break">
          <h3 className="font-semibold text-slate-900">Architecture — {rep.architecture.name}</h3>
          <p className="mt-1 text-sm text-slate-600">{rep.architecture.summary} Estimated ~${rep.architecture.cost.total_monthly_usd.toFixed(0)}/month (approximate).</p>
          <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">{rep.architecture.components.filter((c) => !["users", "account", "region"].includes(c.kind)).map((c) => <li key={c.id}><span className="font-medium">{c.label}</span> — <span className="font-mono text-slate-500">{c.terraform_addresses.slice(0, 2).join(", ")}</span></li>)}</ul>
        </section>
      )}

      {rep.latest_scan && (
        <section className="print-break">
          <h3 className="font-semibold text-slate-900">Latest validation · {rep.latest_scan.status}</h3>
          <p className="font-mono text-[11px] text-slate-500">config {rep.latest_scan.config_sha256}</p>
          <ul className="mt-2 space-y-0.5 text-xs">{rep.latest_scan.steps.map((s) => <li key={s.name}><Badge tone={s.status === "passed" ? "green" : s.status === "failed" ? "red" : "neutral"}>{s.status}</Badge> {s.name} — {s.summary}</li>)}</ul>
          <p className="mt-3 text-sm font-medium text-slate-900">Policy findings ({fails.length})</p>
          {fails.length === 0 ? <p className="text-xs text-slate-600">No deterministic policy failures on the latest plan.</p> :
            <ul className="mt-1 space-y-1 text-xs">{fails.map((f, i) => <li key={i}><SeverityBadge severity={f.severity} /> <span className="font-mono">{f.policy_id}</span> {f.resource}: {f.message}</li>)}</ul>}
          <p className="mt-2 text-xs text-slate-500">{rep.latest_scan.external_findings.length} advisory findings from external scanners are included in the JSON export.</p>
        </section>
      )}

      <section className="print-break">
        <h3 className="font-semibold text-slate-900">Plans and deployments</h3>
        <ul className="mt-2 space-y-1 text-xs">
          {rep.plans.map((p) => <li key={p.id}><span className="font-mono">{p.plan_sha256.slice(0, 12)}</span> {p.kind} plan ({p.mode}) — {p.status}: {p.headline}</li>)}
          {rep.deployments.map((d) => <li key={d.id}><Badge tone={d.mode === "simulation" ? "violet" : "red"}>{d.mode === "simulation" ? "SIMULATED" : "REAL"}</Badge> {d.kind} {d.status} — {d.resources.length} resources, {new Date(d.started_at).toLocaleString()}</li>)}
          {rep.plans.length === 0 && rep.deployments.length === 0 && <li className="text-slate-500">None.</li>}
        </ul>
      </section>

      <section className="print-break">
        <h3 className="font-semibold text-slate-900">Unresolved items and limitations</h3>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{[...rep.unresolved, ...rep.limitations].map((l) => <li key={l}>{l}</li>)}</ul>
      </section>
    </article>
  );
}
