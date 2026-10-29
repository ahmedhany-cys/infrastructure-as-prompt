"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FolderPlus, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { Alert, Badge, Empty, ModePill, Money, PageHeader, Spinner, StepIcon, timeAgo } from "@/components/ui";
import { lifecycleStage, statusLabel } from "@/lib/status";

const STAGES = ["Requirements", "Architecture", "Terraform", "Security", "Deployment", "Evidence"];

function Stage({ status }: { status: string }) {
  const stage = lifecycleStage(status);
  return (
    <div className="flex items-center gap-1" title={`Step ${stage + 1} of 6: ${STAGES[stage]}`}>
      {STAGES.map((s, i) => <span key={s} className={`h-1.5 w-4 rounded-full ${i < stage ? "bg-emerald-500" : i === stage ? "bg-brand-500" : "bg-slate-200"}`} />)}
    </div>
  );
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<ProjectSummary[]>("/projects").then(setProjects).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-10 sm:px-6">
      <PageHeader eyebrow="Workspace" title="Projects"
                  actions={<Link href="/projects/new" className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm shadow-brand-600/25 hover:bg-brand-700"><FolderPlus className="h-4 w-4" /> New project</Link>}>
        Infrastructure projects in this browser workspace.
      </PageHeader>
      <div>
        {error && <Alert tone="red" title="Could not load projects">{error}</Alert>}
        {!error && projects === null && <Spinner />}
        {projects?.length === 0 && (
          <Empty icon={<FolderPlus className="h-8 w-8" />} title="No projects yet"
                 action={<Link href="/projects/new" className="rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700">Create your first project</Link>}>
            Describe what you need in plain English; the interview takes a few minutes.
          </Empty>
        )}
        {projects && projects.length > 0 && (
          <ul className="space-y-3 md:hidden">
            {projects.map((p) => (
              <li key={p.id}>
                <Link href={`/projects/${p.id}`} className="block rounded-xl border border-slate-200/80 bg-white p-4 shadow-card active:bg-slate-50">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-slate-900">{p.name}</p>
                    {p.cost && <span className="text-sm tabular-nums text-slate-700">~<Money value={p.cost.monthly_usd} />/mo</span>}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500"><Badge>{statusLabel(p.status)}</Badge><ModePill mode={p.mode} /> {timeAgo(p.updated_at)}</div>
                  <div className="mt-3"><Stage status={p.status} /></div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {projects && projects.length > 0 && (
          <div className="hidden overflow-x-auto rounded-xl border border-slate-200/80 bg-white shadow-card md:block">
            <table className="w-full min-w-[860px] text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5">Project</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Last validation</th>
                  <th className="px-4 py-2.5">Outstanding findings</th>
                  <th className="px-4 py-2.5">Deployment</th>
                  <th className="px-4 py-2.5 text-right">Est. cost / month</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {projects.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <Link href={`/projects/${p.id}`} className="font-medium text-slate-900 hover:text-brand-700">{p.name}</Link>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500"><ModePill mode={p.mode} /> updated {timeAgo(p.updated_at)}</div>
                    </td>
                    <td className="px-4 py-3"><Badge>{statusLabel(p.status)}</Badge><div className="mt-1.5"><Stage status={p.status} /></div></td>
                    <td className="px-4 py-3">
                      {p.last_scan ? (
                        <span className="inline-flex items-center gap-1.5">
                          <StepIcon status={p.last_scan.status === "passed" ? "passed" : "failed"} />
                          {p.last_scan.status === "passed" ? "Passed" : p.last_scan.status === "blocked" ? "Blocked by policy" : "Failed"}
                          <span className="text-xs text-slate-500">{timeAgo(p.last_scan.at)}{p.last_scan.stale ? " · outdated" : ""}</span>
                        </span>
                      ) : <span className="text-slate-400">Not run</span>}
                    </td>
                    <td className="px-4 py-3">
                      {p.last_scan ? (
                        p.last_scan.summary.critical + p.last_scan.summary.high + p.last_scan.summary.medium > 0 ? (
                          <span className="inline-flex flex-wrap gap-1">
                            {p.last_scan.summary.critical > 0 && <Badge tone="red"><ShieldAlert className="h-3 w-3" />{p.last_scan.summary.critical} critical</Badge>}
                            {p.last_scan.summary.high > 0 && <Badge tone="orange">{p.last_scan.summary.high} high</Badge>}
                            {p.last_scan.summary.medium > 0 && <Badge tone="amber">{p.last_scan.summary.medium} medium</Badge>}
                          </span>
                        ) : <span className="text-emerald-700">None</span>
                      ) : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {p.deployment ? <span>{p.deployment.kind === "destroy" ? "Torn down" : "Deployed"} · {p.deployment.status}{p.deployment.mode === "simulation" ? " (simulated)" : ""}</span> : <span className="text-slate-400">Not deployed</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {p.cost ? <span title={`${p.cost.option} option, approximate`}>~<Money value={p.cost.monthly_usd} /></span> : <span className="text-slate-400">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
