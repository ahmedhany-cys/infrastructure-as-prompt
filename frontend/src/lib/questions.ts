// Short labels for the customer profile; the full prompt comes from the API.
export const QUESTION_LABELS: Record<string, string> = {
  industry: "Industry",
  user_geography: "Where users are",
  environment: "Environment",
  deployment_type: "Deployment",
  existing_ack: "Existing resources",
  app_runtime: "Built with",
  traffic: "Traffic at launch",
  traffic_pattern: "Traffic pattern",
  off_hours: "Off-hours shutdown",
  needs_database: "Database",
  db_size: "Data after one year",
  file_uploads: "File storage",
  data_sensitivity: "Data stored",
  compliance: "Compliance",
  data_residency: "Data residency",
  region: "AWS region",
  availability: "Downtime tolerance",
  recovery_window: "Restore window",
  tls: "HTTPS",
  admin_access: "Server access",
  admin_cidr: "SSH range",
  audit_logging: "Audit trail",
  log_retention: "Log retention",
  ops_team: "Who runs it",
  alerting: "Alerts",
  alert_email: "Alert email",
  budget: "Monthly budget",
};
export const questionLabel = (id: string) => QUESTION_LABELS[id] ?? id.replace(/_/g, " ");

export const HINT_VALUE_LABELS: Record<string, string> = {
  north_america: "North America", middle_east_africa: "Middle East & Africa", asia_pacific: "Asia-Pacific", public_sector: "Public sector",
  business_hours: "Business hours", ecommerce: "E-commerce", saas: "SaaS", dotnet: ".NET", node: "Node.js", tolerate_minutes: "Short outages OK",
  best_effort: "Best effort", none: "None",
};
export const hintValueLabel = (v: string) => HINT_VALUE_LABELS[v] ?? v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, " ");
