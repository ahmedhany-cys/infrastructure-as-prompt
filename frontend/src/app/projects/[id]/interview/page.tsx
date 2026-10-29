"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, Check, ChevronDown, HelpCircle, Pencil, Send, Sparkles, User, Wand2 } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import type { InterviewView, Question, SectionProgress } from "@/lib/types";
import { hintValueLabel, questionLabel } from "@/lib/questions";
import { RequirementsTable } from "@/components/RequirementsTable";
import { Alert, Badge, Button, Card, PageHeader, ProgressRing, cx } from "@/components/ui";

type AnswerBody = { value?: string | number; text?: string; accept_recommendation?: boolean };

function SectionStrip({ sections }: { sections: SectionProgress[] }) {
  return (
    <ol className="grid no-scrollbar grid-flow-col auto-cols-[minmax(8.5rem,1fr)] gap-2 overflow-x-auto pb-1" aria-label="Interview sections">
      {sections.map((s, i) => {
        const done = s.total > 0 && s.answered === s.total;
        return (
          <li key={s.id} aria-current={s.current ? "step" : undefined}
              className={cx("rounded-xl border px-3 py-2.5 transition-colors", s.current ? "border-brand-300 bg-white shadow-card ring-2 ring-brand-100" : done ? "border-emerald-200 bg-emerald-50/60" : "border-slate-200 bg-white/60")}>
            <div className="flex items-center justify-between gap-2">
              <span className={cx("text-[11px] font-semibold tabular-nums", s.current ? "text-brand-600" : done ? "text-emerald-700" : "text-slate-400")}>{String(i + 1).padStart(2, "0")}</span>
              {done ? <Check className="h-3.5 w-3.5 text-emerald-600" aria-label="complete" /> : <span className="text-[11px] tabular-nums text-slate-500">{s.answered}/{s.total}</span>}
            </div>
            <p className={cx("mt-0.5 truncate text-[13px] font-medium", s.current ? "text-slate-900" : "text-slate-700")} title={s.description}>{s.label}</p>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-100">
              <div className={cx("h-1 rounded-full transition-all", done ? "bg-emerald-500" : "bg-brand-500")} style={{ width: `${s.total ? (s.answered / s.total) * 100 : 0}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function QuestionCard({ q, onAnswer, onExplain, busy, revising, onCancel, sectionLabel, position }: {
  q: Question; busy: boolean; revising?: boolean; onCancel?: () => void; sectionLabel?: string; position?: string;
  onAnswer: (body: AnswerBody) => void; onExplain: () => void;
}) {
  const [text, setText] = useState("");
  const [num, setNum] = useState(q.kind === "number" && q.recommended ? q.recommended : "");
  const [why, setWhy] = useState(false);
  const recommended = q.options.find((o) => o.value === q.recommended);
  return (
    <div data-testid="question-card"
         className={cx("animate-fade-up rounded-xl border bg-white p-5 shadow-lift", revising ? "border-amber-300 ring-2 ring-amber-100" : "border-brand-200 ring-1 ring-brand-100")}>
      {revising && <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">Revising an earlier answer — dependent questions and checks will be re-evaluated.</p>}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        {sectionLabel && <span className="font-semibold uppercase tracking-[0.08em] text-brand-600">{sectionLabel}</span>}
        {position && <span className="text-slate-400">· {position}</span>}
      </div>
      <p data-testid="question-prompt" className="mt-1.5 text-lg font-semibold leading-snug tracking-tight text-slate-900">{q.prompt}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {q.affects.map((a) => <span key={a} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">affects {a}</span>)}
        <button type="button" onClick={() => setWhy((v) => !v)} aria-expanded={why}
                className="inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[11px] font-medium text-brand-700 hover:bg-brand-50">
          Why we ask <ChevronDown className={cx("h-3 w-3 transition-transform", why && "rotate-180")} aria-hidden />
        </button>
      </div>
      {why && <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-[13px] leading-relaxed text-slate-700">{q.help}</p>}

      {q.recommendation_reason && (
        <div className="mt-4 flex flex-wrap items-start justify-between gap-3 rounded-lg border border-brand-100 bg-gradient-to-r from-brand-50 to-white px-3.5 py-3">
          <p className="min-w-0 flex-1 text-[13px] leading-relaxed text-slate-700">
            <span className="inline-flex items-center gap-1 font-semibold text-brand-700"><Sparkles className="h-3.5 w-3.5" aria-hidden />
              {recommended ? `Recommended: ${recommended.label}` : q.kind === "number" && q.recommended ? `Recommended: $${Number(q.recommended).toLocaleString("en-US")}` : "Tip"}
            </span>
            <span className="block">{q.recommendation_reason}</span>
          </p>
          {recommended && (
            <Button variant="secondary" className="px-2.5 py-1.5 text-xs" disabled={busy} onClick={() => onAnswer({ accept_recommendation: true })}>
              <Wand2 className="h-3.5 w-3.5" aria-hidden /> Use recommendation
            </Button>
          )}
        </div>
      )}

      {q.kind === "choice" && (
        <div className="mt-4 grid gap-2 sm:grid-cols-2" role="group" aria-label="Options">
          {q.options.map((o) => {
            const rec = o.value === q.recommended;
            return (
              <button key={o.value} disabled={busy} onClick={() => onAnswer(rec ? { accept_recommendation: true } : { value: o.value })}
                      className={cx("group relative flex items-start gap-3 rounded-lg border px-3.5 py-3 text-left text-sm transition-all hover:-translate-y-px hover:border-brand-400 hover:shadow-card disabled:opacity-50",
                        rec ? "border-brand-300 bg-brand-50/40" : "border-slate-200 bg-white")}>
                <span className={cx("mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors group-hover:border-brand-500", rec ? "border-brand-400" : "border-slate-300")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2 font-medium text-slate-900">
                    {o.label} {rec && <Badge tone="brand"><Sparkles className="h-3 w-3" />Recommended</Badge>}
                  </span>
                  {o.description && <span className="mt-0.5 block text-xs text-slate-500">{o.description}</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {q.kind === "number" && (
        <form className="mt-4 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); onAnswer({ value: Number(num) }); }}>
          <div className="flex items-center rounded-lg border border-slate-300 bg-white focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
            <span className="pl-3 text-sm text-slate-500">$</span>
            <input aria-label={q.prompt} type="number" min={1} step={1} required value={num} onChange={(e) => setNum(e.target.value)}
                   className="w-32 rounded-lg bg-transparent px-2 py-2 text-sm tabular-nums focus:outline-none" />
            <span className="pr-3 text-xs text-slate-500">{q.unit}</span>
          </div>
          <Button type="submit" loading={busy}>Confirm</Button>
        </form>
      )}

      <form className="mt-4 flex gap-2 rounded-lg border border-slate-200 bg-slate-50/70 p-1.5 focus-within:border-brand-300 focus-within:bg-white"
            onSubmit={(e) => { e.preventDefault(); if (text.trim()) onAnswer({ text }); setText(""); }}>
        <input aria-label="Answer in your own words" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
               placeholder={q.id === "admin_cidr" ? "e.g. 203.0.113.0/24" : q.id === "alert_email" ? "e.g. ops@yourcompany.com" : "…or answer in your own words, or ask what something means"}
               className="min-w-0 flex-1 bg-transparent px-2 py-1.5 text-sm focus:outline-none" />
        <Button type="submit" className="px-2.5" disabled={busy || !text.trim()} aria-label="Send"><Send className="h-4 w-4" /></Button>
      </form>
      <div className="mt-2.5 flex items-center gap-3">
        <button onClick={onExplain} disabled={busy} className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 hover:text-slate-900"><HelpCircle className="h-3.5 w-3.5" />What does this mean?</button>
        {revising && onCancel && <button onClick={onCancel} className="text-xs text-slate-500 hover:underline">Cancel revision</button>}
      </div>
    </div>
  );
}

function CustomerProfile({ view, onRevise }: { view: InterviewView; onRevise: (qid: string) => void }) {
  const { state, sections, question_sections } = view;
  const answered = view.applicable_questions.filter((q) => state.answers[q]);
  return (
    <Card title="Customer profile" subtitle="Your confirmed answers — the only facts the design is built from.">
      {answered.length === 0 ? <p className="text-sm text-slate-500">Your answers will build up here as you go.</p> : (
        <div className="space-y-4">
          {sections.filter((s) => s.answered > 0).map((s) => (
            <div key={s.id}>
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">{s.label}</h3>
              <dl className="mt-1.5 divide-y divide-slate-100">
                {answered.filter((q) => question_sections[q] === s.id).map((qid) => {
                  const a = state.answers[qid];
                  return (
                    <div key={qid} className="group flex items-start justify-between gap-2 py-1.5">
                      <div className="min-w-0">
                        <dt className="text-xs text-slate-500">{questionLabel(qid)}</dt>
                        <dd className="text-sm font-medium text-slate-900">
                          {a.display}
                          {a.origin === "accepted_recommendation" && <Badge tone="brand" className="ml-1.5 align-middle">recommended</Badge>}
                          {a.interpreted_by === "ai" && <Badge tone="blue" className="ml-1.5 align-middle">AI-interpreted</Badge>}
                        </dd>
                      </div>
                      <button aria-label={`Revise ${qid}`} onClick={() => onRevise(qid)} className="rounded-lg p-1 text-slate-400 opacity-60 transition hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100"><Pencil className="h-3.5 w-3.5" /></button>
                    </div>
                  );
                })}
              </dl>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function InterviewPage() {
  const { project, spec, refresh } = useProject();
  const view: InterviewView = project.interview;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revising, setRevising] = useState<Question | null>(null);
  const [compiling, setCompiling] = useState(false);
  const transcriptRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight; // scroll the transcript only, never the page
  }, [view.state.transcript.length]);

  const hasDownstream = Boolean(spec);

  async function answer(qid: string, body: AnswerBody) {
    if (hasDownstream && revising && !confirm("Changing this answer clears the compiled requirements, architecture and generated Terraform (including manual edits). Continue?")) return;
    setBusy(true);
    setError(null);
    try {
      await api<InterviewView>(`/projects/${project.id}/interview/answer`, { method: "POST", body: { question_id: qid, ...body } });
      setRevising(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function explain(qid: string) {
    setBusy(true);
    try {
      await api<InterviewView>(`/projects/${project.id}/interview/explain`, { method: "POST", body: { question_id: qid } });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function startRevise(qid: string) {
    try {
      setRevising(await api<Question>(`/projects/${project.id}/interview/questions/${qid}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function compile() {
    setCompiling(true);
    setError(null);
    try {
      await api(`/projects/${project.id}/requirements/compile`, { method: "POST" });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCompiling(false);
    }
  }

  const { state, question, progress, sections } = view;
  const blocking = state.conflicts.filter((c) => c.severity === "blocking");
  const pct = progress.total ? Math.round((progress.answered / progress.total) * 100) : 0;
  const active = revising ?? question;
  const activeSection = active ? sections.find((s) => s.id === active.section) : undefined;
  const position = active && !revising ? `Question ${Math.min(progress.answered + 1, progress.total)} of ${progress.total}` : undefined;

  return (
    <div>
      <PageHeader eyebrow="Step 1 · Requirements" title={state.complete ? "Your requirements" : "Tell us about your project"}
                  actions={
                    <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-card">
                      <ProgressRing value={pct} label="Interview progress" />
                      <div className="text-xs">
                        <p className="font-semibold text-slate-900">{progress.answered} of {progress.total} answered</p>
                        <p className="text-slate-500">Questions adapt to your answers</p>
                      </div>
                    </div>
                  }>
        Every question changes the architecture, its security, availability or cost. Recommendations are tailored to what you have already told us — you stay in control of every answer.
      </PageHeader>

      <div className="mb-5"><SectionStrip sections={sections} /></div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-4">
          {error && <Alert tone="red">{error}</Alert>}
          {active ? (
            <QuestionCard key={`${active.id}-${revising ? "r" : "c"}`} q={active} busy={busy} revising={Boolean(revising)} onCancel={() => setRevising(null)}
                          sectionLabel={activeSection?.label} position={position}
                          onAnswer={(b) => answer(active.id, b)} onExplain={() => explain(active.id)} />
          ) : state.complete ? (
            <Alert tone="green" title="Interview complete">All questions that affect the design are answered. {spec ? "Requirements are compiled below." : "Compile the requirements specification to continue."}</Alert>
          ) : null}

          <Card title="Conversation" subtitle="Everything you and the interviewer have said. Only answers you confirm become facts.">
            <ol ref={transcriptRef} className="max-h-[300px] space-y-3 overflow-y-auto pr-1" aria-live="polite">
              {state.transcript.map((t, i) => (
                <li key={i} className={cx("flex gap-2.5", t.role === "user" && "flex-row-reverse")}>
                  <span className={cx("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", t.role === "user" ? "bg-ink-900 text-white" : "bg-gradient-to-br from-brand-500 to-teal-500 text-white")}>
                    {t.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                  </span>
                  <p className={cx("max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                    t.role === "user" ? "rounded-tr-sm bg-ink-900 text-white" : t.kind === "warning" ? "rounded-tl-sm border border-amber-200 bg-amber-50 text-amber-950" :
                    t.kind === "explanation" ? "rounded-tl-sm border border-sky-200 bg-sky-50 text-sky-950" : t.kind === "question" ? "rounded-tl-sm bg-slate-100 font-medium text-slate-900" : "rounded-tl-sm bg-slate-100 text-slate-800")}>
                    {t.text}
                  </p>
                </li>
              ))}
            </ol>
          </Card>

          <div className={cx("flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5 text-[13px]", state.engine === "ai" ? "border-sky-200 bg-sky-50 text-sky-900" : "border-slate-200 bg-white text-slate-700")} role="status">
            <Bot className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden />
            <p><span className="font-semibold">{view.engine_label}.</span>{" "}
              {state.engine === "ai" ? "The model only maps free-text answers to the options shown; every value is validated before it is recorded." :
                "Free-text answers are interpreted by a deterministic keyword parser. Set IAP_AI_PROVIDER=anthropic and an API key on the server to enable AI assistance."}</p>
          </div>

          {state.complete && !spec && (
            <Card title="Compile requirements" subtitle="Converts confirmed answers into a structured, machine-checkable specification." icon={<Sparkles className="h-4 w-4" />}>
              <p className="text-sm text-slate-600">Every requirement gets an ID, category, priority, the policies that will verify it and the Terraform resources expected to implement it. Nothing is marked as verified at this stage.</p>
              <Button className="mt-4" onClick={compile} loading={compiling} disabled={blocking.length > 0}>Compile requirements specification</Button>
            </Card>
          )}
          {spec && (
            <Card title={`Requirements specification · revision ${spec.revision}`} subtitle={`${spec.requirements.length} requirements, ${spec.assumptions.length} assumptions, ${spec.unresolved.length} unresolved items`}
                  actions={<Link href={`/projects/${project.id}/architecture`} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm shadow-brand-600/25 hover:bg-brand-700">Compare architectures <ArrowRight className="h-4 w-4" /></Link>}>
              <RequirementsTable requirements={spec.requirements} compact />
              <div className="mt-6 grid gap-5 md:grid-cols-2">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Assumptions (not confirmed by you)</h3>
                  <ul className="mt-2 space-y-2 text-sm">
                    {spec.assumptions.map((a) => (
                      <li key={a.id} className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                        <p className="text-slate-900"><span className="font-mono text-xs text-amber-800">{a.id}</span> {a.statement}</p>
                        <p className="mt-0.5 text-xs text-slate-600">{a.reason} Change in: {a.can_change_in}.</p>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Unresolved items</h3>
                  <ul className="mt-2 space-y-2 text-sm text-slate-700">
                    {spec.unresolved.length ? spec.unresolved.map((u) => <li key={u} className="rounded-lg border border-slate-200 p-3">{u}</li>) : <li className="text-slate-500">None.</li>}
                  </ul>
                </div>
              </div>
            </Card>
          )}
        </div>

        <aside className="space-y-4">
          {blocking.length > 0 && (
            <Card title="Conflicts to resolve" className="border-red-200">
              <ul className="space-y-3">
                {blocking.map((c) => (
                  <li key={c.id}>
                    <Alert tone="red" title={c.message}>
                      <ul className="mt-1 list-disc space-y-0.5 pl-4">{c.suggestions.map((s) => <li key={s}>{s}</li>)}</ul>
                    </Alert>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {c.involved.filter((q) => q in state.answers).map((q) => <Button key={q} variant="secondary" className="px-2 py-1 text-xs" onClick={() => startRevise(q)}>Revise {q.replace("_", " ")}</Button>)}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <CustomerProfile view={view} onRevise={startRevise} />
          {state.hints.length > 0 && (
            <Card title="Picked up from your request" subtitle="Used only to suggest answers — never treated as confirmed.">
              <ul className="flex flex-wrap gap-1.5">
                {state.hints.map((h) => (
                  <li key={h.key} title={`from “${h.evidence}”`} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs">
                    <span className="text-slate-500">{questionLabel(h.key === "cost" ? "budget" : h.key)}:</span> <span className="font-medium text-slate-900">{h.key === "cost" ? "keep it low" : hintValueLabel(h.value)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {(state.rejected.length > 0 || state.conflicts.some((c) => c.severity === "warning")) && (
            <Card title="Declined suggestions & warnings">
              <ul className="space-y-2 text-xs text-slate-700">
                {state.conflicts.filter((c) => c.severity === "warning").map((c) => <li key={c.id}><Alert tone="amber">{c.message}</Alert></li>)}
                {state.rejected.slice(-6).map((r, i) => (
                  <li key={i} className="rounded-lg border border-slate-200 p-2.5">
                    <Badge tone={r.rejected_by === "system" ? "red" : "neutral"}>{r.rejected_by === "system" ? "refused" : "declined"}</Badge>{" "}
                    <span className="font-medium">{questionLabel(r.question_id)}</span>: {r.reason}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {state.ai_notes.length > 0 && (
            <Card title="AI integration notes"><ul className="space-y-1 text-xs text-slate-600">{state.ai_notes.slice(-5).map((n, i) => <li key={i}>{n}</li>)}</ul></Card>
          )}
        </aside>
      </div>
    </div>
  );
}
