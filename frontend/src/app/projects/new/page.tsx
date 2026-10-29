"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Lightbulb, ListChecks, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { EXAMPLE_REQUEST, STARTERS } from "@/lib/example";
import { Alert, Button, Card, PageHeader, cx } from "@/components/ui";

function NewProjectForm() {
  const router = useRouter();
  const params = useSearchParams();
  const example = params.get("example") === "1";
  const [name, setName] = useState(example ? "Customer Portal" : "");
  const [request, setRequest] = useState(example ? EXAMPLE_REQUEST : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { id } = await api<{ id: string }>("/projects", { method: "POST", body: { name, request } });
      router.push(`/projects/${id}/interview`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-10 sm:px-6">
      <PageHeader eyebrow="New project" title="What do you need to run in AWS?">
        Describe it in your own words — who it is for, what it stores, how busy it gets. Nothing you write is treated as a confirmed requirement until you confirm it in the interview.
      </PageHeader>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <form onSubmit={submit} className="space-y-5">
            <div>
              <p className="text-sm font-medium text-slate-800">Start from an example</p>
              <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Example requests">
                {STARTERS.map((s) => (
                  <button key={s.id} type="button" onClick={() => { setRequest(s.request); if (!name) setName(s.name); }}
                          className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                            request === s.request ? "border-brand-300 bg-brand-50 text-brand-800" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50")}>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-slate-800">Project name</label>
              <input id="name" required minLength={3} maxLength={60} pattern="[A-Za-z0-9][A-Za-z0-9 ._\-]*" value={name} onChange={(e) => setName(e.target.value)}
                     className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100" placeholder="Customer Portal" />
              <p className="mt-1 text-xs text-slate-500">Letters, numbers, spaces, dots, dashes and underscores.</p>
            </div>
            <div>
              <div className="flex items-center justify-between">
                <label htmlFor="request" className="block text-sm font-medium text-slate-800">What do you need?</label>
                <button type="button" onClick={() => setRequest(EXAMPLE_REQUEST)} className="text-xs font-medium text-brand-700 hover:underline">Use example request</button>
              </div>
              <textarea id="request" required minLength={10} maxLength={4000} rows={7} value={request} onChange={(e) => setRequest(e.target.value)}
                        className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
                        placeholder="e.g. A secure web application for our customers in Europe with a database and file uploads, built with Node.js, that stays under $400 a month." />
              <p className="mt-1 text-right text-xs tabular-nums text-slate-400">{request.length} / 4000</p>
            </div>
            {error && <Alert tone="red" title="Could not create the project">{error}</Alert>}
            <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
              <Button type="button" variant="secondary" onClick={() => router.push("/projects")}>Cancel</Button>
              <Button type="submit" loading={busy}>Start interview</Button>
            </div>
          </form>
        </Card>
        <aside className="space-y-3 text-sm">
          {[
            { icon: Lightbulb, t: "Mention what makes you different", b: "Your industry, where your users are, the language it's built in, file uploads, busy periods, or who looks after it. These become suggestions in the interview." },
            { icon: ListChecks, t: "Then answer a short interview", b: "Questions are grouped into sections and only appear when they change the design. Each has a tailored recommendation you can accept with one click." },
            { icon: ShieldCheck, t: "Security is non-negotiable", b: "Encryption, a private database and logging are always included. Answers that would weaken them are refused with an explanation." },
          ].map(({ icon: Icon, t, b }) => (
            <div key={t} className="rounded-xl border border-slate-200/80 bg-white p-4 shadow-card">
              <p className="flex items-center gap-2 font-semibold text-slate-900"><Icon className="h-4 w-4 text-brand-600" aria-hidden />{t}</p>
              <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{b}</p>
            </div>
          ))}
        </aside>
      </div>
    </main>
  );
}

export default function NewProjectPage() {
  return (
    <Suspense>
      <NewProjectForm />
    </Suspense>
  );
}
