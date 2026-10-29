// Mirrors the backend Pydantic schemas (backend/app/domain).
export type ReqStatus = "unverified" | "passing" | "failing" | "blocked" | "not_applicable";
export type Severity = "critical" | "high" | "medium" | "low" | "info";

export interface EvidenceItem { kind: string; source: string; outcome: string; detail: string; observed_at: string; scan_id?: string | null; data?: Record<string, unknown> }
export interface Requirement {
  id: string; title: string; description: string; category: string; priority: string; severity: Severity; origin: string; source: string;
  rationale: string; decisions: string[]; resources: string[]; policies: string[]; verification_method: string; status: ReqStatus;
  verification_level: string; status_reason: string; evidence: EvidenceItem[];
}
export interface Assumption { id: string; statement: string; reason: string; can_change_in: string }
export interface Conflict { id: string; severity: "blocking" | "warning"; message: string; involved: string[]; suggestions: string[] }
export interface Rejected { question_id: string; value: unknown; reason: string; rejected_by: string; at: string }
export interface RequirementsSpec {
  revision: number; generated_at: string; facts: Record<string, unknown>; requirements: Requirement[]; assumptions: Assumption[];
  unresolved: string[]; conflicts: Conflict[]; rejected: Rejected[];
}
export interface Option { value: string; label: string; description: string }
export interface Question {
  id: string; section: string; prompt: string; help: string; kind: "choice" | "number" | "text"; options: Option[]; recommended: string | null;
  recommendation_reason: string | null; affects: string[]; unit: string | null;
}
export interface Answer { question_id: string; value: string | number; display: string; origin: string; answered_at: string; raw_text: string | null; interpreted_by: string }
export interface TranscriptEntry { role: "user" | "assistant" | "system"; text: string; at: string; question_id: string | null; kind: string }
export interface InterviewView {
  state: { initial_request: string; hints: { key: string; value: string; evidence: string; detected_by: string }[]; answers: Record<string, Answer>;
    rejected: Rejected[]; conflicts: Conflict[]; transcript: TranscriptEntry[]; current_question: string | null; complete: boolean; engine: string; ai_notes: string[] };
  question: Question | null; progress: { answered: number; total: number }; applicable_questions: string[]; engine_label: string;
  sections: SectionProgress[]; question_sections: Record<string, string>;
}
export interface SectionProgress { id: string; label: string; description: string; answered: number; total: number; current: boolean }
export interface Component { id: string; kind: string; label: string; parent: string | null; tier: string; details: Record<string, string>; rationale: string; requirements: string[]; terraform_addresses: string[]; security_boundary: string | null }
export interface Connection { id: string; source: string; target: string; label: string; kind: string }
export interface Decision { id: string; title: string; choice: string; rationale: string; alternatives: string[]; requirements: string[] }
export interface CostLine { component: string; item: string; quantity: number; unit: string; unit_price_usd: number; monthly_usd: number; variable: boolean; note: string }
export interface CostEstimate {
  total_monthly_usd: number; fixed_monthly_usd: number; variable_monthly_usd: number; lines: CostLine[]; assumptions: string[]; variable_charges: string[];
  top_drivers: string[]; pricing_source: string; pricing_as_of: string; approximate: boolean; budget_usd: number | null; within_budget: boolean | null; budget_note: string;
}
export interface ArchOption {
  id: "lean" | "balanced" | "resilient"; name: string; summary: string; params: Record<string, unknown> & { region: string; app_subnets_private: boolean; db_enabled: boolean };
  components: Component[]; connections: Connection[]; decisions: Decision[]; cost: CostEstimate; tradeoffs: Record<string, { score: number; note: string }>;
  satisfies: string[]; violates: string[];
}
export interface ArchitectureSpec { requirements_revision: number; recommended: string; selected: string | null; options: ArchOption[]; excluded: { id: string; name: string; reason: string }[] }
export interface ProjectSummary {
  id: string; name: string; description: string; status: string; updated_at: string; created_at: string; mode: string;
  last_scan: { id: string; status: string; at: string; summary: ScanSummary; stale: boolean } | null;
  deployment: { status: string; mode: string; kind: string; at: string } | null;
  cost: { monthly_usd: number; option: string; within_budget: boolean | null } | null;
  requirements: Record<string, number> | null;
}
export interface ProjectDetail extends ProjectSummary {
  settings: { cloud_provider: string; deployment_mode: "simulation" | "aws"; policy_profile: "standard" | "strict"; acm_certificate_arn: string | null; owner_email: string | null };
  interview: InterviewView; requirements_spec?: never; requirements: Record<string, number> | null;
  has_terraform: boolean; config_revision: number; manual_edits: string[];
}
export interface ScanSummary { critical: number; high: number; medium: number; low: number; passed: number; not_applicable: number; external_advisories: number; blocking: boolean; blocking_reason: string }
export interface PipelineStep { name: string; status: string; summary: string; started_at: string | null; finished_at: string | null; output: string }
export interface PolicyResult { policy_id: string; title: string; severity: Severity; category: string; outcome: "pass" | "fail" | "not_applicable" | "error"; resource: string | null; attribute: string | null; message: string; expected: unknown; actual: unknown; remediation: string; requirements: string[] }
export interface ExternalFinding { tool: string; rule_id: string; title: string; severity: string; resource: string | null; file: string | null; line: number | null; guideline: string | null; advisory: boolean }
export interface Scan { id: string; status: string; created_at: string; config_revision: number; stale: boolean; config_sha256: string; steps: PipelineStep[]; policy_results: PolicyResult[]; external_findings: ExternalFinding[]; summary: ScanSummary }
export interface ResourceChange { address: string; type: string; name: string; actions: string[]; action: string; stateful: boolean; risk: string; notes: string[]; changed_attributes: string[] }
export interface PlanReview { counts: Record<string, number>; changes: ResourceChange[]; destructive: boolean; data_loss_risks: string[]; downtime_risks: string[]; security_notes: string[]; cost_note: string; headline: string }
export interface Plan { id: string; kind: "apply" | "destroy"; mode: string; status: string; plan_sha256: string; config_sha256: string; review: PlanReview; scan_id: string | null; blocked_reason: string | null; approval: Record<string, unknown> | null; approved_at: string | null; created_at: string }
export interface Operation { id: string; kind: string; status: string; progress: string; log: string; result: Record<string, unknown> | null; error: string | null; created_at: string; finished_at: string | null }
export interface Deployment { id: string; plan_id: string; kind: string; mode: string; status: string; resources: { address: string; type: string; id: string | null; arn: string | null; simulated: boolean }[]; verification: { requirement: string; check: string; source: string; outcome: string; detail: string }[]; log: string; started_at: string; finished_at: string | null }
export interface SystemInfo { ai: { live: boolean; label: string }; tools: Record<string, boolean>; real_deploy_enabled: boolean; aws_expected_account_id: string | null; allowed_regions: string[] }
