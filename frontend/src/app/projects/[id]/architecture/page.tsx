"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useState } from "react";
import { ArrowRight, Check, ClipboardList } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import type { ArchOption } from "@/lib/types";
import { Alert, Badge, Button, Card, Empty, Money, cx } from "@/components/ui";

const ArchitectureDiagram = dynamic(() => import("@/components/ArchitectureDiagram").then((m) => m.ArchitectureDiagram), { ssr: false, loading: () => <div className="h-[620px] animate-pulse rounded-lg bg-slate-100" /> });

function Score({ score }: { score: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`${score} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => <span key={i} className={cx("h-1.5 w-3 rounded-sm", i <= score ? "bg-brand-500" : "bg-slate-200")} />)}
    </span>
  );
}

function CostTable({ option }: { option: ArchOption }) {
  const c = option.cost;
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <p className="text-2xl font-semibold text-slate-900">~<Money value={c.total_monthly_usd} /><span className="text-sm font-normal text-slate-500"> / month</span></p>
        <p className="text-sm text-slate-600">fixed <Money value={c.fixed_monthly_usd} /> · variable (estimated) <Money value={c.variable_monthly_usd} /></p>
        {c.within_budget !== null && <Badge tone={c.within_budget ? "green" : "red"}>{c.within_budget ? "within budget" : "over budget"}</Badge>}
      </div>
      <p className="mt-1 text-xs text-slate-500">{c.budget_note}</p>
      <Alert tone="amber" className="mt-3" title="Approximate estimate">{c.pricing_source}. {c.pricing_as_of}.</Alert>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[620px] text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate-500"><tr className="border-b border-slate-200"><th className="py-1.5">Item</th><th>Quantity</th><th>Unit price</th><th className="text-right">Monthly</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {c.lines.map((l, i) => (
              <tr key={i} className="align-top">
                <td className="py-1.5 pr-3"><span className="text-slate-900">{l.item}</span> {l.variable && <Badge tone="amber">variable</Badge>}<div className="text-xs text-slate-500">{l.component}{l.note ? ` — ${l.note}` : ""}</div></td>
                <td className="pr-3 tabular-nums text-slate-600">{l.quantity.toLocaleString()} {l.unit}</td>
                <td className="pr-3 tabular-nums text-slate-600">${l.unit_price_usd}</td>
                <td className="text-right tabular-nums">${l.monthly_usd.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-3 text-sm">
        <div><p className="font-medium text-slate-900">Largest costs</p><ul className="mt-1 space-y-0.5 text-slate-600">{c.top_drivers.map((d) => <li key={d}>{d}</li>)}</ul></div>
        <div><p className="font-medium text-slate-900">Charges that vary with usage</p><ul className="mt-1 space-y-0.5 text-slate-600">{c.variable_charges.map((d) => <li key={d}>{d}</li>)}</ul></div>
        <div><p className="font-medium text-slate-900">Assumptions</p><ul className="mt-1 space-y-0.5 text-slate-600">{c.assumptions.map((d) => <li key={d}>{d}</li>)}</ul></div>
      </div>
    </div>
  );
}

export default function ArchitecturePage() {
  const { project, spec, arch, refresh } = useProject();
  const [viewId, setViewId] = useState<string | null>(null);
  const [selectedComp, setSelectedComp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!spec || !arch) {
    return <Empty icon={<ClipboardList className="h-8 w-8" />} title="No architecture yet" action={<Link className="text-sm font-medium text-brand-700 hover:underline" href={`/projects/${project.id}/interview`}>Go to the interview</Link>}>Complete the interview and compile the requirements first.</Empty>;
  }
  const wanted = viewId ?? arch.selected ?? arch.recommended;
  const current = arch.options.find((o) => o.id === wanted) ?? arch.options[0];
  const comp = current.components.find((c) => c.id === selectedComp) ?? null;
  const reqById = new Map(spec.requirements.map((r) => [r.id, r]));

  async function choose(id: string) {
    const edits = project.manual_edits.length > 0;
    if (edits && !confirm(`Regenerating Terraform discards your manual edits to ${project.manual_edits.join(", ")}. Continue?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/projects/${project.id}/architecture/select`, { method: "POST", body: { option_id: id, confirm_discard_edits: edits } });
      await refresh();
      setViewId(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className={cx("grid gap-4", arch.options.length === 3 ? "lg:grid-cols-3" : arch.options.length === 2 ? "md:grid-cols-2" : "")}>
        {arch.options.map((o) => {
          const isViewed = o.id === current.id;
          return (
            <button key={o.id} onClick={() => setViewId(o.id)} aria-pressed={isViewed}
                    className={cx("rounded-lg border bg-white p-4 text-left transition-colors", isViewed ? "border-brand-500 ring-2 ring-brand-100" : "border-slate-200 hover:border-slate-300")}>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-slate-900">{o.name}</h2>
                {o.id === arch.recommended && <Badge tone="brand">Recommended</Badge>}
                {o.id === arch.selected && <Badge tone="green"><Check className="h-3 w-3" />Selected</Badge>}
              </div>
              <p className="mt-1 text-sm text-slate-600">{o.summary}</p>
              <p className="mt-3 text-xl font-semibold text-slate-900">~<Money value={o.cost.total_monthly_usd} /><span className="text-xs font-normal text-slate-500"> /mo (approx.)</span></p>
              {o.cost.within_budget === false && <Badge tone="red">over budget</Badge>}
              <dl className="mt-3 space-y-1.5 text-xs">
                {Object.entries(o.tradeoffs).map(([k, t]) => (
                  <div key={k} className="grid grid-cols-[84px_auto] items-center gap-2" title={t.note}>
                    <dt className="capitalize text-slate-500">{k}</dt><dd><Score score={t.score} /></dd>
                  </div>
                ))}
              </dl>
            </button>
          );
        })}
      </div>
      {arch.excluded.length > 0 && (
        <Alert tone="neutral" title="Options not offered">
          <ul className="space-y-0.5">{arch.excluded.map((e) => <li key={e.id}><span className="font-medium">{e.name}:</span> {e.reason}</li>)}</ul>
        </Alert>
      )}
      {error && <Alert tone="red">{error}</Alert>}

      <Card title={`${current.name} architecture`} subtitle="Generated from the architecture specification — the same data the Terraform generator uses. Click a component to inspect it."
            actions={
              arch.selected === current.id ? (
                <Link href={`/projects/${project.id}/terraform`} className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700">Open Terraform <ArrowRight className="h-4 w-4" /></Link>
              ) : (
                <Button onClick={() => choose(current.id)} loading={busy}>Use {current.name} and generate Terraform</Button>
              )}>
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_300px]">
          <ArchitectureDiagram option={current} selectedId={selectedComp} onSelect={setSelectedComp} />
          <div className="rounded-lg border border-slate-200 p-3 text-sm">
            {comp ? (
              <div className="space-y-2">
                <p className="font-semibold text-slate-900">{comp.label}</p>
                <p className="text-slate-600">{comp.rationale}</p>
                {comp.security_boundary && <p className="text-xs"><Badge tone="violet">Boundary</Badge> {comp.security_boundary}</p>}
                <dl className="space-y-1 text-xs">{Object.entries(comp.details).map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-slate-500">{k}</dt><dd className="text-right text-slate-900">{v}</dd></div>)}</dl>
                <p className="pt-1 text-xs font-medium text-slate-500">Requirements</p>
                <ul className="space-y-1 text-xs">{comp.requirements.length ? comp.requirements.map((r) => <li key={r}><span className="font-mono">{r}</span> {reqById.get(r)?.title}</li>) : <li className="text-slate-400">—</li>}</ul>
                <p className="pt-1 text-xs font-medium text-slate-500">Terraform</p>
                <div className="flex flex-wrap gap-1">{comp.terraform_addresses.map((a) => <code key={a} className="rounded bg-slate-100 px-1 py-0.5 text-[11px]">{a}</code>)}</div>
              </div>
            ) : (
              <div>
                <p className="font-medium text-slate-900">Components</p>
                <ul className="mt-2 space-y-1">
                  {current.components.filter((c) => !["account", "region", "vpc"].includes(c.kind)).map((c) => (
                    <li key={c.id}><button className="text-left text-brand-700 hover:underline" onClick={() => setSelectedComp(c.id)}>{c.label}</button></li>
                  ))}
                </ul>
                <p className="mt-3 text-xs text-slate-500">Legend: solid = user traffic, purple dashed = data, blue dashed = admin, dotted = logs, amber = outbound.</p>
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Cost estimate" subtitle={`${current.name} option`}><CostTable option={current} /></Card>
        <Card title="Decisions and traceability" subtitle="Why each choice was made, and which requirements it serves.">
          <ul className="space-y-3 text-sm">
            {current.decisions.map((d) => (
              <li key={d.id} className="border-b border-slate-100 pb-2 last:border-0">
                <p className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-slate-500">{d.id}</span><span className="font-medium text-slate-900">{d.title}:</span> {d.choice}</p>
                <p className="mt-0.5 text-slate-600">{d.rationale}</p>
                {d.alternatives.length > 0 && <p className="text-xs text-slate-500">Alternatives: {d.alternatives.join("; ")}</p>}
                <div className="mt-1 flex flex-wrap gap-1">{d.requirements.map((r) => <Badge key={r} className="font-mono" title={reqById.get(r)?.title}>{r}</Badge>)}</div>
              </li>
            ))}
          </ul>
          {current.violates.length > 0 && <Alert tone="amber" className="mt-3" title="Does not satisfy">{current.violates.join(", ")}</Alert>}
        </Card>
      </div>
    </div>
  );
}
