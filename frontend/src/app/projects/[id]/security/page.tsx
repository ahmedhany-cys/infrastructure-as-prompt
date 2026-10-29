"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ShieldCheck, ShieldX } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import type { PolicyResult, Scan } from "@/lib/types";
import { RequirementsTable } from "@/components/RequirementsTable";
import { ValidationControls, useValidation } from "@/components/Pipeline";
import { Alert, Badge, Card, Empty, SeverityBadge, Spinner, timeAgo } from "@/components/ui";

const ORDER = ["critical", "high", "medium", "low"] as const;

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function Finding({ r }: { r: PolicyResult }) {
  return (
    <li className="rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={r.severity} />
        <span className="font-mono text-xs text-slate-500">{r.policy_id}</span>
        <span className="font-medium text-slate-900">{r.title}</span>
      </div>
      <p className="mt-1.5 text-sm text-slate-800">{r.message}</p>
      <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[110px_minmax(0,1fr)]">
        <dt className="text-slate-500">Resource</dt><dd className="font-mono break-all">{r.resource ?? "—"}{r.attribute ? ` · ${r.attribute}` : ""}</dd>
        <dt className="text-slate-500">Expected</dt><dd className="font-mono break-all">{fmt(r.expected)}</dd>
        <dt className="text-slate-500">Found in plan</dt><dd className="font-mono break-all text-red-700">{fmt(r.actual)}</dd>
        <dt className="text-slate-500">Requirements</dt><dd>{r.requirements.length ? r.requirements.join(", ") : "Baseline policy"}</dd>
      </dl>
      {r.remediation && <p className="mt-2 rounded bg-emerald-50 px-2 py-1.5 text-xs text-emerald-900"><span className="font-medium">Remediation:</span> {r.remediation}</p>}
    </li>
  );
}

export default function SecurityPage() {
  const { project, spec, refresh } = useProject();
  const [scan, setScan] = useState<Scan | null | undefined>(undefined);
  const [showPassed, setShowPassed] = useState(false);
  const load = useCallback(() => api<Scan | null>(`/projects/${project.id}/scans/latest`).then(setScan), [project.id]);
  useEffect(() => { void load(); }, [load]);
  const v = useValidation(project.id, () => { void load(); void refresh(); });

  if (scan === undefined) return <Spinner />;
  const fails = scan?.policy_results.filter((r) => r.outcome === "fail" || r.outcome === "error") ?? [];
  const passes = scan?.policy_results.filter((r) => r.outcome === "pass") ?? [];
  const na = scan?.policy_results.filter((r) => r.outcome === "not_applicable") ?? [];
  const policiesPassing = new Set(passes.map((p) => p.policy_id));
  const policiesFailing = new Set(fails.map((p) => p.policy_id));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Security center</h2>
          <p className="text-sm text-slate-600">Deterministic policies evaluated on the saved Terraform plan. Policy profile: <strong>{project.settings.policy_profile}</strong> ({project.settings.policy_profile === "strict" ? "critical and high findings block" : "critical findings block"}).</p>
        </div>
        {project.has_terraform && <ValidationControls v={v} label="Re-run scan" />}
      </div>

      {!scan ? (
        <Empty icon={<ShieldCheck className="h-8 w-8" />} title="No scan results yet" action={<Link className="text-sm font-medium text-brand-700 hover:underline" href={`/projects/${project.id}/terraform`}>Open the Terraform workspace</Link>}>
          Generate Terraform and run the validation pipeline.
        </Empty>
      ) : (
        <>
          {scan.stale && <Alert tone="amber" title="Results are out of date">The configuration changed after this scan ({timeAgo(scan.created_at)}). Re-run the scan before relying on these results.</Alert>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[["Critical", scan.summary.critical, "text-red-700"], ["High", scan.summary.high, "text-orange-700"], ["Medium", scan.summary.medium, "text-amber-700"], ["Checks passed", scan.summary.passed, "text-emerald-700"], ["Advisories (external)", scan.summary.external_advisories, "text-slate-700"]].map(([l, n, c]) => (
              <div key={l as string} className="rounded-lg border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">{l}</p><p className={`mt-1 text-2xl font-semibold ${c}`}>{n as number}</p></div>
            ))}
          </div>
          {scan.summary.blocking ? (
            <Alert tone="red" title="Deployment is blocked">{scan.summary.blocking_reason}. Fix the configuration (or revert the manual edit) and re-run the scan.</Alert>
          ) : (
            <Alert tone="green" title="No blocking findings">Deployment may proceed to plan review. This is static analysis of the planned configuration; it does not prove the running environment is secure.</Alert>
          )}

          <Card title={`Findings (${fails.length})`} subtitle="Grouped by severity, with evidence from the plan.">
            {fails.length === 0 ? <p className="flex items-center gap-2 text-sm text-emerald-700"><ShieldCheck className="h-4 w-4" />No policy violations.</p> : (
              <div className="space-y-5">
                {ORDER.filter((s) => fails.some((f) => f.severity === s)).map((sev) => (
                  <div key={sev}>
                    <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold capitalize text-slate-900"><ShieldX className="h-4 w-4" />{sev}</h3>
                    <ul className="space-y-2">{fails.filter((f) => f.severity === sev).map((f, i) => <Finding key={i} r={f} />)}</ul>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Policy test results" subtitle={`${policiesPassing.size} policies passing, ${policiesFailing.size} failing, ${new Set(na.map((n) => n.policy_id)).size} not applicable`}
                actions={<button onClick={() => setShowPassed(!showPassed)} className="text-sm font-medium text-brand-700 hover:underline">{showPassed ? "Hide" : "Show"} all results</button>}>
            {showPassed ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-xs">
                  <thead className="text-left text-slate-500"><tr className="border-b"><th className="py-1.5">Policy</th><th>Outcome</th><th>Resource</th><th>Detail</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {scan.policy_results.map((r, i) => (
                      <tr key={i} className="align-top"><td className="py-1.5 pr-2"><span className="font-mono">{r.policy_id}</span> <span className="text-slate-500">{r.title}</span></td>
                        <td className="pr-2"><Badge tone={r.outcome === "pass" ? "green" : r.outcome === "fail" ? "red" : "neutral"}>{r.outcome}</Badge></td>
                        <td className="pr-2 font-mono">{r.resource ?? "—"}</td><td className="text-slate-600">{r.message}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="text-sm text-slate-600">Every policy result — including passes and not-applicable outcomes — is recorded and exported in the evidence report.</p>}
          </Card>

          {scan.external_findings.length > 0 && (
            <Card title={`External scanner advisories (${scan.external_findings.length})`} subtitle="Checkov and Trivy findings are shown for context and do not gate deployment; some conflict with deliberate design choices (for example, an internet-facing load balancer).">
              <div className="max-h-80 overflow-auto">
                <table className="w-full min-w-[640px] text-xs">
                  <thead className="text-left text-slate-500"><tr className="border-b"><th className="py-1.5">Tool</th><th>Rule</th><th>Severity</th><th>Resource</th><th>Title</th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {scan.external_findings.map((f, i) => (
                      <tr key={i}><td className="py-1.5 pr-2">{f.tool}</td><td className="pr-2 font-mono">{f.rule_id}</td><td className="pr-2">{f.severity}</td><td className="pr-2 font-mono">{f.resource}</td><td>{f.title}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}

      {spec && (
        <Card title="Requirement verification status" subtitle="Derived only from policy results, cost estimates and inspection evidence — never from AI output.">
          <RequirementsTable requirements={spec.requirements} showEvidence />
        </Card>
      )}
    </div>
  );
}
