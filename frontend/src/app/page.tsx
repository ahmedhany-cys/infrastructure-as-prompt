import Link from "next/link";
import {
  ArrowRight, BellRing, Building2, ClipboardCheck, Clock, Cpu, FileCode2, Fingerprint, GitBranch, Globe2, HardDrive, Lock, MessagesSquare, Network,
  ScrollText, ShieldCheck, Sparkles,
} from "lucide-react";
import { EXAMPLE_REQUEST } from "@/lib/example";

const steps = [
  { icon: MessagesSquare, title: "Tailored interview", body: "Up to 27 questions about your business, application, data, recovery and operations — only the ones that change the design are asked." },
  { icon: ClipboardCheck, title: "Requirements", body: "Answers compiled into IDs, priorities and machine-checkable policies, with assumptions kept separate from what you confirmed." },
  { icon: Network, title: "Architecture", body: "Viable options compared on cost, security and availability. The diagram is drawn from the same spec as the code." },
  { icon: FileCode2, title: "Terraform", body: "Deterministic, reviewed templates — formatted, initialised, validated and planned with the real Terraform CLI." },
  { icon: ShieldCheck, title: "Policy gate", body: "A deterministic engine evaluates the plan. Critical violations block deployment and no model can override it." },
  { icon: ScrollText, title: "Evidence", body: "Requirement-to-resource traceability, with an honest record of what was verified, how, and what was not." },
];

// What the interview asks about, and what each answer changes in the generated design.
const tailoring = [
  { icon: Building2, q: "Industry", effect: "Recommended data class, compliance framework and log retention" },
  { icon: Globe2, q: "Where your users are", effect: "Suggested AWS region" },
  { icon: Cpu, q: "Runtime & traffic pattern", effect: "Server size, app port, scaling headroom and threshold" },
  { icon: Clock, q: "Business-hours traffic", effect: "Servers switched off nights and weekends (non-production)" },
  { icon: HardDrive, q: "Files & data volume", effect: "Private S3 bucket, database storage size" },
  { icon: Fingerprint, q: "Restore window", effect: "Point-in-time recovery from 1 to 35 days" },
  { icon: Lock, q: "Log retention", effect: "Lifecycle rules enforced by policy POL-LOG-004" },
  { icon: BellRing, q: "Who runs it", effect: "CloudWatch alarms to your team via an encrypted topic" },
];

