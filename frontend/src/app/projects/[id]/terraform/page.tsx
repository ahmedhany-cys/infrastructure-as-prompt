"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Download, FileCode2, FileText, RotateCcw, Save, ShieldCheck, Pencil, X } from "lucide-react";
import { api, downloadUrl } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import type { Plan, Scan } from "@/lib/types";
import { CodeView } from "@/components/CodeView";
import { StepsList, ValidationControls, useValidation } from "@/components/Pipeline";
import { Alert, Badge, Button, Card, Empty, Spinner, cx, timeAgo } from "@/components/ui";

interface Files { files: Record<string, string>; generated: Record<string, string>; overrides: string[]; lock_file: string | null; revision: number; insecure_scenarios?: Record<string, string> }

export default function TerraformPage() {
  const { project, refresh } = useProject();
  const [data, setData] = useState<Files | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [active, setActive] = useState("database.tf");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red" | "amber"; text: string } | null>(null);
  const [menu, setMenu] = useState(false);

  const load = useCallback(
    () =>
      Promise.all([
        api<Files>(`/projects/${project.id}/terraform`),
        api<Scan | null>(`/projects/${project.id}/scans/latest`),
        api<{ latest_apply: Plan | null }>(`/projects/${project.id}/plans`),
      ]).then(([f, s, p]) => {
        setData(f);
        setScan(s);
        setPlan(p.latest_apply);
        setActive((a) => (a in f.files ? a : Object.keys(f.files).find((n) => n.endsWith(".tf")) ?? Object.keys(f.files)[0] ?? ""));
      }),
    [project.id],
  );
  useEffect(() => {
    load();
  }, [load]);

  const v = useValidation(project.id, () => { void load(); void refresh(); });

  if (!project.has_terraform) {
    return <Empty icon={<FileCode2 className="h-8 w-8" />} title="No Terraform generated yet" action={<Link href={`/projects/${project.id}/architecture`} className="text-sm font-medium text-brand-700 hover:underline">Choose an architecture</Link>}>Select an architecture option to generate Terraform.</Empty>;
  }
  if (!data) return <Spinner />;

  const names = Object.keys(data.files).sort((a, b) => Number(b.endsWith(".tf")) - Number(a.endsWith(".tf")) || a.localeCompare(b));
  const content = data.files[active] ?? "";
  const edited = data.overrides.includes(active);
  const stale = scan && scan.config_revision !== data.revision;

  async function save() {
    setBusy(true);
    try {
      await api(`/projects/${project.id}/terraform/files/${encodeURIComponent(active)}`, { method: "PUT", body: { content: draft } });
      setEditing(false);
      setMsg({ tone: "amber", text: `${active} saved. The previous validation no longer applies — run validation again.` });
      await load();
      await refresh();
    } catch (e) {
      setMsg({ tone: "red", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function revert(name: string) {
    setBusy(true);
    try {
      await api(`/projects/${project.id}/terraform/files/${encodeURIComponent(name)}`, { method: "DELETE" });
      setMsg({ tone: "green", text: `${name} reverted to the generated version. Run validation to confirm the fix.` });
      await load();
      await refresh();
    } catch (e) {
      setMsg({ tone: "red", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function insecure(key: string) {
    setMenu(false);
    setBusy(true);
    try {
      const r = await api<{ file: string; title: string }>(`/projects/${project.id}/terraform/insecure-change`, { method: "POST", body: { scenario: key } });
      setMsg({ tone: "amber", text: `Test change applied to ${r.file}: “${r.title}”. This is a real edit to the configuration; run validation to see whether the policy engine catches it.` });
      setActive(r.file);
      await load();
      await refresh();
    } catch (e) {
      setMsg({ tone: "red", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const fail = scan?.policy_results.filter((r) => r.outcome === "fail") ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ValidationControls v={v} />
        <div className="flex flex-wrap gap-2">
          <div className="relative">
            <Button variant="secondary" onClick={() => setMenu(!menu)} aria-expanded={menu} aria-haspopup="menu"><AlertTriangle className="h-4 w-4 text-amber-600" />Introduce insecure test change</Button>
            {menu && data.insecure_scenarios && (
              <div role="menu" className="absolute right-0 z-20 mt-1 w-80 rounded-lg border border-slate-200 bg-white p-1 shadow-lg">
                <p className="px-2 py-1.5 text-xs text-slate-500">Applies a deliberate misconfiguration as a manual edit so you can verify the policy gate. Revert the file afterwards.</p>
                {Object.entries(data.insecure_scenarios).map(([k, title]) => (
                  <button key={k} role="menuitem" onClick={() => insecure(k)} className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-amber-50">{title}</button>
                ))}
              </div>
            )}
          </div>
          <Button variant="secondary" onClick={() => downloadUrl(`/projects/${project.id}/terraform/download`)}><Download className="h-4 w-4" />Download .zip</Button>
        </div>
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}

      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <Card className="h-fit" title="Files" subtitle={`Revision ${data.revision}`}>
          <ul className="-mx-2 space-y-0.5 text-sm">
            {names.map((n) => (
              <li key={n}>
                <button onClick={() => { setActive(n); setEditing(false); }} aria-current={n === active}
                        className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left", n === active ? "bg-brand-50 font-medium text-brand-700" : "text-slate-700 hover:bg-slate-50")}>
                  {n.endsWith(".tf") ? <FileCode2 className="h-3.5 w-3.5 shrink-0" /> : <FileText className="h-3.5 w-3.5 shrink-0" />}
                  <span className="truncate">{n}</span>
                  {data.overrides.includes(n) && <Badge tone="amber" className="ml-auto">edited</Badge>}
                </button>
              </li>
            ))}
            {data.lock_file && <li className="px-2 pt-2 text-xs text-slate-500">.terraform.lock.hcl present (providers pinned)</li>}
          </ul>
        </Card>
        <Card className="min-w-0" title={<span className="font-mono">{active}</span>}
              subtitle={edited ? "Manually edited — differs from the generated version" : "Generated"}
              actions={
                editing ? (
                  <>
                    <Button variant="secondary" onClick={() => setEditing(false)}><X className="h-4 w-4" />Cancel</Button>
                    <Button onClick={save} loading={busy}><Save className="h-4 w-4" />Save</Button>
                  </>
                ) : (
                  <>
                    {edited && <Button variant="secondary" onClick={() => revert(active)} loading={busy}><RotateCcw className="h-4 w-4" />Revert to generated</Button>}
                    <Button variant="secondary" disabled={!active.endsWith(".tf")} title={active.endsWith(".tf") ? "" : "Only .tf files can be edited"} onClick={() => { setDraft(content); setEditing(true); }}><Pencil className="h-4 w-4" />Edit</Button>
                  </>
                )
              }>
          <div className="-m-4 max-h-[560px] overflow-auto">
            {editing ? (
              <textarea aria-label={`Edit ${active}`} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)}
                        className="block h-[540px] w-full resize-none border-0 bg-slate-50 p-4 font-mono text-[12.5px] leading-[1.6] focus:outline-none" />
            ) : (
              <CodeView code={content} language={active.endsWith(".tf") ? "hcl" : "text"} />
            )}
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Validation pipeline" subtitle={scan ? `Last run ${timeAgo(scan.created_at)} · config ${scan.config_sha256.slice(0, 12)}` : "Not run yet"}
              actions={scan && <Badge tone={scan.status === "passed" ? "green" : scan.status === "blocked" ? "red" : "orange"}>{scan.status}</Badge>}>
          {stale && <Alert tone="amber" className="mb-3">The configuration changed after this run. Results below describe an older revision.</Alert>}
          {scan ? <StepsList steps={scan.steps} /> : <p className="text-sm text-slate-500">Run validation to format-check, initialise, validate and plan with Terraform, then evaluate security policies.</p>}
        </Card>
        <Card title="Plan summary" subtitle={plan ? `Plan ${plan.id.slice(0, 8)} · ${plan.mode}` : "No plan yet"}
              actions={<Link href={`/projects/${project.id}/security`} className="inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"><ShieldCheck className="h-4 w-4" />Security center</Link>}>
          {plan ? (
            <div className="space-y-3 text-sm">
              <p className="font-medium text-slate-900">{plan.review.headline}</p>
              <div className="flex flex-wrap gap-1.5">
                {(["create", "update", "replace", "delete"] as const).map((k) => <Badge key={k} tone={k === "delete" || k === "replace" ? (plan.review.counts[k] ? "red" : "neutral") : "neutral"}>{plan.review.counts[k] ?? 0} {k}</Badge>)}
              </div>
              {fail.length > 0 ? (
                <Alert tone={scan?.summary.blocking ? "red" : "amber"} title={scan?.summary.blocking ? "Deployment blocked by policy" : "Policy findings"}>
                  <ul className="space-y-0.5">{fail.slice(0, 5).map((f, i) => <li key={i}><span className="font-mono text-xs">{f.policy_id}</span> {f.resource}: {f.message}</li>)}</ul>
                </Alert>
              ) : scan && <Alert tone="green">All enabled deterministic policies pass on this plan.</Alert>}
              <ul className="max-h-56 space-y-1 overflow-auto text-xs">
                {plan.review.changes.slice(0, 40).map((c) => (
                  <li key={c.address} className="flex gap-2"><Badge tone={c.action === "create" ? "green" : c.action === "update" ? "blue" : "red"}>{c.action}</Badge><span className="font-mono">{c.address}</span></li>
                ))}
              </ul>
              <Link href={`/projects/${project.id}/deploy`} className="inline-block text-sm font-medium text-brand-700 hover:underline">Review the full plan in the deployment center →</Link>
            </div>
          ) : <p className="text-sm text-slate-500">A saved Terraform plan is produced by the validation pipeline.</p>}
        </Card>
      </div>
    </div>
  );
}
