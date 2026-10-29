const LABELS: Record<string, string> = {
  interviewing: "Interviewing",
  interview_complete: "Interview complete",
  requirements_ready: "Requirements compiled",
  generated: "Terraform generated",
  modified: "Edited — not validated",
  validated: "Validated",
  blocked: "Blocked by policy",
  validation_failed: "Validation failed",
  deployed_simulated: "Deployed (simulated)",
  deployed: "Deployed",
  torn_down_simulated: "Torn down (simulated)",
  torn_down: "Torn down",
};
export const statusLabel = (s: string) => LABELS[s] ?? s;

// Index of the lifecycle step the project is currently on
// (0 Requirements, 1 Architecture, 2 Terraform, 3 Security, 4 Deployment, 5 Evidence).
const STAGE: Record<string, number> = {
  interviewing: 0,
  interview_complete: 0,
  requirements_ready: 1,
  generated: 2,
  modified: 2,
  validation_failed: 2,
  blocked: 3,
  validated: 4,
  deployed_simulated: 5,
  deployed: 5,
  torn_down_simulated: 5,
  torn_down: 5,
};
export const lifecycleStage = (s: string) => STAGE[s] ?? 0;
