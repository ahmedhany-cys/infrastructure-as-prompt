"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertOctagon, CheckCircle2, Rocket, Trash2 } from "lucide-react";
import { api, downloadUrl } from "@/lib/api";
import { useOperation, useProject } from "@/lib/project-context";
import type { Deployment, Plan } from "@/lib/types";
import { Alert, Badge, Button, Card, Empty, Spinner, StepIcon, cx, timeAgo } from "@/components/ui";

interface Plans { plans: Plan[]; latest_apply: Plan | null; latest_destroy: Plan | null; config_revision: number }

const RISK_TONE = { critical: "red", high: "orange", medium: "amber", low: "neutral", none: "neutral" } as const;

function PlanReviewView({ plan }: { plan: Plan }) {
  const r = plan.review;
  const [all, setAll] = useState(false);
  const shown = all ? r.changes : r.changes.slice(0, 15);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-base font-semibold text-slate-900">{r.headline}</p>
        {(["create", "update", "replace", "delete"] as const).map((k) => (
          <Badge key={k} tone={(k === "delete" || k === "replace") && r.counts[k] ? "red" : k === "create" ? "green" : "neutral"}>{r.counts[k] ?? 0} {k}</Badge>
        ))}
      </div>
      {r.destructive && (
        <div className="rounded-lg border-2 border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
          <p className="flex items-center gap-2 font-semibold"><AlertOctagon className="h-4 w-4" />This plan destroys or replaces resources</p>
          {r.data_loss_risks.length > 0 && <><p className="mt-2 font-medium">Data-loss risks</p><ul className="list-disc pl-5">{r.data_loss_risks.map((d) => <li key={d}>{d}</li>)}</ul></>}
        </div>
      )}
      {r.downtime_risks.length > 0 && <Alert tone="amber" title="Possible downtime"><ul className="list-disc pl-4">{r.downtime_risks.map((d) => <li key={d}>{d}</li>)}</ul></Alert>}
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="text-sm font-medium text-slate-900">Security implications</p>
          <ul className="mt-1 max-h-40 space-y-0.5 overflow-auto text-xs text-slate-600">{r.security_notes.length ? r.security_notes.map((s) => <li key={s}>{s}</li>) : <li>No security-relevant resources change.</li>}</ul>
        </div>
        <div>
          <p className="text-sm font-medium text-slate-900">Cost</p>
          <p className="mt-1 text-xs text-slate-600">{r.cost_note}</p>
          <p className="mt-2 text-sm font-medium text-slate-900">Integrity</p>
          <p className="mt-1 break-all font-mono text-[11px] text-slate-600">plan sha256 {plan.plan_sha256}</p>
          <p className="break-all font-mono text-[11px] text-slate-600">config sha256 {plan.config_sha256}</p>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs">
          <thead className="text-left text-slate-500"><tr className="border-b"><th className="py-1.5">Action</th><th>Resource</th><th>Risk</th><th>What changes</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {shown.map((c) => (
              <tr key={c.address} className={cx("align-top", (c.action === "delete" || c.action === "replace") && "bg-red-50/60")}>
                <td className="py-1.5 pr-2"><Badge tone={c.action === "create" ? "green" : c.action === "update" ? "blue" : "red"}>{c.action}</Badge></td>
                <td className="pr-2 font-mono">{c.address}{c.stateful && <Badge tone="violet" className="ml-1">stateful</Badge>}</td>
                <td className="pr-2"><Badge tone={RISK_TONE[c.risk as keyof typeof RISK_TONE] ?? "neutral"}>{c.risk}</Badge></td>
                <td className="text-slate-600">{c.notes.join(" ") || "New resource."}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {r.changes.length > 15 && <button onClick={() => setAll(!all)} className="mt-2 text-xs font-medium text-brand-700 hover:underline">{all ? "Show fewer" : `Show all ${r.changes.length} changes`}</button>}
      </div>
    </div>
  );
}

function ApprovalPanel({ plan, projectId, projectName, mode, accountId, onDone }: { plan: Plan; projectId: string; projectName: string; mode: string; accountId: string | null; onDone: () => void }) {
  const [reviewed, setReviewed] = useState(false);
  const [ackDestructive, setAckDestructive] = useState(false);
  const [typed, setTyped] = useState("");
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opId, setOpId] = useState<string | null>(null);
  const op = useOperation(opId, () => onDone());
  const destructive = plan.review.destructive;
  const ready = reviewed && (!destructive || (ackDestructive && typed === projectName)) && (mode !== "aws" || account === accountId);

  async function approve() {
    setBusy(true);
    setError(null);
    try {
      await api(`/projects/${projectId}/plans/${plan.id}/approve`, {
        method: "POST", body: { plan_sha256: plan.plan_sha256, acknowledge_destructive: ackDestructive, confirmation_text: typed || null, account_confirmation: account || null },
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function apply() {
    setBusy(true);
    setError(null);
    try {
      const { operation_id } = await api<{ operation_id: string }>(`/projects/${projectId}/plans/${plan.id}/apply`, { method: "POST" });
      setOpId(operation_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (plan.status === "approved") {
    const running = Boolean(opId) && (!op || op.status === "running" || op.status === "queued");
    return (
      <div className="space-y-3">
        <Alert tone="green" title={`Approved ${plan.approved_at ? timeAgo(plan.approved_at) : ""}`}>Approval is bound to plan {plan.plan_sha256.slice(0, 16)}… — any change to the configuration voids it.</Alert>
        <Button onClick={apply} loading={busy || running} variant={plan.kind === "destroy" ? "danger" : "primary"}>
          {plan.kind === "destroy" ? <Trash2 className="h-4 w-4" /> : <Rocket className="h-4 w-4" />}
          {mode === "simulation" ? (plan.kind === "destroy" ? "Run simulated teardown" : "Run simulated deployment") : plan.kind === "destroy" ? "Destroy real AWS resources" : "Deploy to AWS"}
        </Button>
        {op && <OpLog op={op} />}
        {error && <Alert tone="red">{error}</Alert>}
      </div>
    );
  }
  return (
    <div className="space-y-3 text-sm">
      <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />I reviewed every change in this plan.</label>
      {destructive && (
        <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3">
          <label className="flex items-start gap-2 text-red-900"><input type="checkbox" className="mt-0.5" checked={ackDestructive} onChange={(e) => setAckDestructive(e.target.checked)} />I understand resources will be destroyed or replaced and data may be lost.</label>
          <label className="block text-red-900">Type the project name <strong>{projectName}</strong> to confirm
            <input value={typed} onChange={(e) => setTyped(e.target.value)} className="mt-1 block w-full rounded border border-red-300 bg-white px-2 py-1.5" aria-label="Type project name to confirm" />
          </label>
        </div>
      )}
      {mode === "aws" && (
        <label className="block">Type the target AWS account ID <strong>{accountId}</strong> to confirm a real deployment
          <input value={account} onChange={(e) => setAccount(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5" />
        </label>
      )}
      <Button onClick={approve} disabled={!ready} loading={busy} variant={destructive ? "danger" : "primary"}><CheckCircle2 className="h-4 w-4" />Approve this exact plan</Button>
      {error && <Alert tone="red">{error}</Alert>}
    </div>
  );
}

function OpLog({ op }: { op: { status: string; log: string; error: string | null } }) {
  return (
    <div>
      <p className="flex items-center gap-2 text-sm"><StepIcon status={op.status === "succeeded" ? "passed" : op.status} />Operation {op.status}</p>
      {op.log && <pre className="mt-2 max-h-60 overflow-auto rounded bg-slate-900 p-3 text-[11.5px] leading-relaxed text-slate-100">{op.log}</pre>}
      {op.error && <Alert tone="red" className="mt-2">{op.error}</Alert>}
    </div>
  );
}

export default function DeployPage() {
  const { project, system, refresh } = useProject();
  const [plans, setPlans] = useState<Plans | null>(null);
  const [deps, setDeps] = useState<Deployment[]>([]);
  const [tdOp, setTdOp] = useState<string | null>(null);
  const [tdError, setTdError] = useState<string | null>(null);
  const load = useCallback(
    () =>
      Promise.all([api<Plans>(`/projects/${project.id}/plans`), api<Deployment[]>(`/projects/${project.id}/deployments`)]).then(([p, d]) => {
        setPlans(p);
        setDeps(d);
      }),
    [project.id],
  );
  useEffect(() => {
    load();
  }, [load]);
  const tdOperation = useOperation(tdOp, () => { void load(); });
  const onDone = () => { void load(); void refresh(); };
  const mode = project.settings.deployment_mode;

  if (!plans) return <Spinner />;
  const apply = plans.latest_apply;
  const destroy = plans.latest_destroy;
  const lastDep = deps[0];
  const deployed = lastDep && lastDep.kind === "apply" && lastDep.status === "succeeded";

  async function planTeardown() {
    setTdError(null);
    try {
      const { operation_id } = await api<{ operation_id: string }>(`/projects/${project.id}/teardown/plan`, { method: "POST" });
      setTdOp(operation_id);
    } catch (e) {
      setTdError((e as Error).message);
    }
  }

  return (
    <div className="space-y-6">
      {mode === "simulation" ? (
        <Alert tone="blue" title="Simulation mode">Approved plans are “applied” by a simulation adapter: Terraform plans run with placeholder credentials and no AWS API calls, and resulting identifiers are placeholders prefixed <code>sim-</code>. Simulated results never count as verification.
          {!system?.real_deploy_enabled && " Real AWS deployment is disabled on this server."}</Alert>
      ) : (
        <Alert tone="red" title="Real AWS mode">Approved plans are applied to account {system?.aws_expected_account_id}. This creates billable resources.</Alert>
      )}

      <Card title="Deployment plan review" subtitle={apply ? `Plan ${apply.id.slice(0, 8)} · created ${timeAgo(apply.created_at)} · status ${apply.status}` : undefined}
            actions={apply && <Badge tone={apply.status === "approved" ? "green" : apply.status === "pending_review" ? "amber" : apply.status === "applied" ? "brand" : "red"}>{apply.status.replace("_", " ")}</Badge>}>
        {!apply ? (
          <Empty icon={<Rocket className="h-8 w-8" />} title="No plan to review" action={<Link href={`/projects/${project.id}/terraform`} className="text-sm font-medium text-brand-700 hover:underline">Run validation</Link>}>
            The validation pipeline produces a saved Terraform plan for review.
          </Empty>
        ) : (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <PlanReviewView plan={apply} />
            <div className="rounded-lg border border-slate-200 p-4">
              <h3 className="text-sm font-semibold text-slate-900">Approval</h3>
              {apply.status === "rejected" && <Alert tone="red" className="mt-2" title="Blocked by policy">{apply.blocked_reason}</Alert>}
              {apply.status === "superseded" && <Alert tone="amber" className="mt-2">This plan is out of date. Run validation again to produce a new plan.</Alert>}
              {apply.status === "applied" && <Alert tone="green" className="mt-2">This plan was applied{apply.mode === "simulation" ? " in simulation" : ""}.</Alert>}
              {(apply.status === "pending_review" || apply.status === "approved") && plans.config_revision !== undefined && (
                <div className="mt-3"><ApprovalPanel plan={apply} projectId={project.id} projectName={project.name} mode={mode} accountId={system?.aws_expected_account_id ?? null} onDone={onDone} /></div>
              )}
            </div>
          </div>
        )}
      </Card>

      <Card title="Deployments" subtitle="Resource identifiers and post-deployment checks.">
        {deps.length === 0 ? <p className="text-sm text-slate-500">No deployments yet.</p> : (
          <div className="space-y-4">
            {deps.slice(0, 3).map((d) => (
              <div key={d.id} className="rounded-lg border border-slate-200 p-3">
                <p className="flex flex-wrap items-center gap-2 text-sm">
                  <StepIcon status={d.status === "succeeded" ? "passed" : d.status} />
                  <span className="font-medium text-slate-900">{d.kind === "destroy" ? "Teardown" : "Deployment"} {d.status}</span>
                  {d.mode === "simulation" ? <Badge tone="violet">SIMULATED</Badge> : <Badge tone="red">REAL AWS</Badge>}
                  <span className="text-xs text-slate-500">{timeAgo(d.started_at)} · {d.resources.length} resources</span>
                </p>
                {d.verification.length > 0 && (
                  <div className="mt-2">
                    <p className="text-xs font-medium text-slate-700">{d.mode === "simulation" ? "Simulated checks (not evidence of real infrastructure)" : "Live AWS checks"}</p>
                    <ul className="mt-1 space-y-0.5 text-xs">{d.verification.map((c, i) => <li key={i} className="flex gap-2"><Badge tone={c.outcome === "pass" ? "green" : c.outcome === "fail" ? "red" : "neutral"}>{c.outcome}</Badge><span className="font-mono">{c.requirement}</span>{c.check} — <span className="text-slate-500">{c.detail}</span></li>)}</ul>
                  </div>
                )}
                {d.resources.length > 0 && (
                  <details className="mt-2 text-xs">
                    <summary className="cursor-pointer text-slate-600">Resource identifiers</summary>
                    <ul className="mt-1 max-h-48 overflow-auto font-mono">{d.resources.map((r) => <li key={r.address}>{r.address} → {r.id ?? "—"}</li>)}</ul>
                  </details>
                )}
                <details className="mt-1 text-xs"><summary className="cursor-pointer text-slate-600">Operation log</summary><pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-900 p-2 text-slate-100">{d.log}</pre></details>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Evidence export" subtitle="Requirements, architecture, validation results, findings, plans, deployments and limitations.">
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => downloadUrl(`/projects/${project.id}/evidence?format=json-download`)}>Download JSON</Button>
            <Button variant="secondary" onClick={() => downloadUrl(`/projects/${project.id}/evidence?format=md`)}>Download Markdown</Button>
            <Link href={`/projects/${project.id}/evidence`} className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50">Open report / print to PDF</Link>
          </div>
        </Card>
        <Card title="Teardown" subtitle="Destroys resources tracked in this project’s Terraform state only.">
          <p className="text-sm text-slate-600">A destroy plan is created and must be reviewed and approved with a typed confirmation. Cleanup may not remove every billable item (final snapshots, retained logs, CloudWatch data); check the AWS Billing console after a real teardown.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="danger" onClick={planTeardown} disabled={!deployed} title={deployed ? "" : "Nothing is deployed"}><Trash2 className="h-4 w-4" />Plan teardown</Button>
            {!deployed && <span className="text-xs text-slate-500">Available after a successful deployment.</span>}
          </div>
          {tdError && <Alert tone="red" className="mt-2">{tdError}</Alert>}
          {tdOperation && tdOperation.status !== "succeeded" && <div className="mt-3"><OpLog op={tdOperation} /></div>}
          {destroy && (destroy.status === "pending_review" || destroy.status === "approved") && (
            <div className="mt-4 space-y-4 border-t border-slate-100 pt-4">
              <PlanReviewView plan={destroy} />
              <ApprovalPanel plan={destroy} projectId={project.id} projectName={project.name} mode={mode} accountId={system?.aws_expected_account_id ?? null} onDone={onDone} />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
