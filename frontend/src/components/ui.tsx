"use client";

import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, XCircle } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand-600 text-white shadow-sm shadow-brand-600/25 hover:bg-brand-700 disabled:bg-slate-300 disabled:shadow-none",
  secondary: "bg-white text-slate-800 border border-slate-300 shadow-sm hover:border-slate-400 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  danger: "bg-red-600 text-white shadow-sm shadow-red-600/25 hover:bg-red-700 disabled:bg-red-300",
};

export function Button({ variant = "primary", loading, children, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100", variants[variant], className)}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ children, className, title, actions, subtitle, icon }: { children: ReactNode; className?: string; title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <section className={cx("rounded-xl border border-slate-200/80 bg-white shadow-card", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-2.5">
            {icon && <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 ring-1 ring-brand-100">{icon}</span>}
            <div className="min-w-0">
              {title && <h2 className="text-[15px] font-semibold tracking-tight text-slate-900">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, children, actions }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.08em] text-brand-600">{eyebrow}</p>}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {children && <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-600">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ProgressRing({ value, size = 44, stroke = 4, label }: { value: number; size?: number; stroke?: number; label?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} className="text-slate-200" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c - (pct / 100) * c} className="text-brand-600 transition-[stroke-dashoffset] duration-500" />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[11px] font-semibold tabular-nums text-slate-800">{pct}%</span>
    </div>
  );
}

const tones = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  green: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  red: "bg-red-50 text-red-800 ring-red-200",
  amber: "bg-amber-50 text-amber-900 ring-amber-200",
  orange: "bg-orange-50 text-orange-800 ring-orange-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  violet: "bg-violet-50 text-violet-800 ring-violet-200",
  brand: "bg-brand-50 text-brand-700 ring-brand-200",
  signal: "bg-teal-50 text-teal-800 ring-teal-200",
} as const;
export type Tone = keyof typeof tones;

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap", tones[tone], className)}>{children}</span>;
}

export const severityTone: Record<string, Tone> = { critical: "red", high: "orange", medium: "amber", low: "neutral", info: "blue" };
export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={severityTone[severity.toLowerCase()] ?? "neutral"}>{severity.toUpperCase()}</Badge>;
}

const reqTone: Record<string, Tone> = { passing: "green", failing: "red", blocked: "orange", unverified: "neutral", not_applicable: "blue" };
const reqLabel: Record<string, string> = { passing: "Passing", failing: "Failing", blocked: "Blocked", unverified: "Unverified", not_applicable: "Not applicable" };
export function ReqStatusBadge({ status }: { status: string }) {
  return <Badge tone={reqTone[status] ?? "neutral"}>{reqLabel[status] ?? status}</Badge>;
}

const levelLabel: Record<string, string> = {
  none: "No evidence", estimate: "Estimate", static_config: "Static plan analysis", simulated_inspection: "Simulated", live_inspection: "Live AWS inspection",
};
export function LevelBadge({ level }: { level: string }) {
  return <Badge tone={level === "live_inspection" ? "green" : level === "static_config" ? "brand" : "neutral"} title="Strength of the evidence behind this status">{levelLabel[level] ?? level}</Badge>;
}

export function StepIcon({ status }: { status: string }) {
  const cls = "h-4 w-4 shrink-0";
  if (status === "passed" || status === "succeeded") return <CheckCircle2 className={cx(cls, "text-emerald-600")} aria-label="passed" />;
  if (status === "failed" || status === "error") return <XCircle className={cx(cls, "text-red-600")} aria-label="failed" />;
  if (status === "warning") return <AlertTriangle className={cx(cls, "text-amber-600")} aria-label="warning" />;
  if (status === "running" || status === "queued") return <Loader2 className={cx(cls, "animate-spin text-sky-600")} aria-label="running" />;
  return <CircleDashed className={cx(cls, "text-slate-400")} aria-label={status} />;
}

export function Alert({ tone = "neutral", title, children, className }: { tone?: "neutral" | "red" | "amber" | "green" | "blue"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const map = {
    neutral: "border-slate-200 bg-slate-50 text-slate-800",
    red: "border-red-200 bg-red-50 text-red-900",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    green: "border-emerald-200 bg-emerald-50 text-emerald-900",
    blue: "border-sky-200 bg-sky-50 text-sky-900",
  };
  const Icon = tone === "red" ? XCircle : tone === "amber" ? AlertTriangle : tone === "green" ? CheckCircle2 : Info;
  return (
    <div role={tone === "red" ? "alert" : "status"} className={cx("flex gap-3 rounded-lg border px-3.5 py-3 text-sm", map[tone], className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cx(title ? "mt-0.5" : "", "text-[13px] leading-relaxed")}>{children}</div>}
      </div>
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      {icon && <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">{icon}</div>}
      <p className="font-medium text-slate-900">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-slate-600">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function SimulationBanner({ mode }: { mode: string }) {
  if (mode !== "simulation") {
    return <Alert tone="red" title="REAL AWS MODE">Approved plans in this project are applied to a real AWS account and can incur charges.</Alert>;
  }
  return null;
}

export function ModePill({ mode }: { mode: string }) {
  return mode === "simulation"
    ? <Badge tone="violet" title="No AWS resources are created in simulation mode">SIMULATION</Badge>
    : <Badge tone="red" title="Plans are applied to a real AWS account">REAL AWS</Badge>;
}

export function Money({ value }: { value: number }) {
  return <>{value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })}</>;
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