export default function Landing() {
  return (
    <main>
      <section className="bg-hero relative overflow-hidden text-white">
        <div className="bg-grid pointer-events-none absolute inset-0 opacity-40 [mask-image:linear-gradient(to_bottom,black,transparent)]" aria-hidden />
        <div className="relative mx-auto grid max-w-[1280px] gap-12 px-4 py-16 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:py-24">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-medium text-white/80">
              <Sparkles className="h-3.5 w-3.5 text-signal-300" aria-hidden /> Security-first cloud architecture for small teams
            </p>
            <h1 className="mt-5 text-4xl font-semibold leading-[1.08] tracking-tight sm:text-[3.4rem]">
              Describe the infrastructure.
              <br />
              <span className="bg-gradient-to-r from-brand-300 via-white to-signal-300 bg-clip-text text-transparent">Get evidence it does what you asked.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-white/70">
              A tailored interview turns your business needs into enforceable AWS requirements, generates Terraform, gates it with deterministic security
              policies, and traces every requirement to the resources and checks that satisfy it.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/projects/new" className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-lg shadow-brand-900/30 transition hover:bg-brand-50">
                Create an infrastructure project <ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/projects" className="inline-flex items-center rounded-lg border border-white/20 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-white/10">
                View projects
              </Link>
            </div>
            <dl className="mt-10 grid max-w-lg grid-cols-3 gap-4 border-t border-white/10 pt-6">
              {[["27", "tailoring questions"], ["38", "deterministic policies"], ["3", "architecture options"]].map(([n, l]) => (
                <div key={l}>
                  <dt className="sr-only">{l}</dt>
                  <dd className="text-2xl font-semibold tabular-nums">{n}</dd>
                  <dd className="text-xs text-white/60">{l}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-6 text-xs text-white/50">AWS only. Runs in simulation mode by default — no cloud resources are created unless an operator enables real deployments.</p>
          </div>

          <div className="relative">
            <div className="absolute -inset-4 rounded-3xl bg-gradient-to-br from-brand-500/20 to-signal-500/10 blur-2xl" aria-hidden />
            <div className="relative rounded-2xl border border-white/10 bg-ink-900/80 p-5 shadow-2xl backdrop-blur">
              <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-white/50">Example request</p>
              <blockquote className="mt-3 rounded-xl border border-white/10 bg-white/5 p-4 text-[15px] leading-relaxed text-white/90">“{EXAMPLE_REQUEST}”</blockquote>
              <p className="mt-5 text-sm font-medium text-white">What happens next</p>
              <ol className="mt-3 space-y-3 text-sm text-white/70">
                <li className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-200">1</span>
                  <span>Questions grouped into 7 sections — your business, application, data, recovery, access, operations and budget.</span></li>
                <li className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-200">2</span>
                  <span>Requirements such as <code className="rounded bg-white/10 px-1 font-mono text-[12px] text-white">REQ-SEC-001</code> “Database is not reachable from the internet”.</span></li>
                <li className="flex gap-3"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-200">3</span>
                  <span>Each mapped to policies like <code className="rounded bg-white/10 px-1 font-mono text-[12px] text-white">POL-RDS-001</code>, evaluated on the real Terraform plan.</span></li>
              </ol>
              <Link href={`/projects/new?example=1`} className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand-500 px-3.5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-brand-900/40 transition hover:bg-brand-400">
                Start with this example <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-[1280px] px-4 py-16 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[0.9fr_1.4fr]">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-600">Tailor-made, not templated</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">Every answer changes the design</h2>
            <p className="mt-3 text-[15px] leading-relaxed text-slate-600">
              The interview builds a profile of your organisation and your workload. Recommendations adapt to what you have already said — a clinic gets
              different defaults from an online store — but you confirm every answer, and security controls are never removed to save money.
            </p>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2">
            {tailoring.map(({ icon: Icon, q, effect }) => (
              <li key={q} className="flex gap-3 rounded-xl border border-slate-200/80 bg-white p-4 shadow-card">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 ring-1 ring-brand-100"><Icon className="h-4.5 w-4.5" aria-hidden /></span>
                <span>
                  <span className="block text-sm font-semibold text-slate-900">{q}</span>
                  <span className="mt-0.5 block text-[13px] leading-snug text-slate-600">{effect}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="border-y border-slate-200 bg-white">
        <div className="mx-auto max-w-[1280px] px-4 py-16 sm:px-6">
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-600">The lifecycle</p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">From intent to evidence</h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {steps.map(({ icon: Icon, title, body }, i) => (
              <li key={title} className="group relative rounded-xl border border-slate-200/80 bg-slate-50/50 p-5 transition hover:border-brand-200 hover:bg-white hover:shadow-lift">
                <div className="flex items-center justify-between">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-brand-600 shadow-card ring-1 ring-slate-200 group-hover:ring-brand-200"><Icon className="h-5 w-5" aria-hidden /></span>
                  <span className="font-mono text-xs font-medium text-slate-400">{String(i + 1).padStart(2, "0")}</span>
                </div>
                <h3 className="mt-4 font-semibold text-slate-900">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto grid max-w-[1280px] gap-8 px-4 py-16 sm:px-6 lg:grid-cols-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-brand-600">Guardrails</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">Security is enforced, not suggested</h2>
          <p className="mt-3 text-sm leading-relaxed text-slate-600">The AI layer can help interpret answers. It cannot write Terraform, mark a requirement verified, approve a plan or run a command.</p>
        </div>
        <ul className="grid gap-3 text-sm text-slate-700 sm:grid-cols-2 lg:col-span-2">
          {[
            ["Deterministic policies", "38 AWS policies evaluated on the Terraform plan JSON, with positive and negative tests."],
            ["Reviewed plan = applied plan", "Approval binds to the saved plan’s SHA-256; any change voids it."],
            ["Destructive changes", "Deletes and replacements require a separate, typed confirmation."],
            ["Honest evidence", "Static analysis, simulation and live inspection are reported as different things."],
          ].map(([t, b]) => (
            <li key={t} className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-card">
              <p className="flex items-center gap-2 font-semibold text-slate-900"><GitBranch className="h-4 w-4 text-brand-600" aria-hidden />{t}</p>
              <p className="mt-1 text-slate-600">{b}</p>
            </li>
          ))}
        </ul>
      </section>
      <footer className="border-t border-slate-200 bg-white py-8 text-center text-xs text-slate-500">
        Infrastructure as Prompt — MVP. Static checks do not prove an environment is secure; see the documentation for limitations.
      </footer>
    </main>
  );
}
