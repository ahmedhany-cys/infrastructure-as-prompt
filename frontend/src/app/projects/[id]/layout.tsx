"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Check, ChevronLeft, ClipboardList, FileCode2, Network, Rocket, Settings, ShieldCheck, ScrollText } from "lucide-react";
import { ProjectProvider, useProjectLoader } from "@/lib/project-context";
import { Alert, ModePill, PageHeader, Spinner, cx } from "@/components/ui";
import { lifecycleStage, statusLabel } from "@/lib/status";

const STEPS = [
  { href: "interview", label: "Requirements", hint: "Interview & specification", icon: ClipboardList },
  { href: "architecture", label: "Architecture", hint: "Options, diagram & cost", icon: Network },
  { href: "terraform", label: "Terraform", hint: "Generate & validate", icon: FileCode2 },
  { href: "security", label: "Security", hint: "Policy gate & findings", icon: ShieldCheck },
  { href: "deploy", label: "Deployment", hint: "Review, approve, apply", icon: Rocket },
  { href: "evidence", label: "Evidence", hint: "Traceability report", icon: ScrollText },
];

const PAGE_META: Record<string, { eyebrow: string; title: string; body: string }> = {
  architecture: { eyebrow: "Step 2 · Architecture", title: "Compare architectures", body: "Options generated from your requirements. Any option that would break a must-have requirement is excluded, with the reason." },
  terraform: { eyebrow: "Step 3 · Terraform", title: "Terraform configuration", body: "Generated from the selected architecture, then formatted, validated and planned with the real Terraform CLI." },
  security: { eyebrow: "Step 4 · Security", title: "Security gate", body: "Deterministic policies evaluated on the Terraform plan. Critical findings block deployment; advisory scanners are reported separately." },
  deploy: { eyebrow: "Step 5 · Deployment", title: "Deployment center", body: "Review the exact saved plan, approve it, then apply it. Any change after approval voids the approval." },
  evidence: { eyebrow: "Step 6 · Evidence", title: "Traceability & evidence", body: "What each requirement is backed by, and how strong that evidence is." },
  settings: { eyebrow: "Project", title: "Settings", body: "Deployment mode, policy profile and project details." },
};

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { state, system, error, refresh } = useProjectLoader(id);

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10">
        <Alert tone="red" title={error.status === 404 ? "Project not found" : "Could not load project"}>
          {error.status === 404 ? "It does not exist or belongs to another workspace session." : error.message}
        </Alert>
        <Link href="/projects" className="mt-4 inline-block text-sm text-brand-700 hover:underline">Back to projects</Link>
      </main>
    );
  }
  if (!state) return <main className="mx-auto max-w-[1440px] px-6"><Spinner label="Loading project…" /></main>;
  const { project } = state;
  const reqs = project.requirements;
  const stage = lifecycleStage(project.status);
  const total = reqs ? reqs.passing + reqs.failing + reqs.unverified + reqs.blocked : 0;
  const settingsActive = pathname.endsWith("/settings");
  const meta = PAGE_META[pathname.split("/").pop() ?? ""];

  return (
    <ProjectProvider value={{ ...state, system, refresh }}>
      <div className="mx-auto flex max-w-[1440px] flex-col lg:flex-row">
        <aside className="no-print border-b border-slate-200 bg-white lg:sticky lg:top-14 lg:h-[calc(100vh-3.5rem)] lg:w-64 lg:shrink-0 lg:overflow-y-auto lg:border-b-0 lg:border-r">
          <div className="px-4 pb-3 pt-4 sm:px-6 lg:px-5 lg:pt-6">
            <Link href="/projects" className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"><ChevronLeft className="h-3.5 w-3.5" aria-hidden />All projects</Link>
            <h1 className="mt-2 truncate text-lg font-semibold tracking-tight text-slate-900" title={project.name}>{project.name}</h1>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-slate-600">{statusLabel(project.status)}</span>
              <ModePill mode={project.settings.deployment_mode} />
            </div>
            {reqs && total > 0 && (
              <div className="mt-4 hidden lg:block" aria-label="Requirement status">
                <div className="flex h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div className="bg-emerald-500" style={{ width: `${(reqs.passing / total) * 100}%` }} />
                  <div className="bg-red-500" style={{ width: `${(reqs.failing / total) * 100}%` }} />
                </div>
                <p className="mt-1.5 text-xs text-slate-600">
                  <span className="font-medium text-emerald-700">{reqs.passing} passing</span>
                  {reqs.failing > 0 && <> · <span className="font-medium text-red-700">{reqs.failing} failing</span></>}
                  {" "}· {reqs.unverified + reqs.blocked} unverified
                </p>
              </div>
            )}
          </div>
          <nav aria-label="Project sections" className="no-scrollbar flex gap-1 overflow-x-auto px-3 pb-3 sm:px-5 lg:flex-col lg:gap-0.5 lg:px-3 lg:pb-6">
            {STEPS.map(({ href, label, hint, icon: Icon }, i) => {
              const active = pathname.endsWith(`/${href}`);
              const done = stage > i;
              const current = stage === i;
              return (
                <Link key={href} href={`/projects/${id}/${href}`} aria-current={active ? "page" : undefined}
                      className={cx("group flex shrink-0 items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors",
                        active ? "bg-brand-50 text-brand-800 ring-1 ring-brand-100" : "text-slate-700 hover:bg-slate-50")}>
                  <span className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ring-1",
                    done ? "bg-emerald-500 text-white ring-emerald-500" : current ? "bg-brand-600 text-white ring-brand-600" : "bg-white text-slate-500 ring-slate-300")}>
                    {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Icon className="h-3.5 w-3.5" aria-hidden />}
                  </span>
                  <span className="min-w-0">
                    <span className={cx("block whitespace-nowrap", active && "font-semibold")}>{label}</span>
                    <span aria-hidden className="hidden text-[11px] text-slate-500 lg:block">{hint}</span>
                  </span>
                </Link>
              );
            })}
            <div className="hidden lg:my-2 lg:block lg:border-t lg:border-slate-100" />
            <Link href={`/projects/${id}/settings`} aria-current={settingsActive ? "page" : undefined}
                  className={cx("flex shrink-0 items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors", settingsActive ? "bg-brand-50 font-semibold text-brand-800 ring-1 ring-brand-100" : "text-slate-700 hover:bg-slate-50")}>
              <span className="flex h-7 w-7 items-center justify-center"><Settings className="h-4 w-4 text-slate-500" aria-hidden /></span> Settings
            </Link>
          </nav>
        </aside>
        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {meta && <div className="no-print"><PageHeader eyebrow={meta.eyebrow} title={meta.title}>{meta.body}</PageHeader></div>}
          {children}
        </main>
      </div>
    </ProjectProvider>
  );
}
