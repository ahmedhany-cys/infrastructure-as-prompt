"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project-context";
import { Alert, Button, Card } from "@/components/ui";

const REGIONS = [["us-east-1", "US East (N. Virginia)"], ["us-west-2", "US West (Oregon)"], ["eu-west-1", "EU (Ireland)"], ["eu-central-1", "EU (Frankfurt)"]];

export default function SettingsPage() {
  const { project, system, refresh } = useProject();
  const router = useRouter();
  const answers = project.interview.state.answers;
  const [form, setForm] = useState({
    name: project.name, description: project.description, policy_profile: project.settings.policy_profile, deployment_mode: project.settings.deployment_mode,
    acm_certificate_arn: project.settings.acm_certificate_arn ?? "", region: String(answers.region?.value ?? ""), budget: String(answers.budget?.value ?? ""),
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const changingDesign = (form.region && form.region !== String(answers.region?.value ?? "")) || (form.budget && form.budget !== String(answers.budget?.value ?? ""));
    if (changingDesign && project.has_terraform && !confirm("Changing region or budget re-opens the requirements: compiled requirements, architecture and generated Terraform are cleared. Continue?")) return;
    setBusy(true);
    setMsg(null);
    try {
      const body: Record<string, unknown> = { name: form.name, description: form.description, policy_profile: form.policy_profile, deployment_mode: form.deployment_mode, acm_certificate_arn: form.acm_certificate_arn };
      if (form.region && form.region !== String(answers.region?.value ?? "")) body.region = form.region;
      if (form.budget && form.budget !== String(answers.budget?.value ?? "")) body.budget = Number(form.budget);
      const r = await api<{ changed: string[] }>(`/projects/${project.id}/settings`, { method: "PATCH", body });
      setMsg({ tone: "green", text: r.changed.length ? `Saved: ${r.changed.join(", ")}.` : "No changes." });
      await refresh();
    } catch (err) {
      setMsg({ tone: "red", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!confirm(`Delete project “${project.name}”? This removes its records from this application. It does not touch any cloud resources.`)) return;
    try {
      await api(`/projects/${project.id}`, { method: "DELETE" });
      router.push("/projects");
    } catch (err) {
      setMsg({ tone: "red", text: (err as Error).message });
    }
  }

  const input = "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500";
  return (
    <form onSubmit={save} className="grid gap-6 lg:grid-cols-2">
      <Card title="Project">
        <div className="space-y-4 text-sm">
          <label className="block font-medium text-slate-800">Name<input className={input} value={form.name} onChange={set("name")} required minLength={3} maxLength={60} /></label>
          <label className="block font-medium text-slate-800">Description<textarea className={input} rows={3} value={form.description} onChange={set("description")} maxLength={500} /></label>
        </div>
      </Card>
      <Card title="Cloud and budget" subtitle="Region and budget are interview answers; changing them re-opens the requirements.">
        <div className="space-y-4 text-sm">
          <label className="block font-medium text-slate-800">Cloud provider
            <select className={input} value="aws" disabled><option value="aws">Amazon Web Services</option></select>
            <span className="mt-1 block text-xs font-normal text-slate-500">Only AWS is supported in this release.</span>
          </label>
          <label className="block font-medium text-slate-800">Region
            <select className={input} value={form.region} onChange={set("region")} disabled={!answers.region}>
              {!answers.region && <option value="">Answer the interview first</option>}
              {REGIONS.map(([v, l]) => <option key={v} value={v}>{l} — {v}</option>)}
            </select>
          </label>
          <label className="block font-medium text-slate-800">Monthly budget (USD)
            <input className={input} type="number" min={1} value={form.budget} onChange={set("budget")} disabled={!answers.budget} placeholder="Answer the interview first" />
          </label>
        </div>
      </Card>
      <Card title="Policies and deployment">
        <div className="space-y-4 text-sm">
          <label className="block font-medium text-slate-800">Policy profile
            <select className={input} value={form.policy_profile} onChange={set("policy_profile")}>
              <option value="standard">Standard — critical findings block deployment</option>
              <option value="strict">Strict — critical and high findings block deployment</option>
            </select>
          </label>
          <label className="block font-medium text-slate-800">Deployment mode
            <select className={input} value={form.deployment_mode} onChange={set("deployment_mode")}>
              <option value="simulation">Simulation (no AWS resources)</option>
              <option value="aws" disabled={!system?.real_deploy_enabled}>Real AWS{system?.real_deploy_enabled ? "" : " — disabled by the server operator"}</option>
            </select>
            {!system?.real_deploy_enabled && <span className="mt-1 block text-xs font-normal text-slate-500">Real deployments require the server operator to set IAP_ALLOW_REAL_DEPLOY=true, IAP_AWS_EXPECTED_ACCOUNT_ID and an AWS profile. AWS keys are never entered in this interface.</span>}
          </label>
          <label className="block font-medium text-slate-800">ACM certificate ARN (real deployments)
            <input className={input} value={form.acm_certificate_arn} onChange={set("acm_certificate_arn")} placeholder="arn:aws:acm:us-east-1:123456789012:certificate/…" />
          </label>
        </div>
      </Card>
      <Card title="AI integration">
        <div className="space-y-2 text-sm text-slate-700">
          <p><span className="font-medium">Status:</span> {system?.ai.label ?? "unknown"}</p>
          <p className="text-xs text-slate-500">The AI provider is configured on the server (IAP_AI_PROVIDER, IAP_ANTHROPIC_API_KEY, IAP_ANTHROPIC_MODEL). Keys are never sent to the browser. The model can only map free-text interview answers to allowed options; it cannot generate Terraform, approve plans or mark requirements verified.</p>
          <p className="text-xs text-slate-500">Tools on this server: {system ? Object.entries(system.tools).map(([k, v]) => `${k} ${v ? "✓" : "✗"}`).join(" · ") : "—"}</p>
        </div>
      </Card>
      <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
        <Button type="submit" loading={busy}>Save settings</Button>
        {msg && <Alert tone={msg.tone} className="flex-1">{msg.text}</Alert>}
      </div>
      <Card title="Danger zone" className="border-red-200 lg:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p className="text-slate-600">Delete this project and its records. Refused if it still manages real AWS resources.</p>
          <Button type="button" variant="danger" onClick={remove}>Delete project</Button>
        </div>
      </Card>
    </form>
  );
}
