import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// Full requirements -> infrastructure -> evidence journey through the UI.
// Screenshots are written to docs/screenshots and are genuine renders.
const SHOTS = path.resolve(__dirname, "../../docs/screenshots");
async function shot(page: Page, name: string, fullPage = false, keepScroll = false) {
  if (!fullPage && !keepScroll) await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(SHOTS, name), fullPage, animations: "disabled" });
}
const startsWith = (label: string) => new RegExp("^" + label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));

const ANSWERS: [RegExp, string][] = [
  [/Where are most of the people/, "North America"],
  [/development\/test environment or a production/, "Production"],
  [/new deployment, or do you already/, "New deployment"],
  [/What is the application built with/, "Node.js"],
  [/how much traffic/, "Moderate"],
  [/traffic behave over a typical week/, "Fairly steady, day and night"],
  [/relational database/, "Yes, PostgreSQL"],
  [/How much data do you expect/, "Under 20 GB"],
  [/upload or download files/, "Yes, store files in a private S3 bucket"],
  [/kind of data will the application store/, "Customers' personal data"],
  [/specific compliance framework/, "None that I know of"],
  [/particular geography/, "No restriction"],
  [/Which AWS region/, "US East (N. Virginia) — us-east-1"],
  [/tolerate brief interruptions/, "Short outages (minutes to an hour) are acceptable"],
  [/how far back might you need to restore/, "7 days"],
  [/HTTPS using a certificate/, "Yes, HTTPS with an ACM certificate"],
  [/access servers for maintenance/, "AWS Systems Manager Session Manager (no open ports)"],
  [/audit trail of who changed what/, "Yes, record an audit trail"],
  [/How long must logs/, "90 days"],
  [/Who will look after this infrastructure/, "Nobody dedicated"],
  [/emailed when the application is unhealthy/, "Yes, send email alerts"],
];
const FREE_TEXT: [RegExp, string][] = [[/Which email address should receive the alerts/, "please send them to ops@example.com"]];

const prompt = (page: Page) => page.getByTestId("question-prompt");

async function currentPrompt(page: Page): Promise<string | null> {
  const el = prompt(page).first();
  if (!(await el.count())) return null;
  return el.textContent();
}

async function runValidation(page: Page, expected: "passed" | "blocked") {
  await page.getByRole("button", { name: /Run validation & security scan/ }).click();
  await expect(page.getByRole("button", { name: /Running…/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Running…/ })).toBeHidden({ timeout: 8 * 60_000 });
  const card = page.locator("section", { has: page.getByRole("heading", { name: "Validation pipeline" }) });
  await expect(card.getByText(expected, { exact: true }).first()).toBeVisible();
}

test("security-first journey from plain English to evidence and teardown", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("response", (r) => { if (r.status() >= 400 && !r.url().includes("/api/")) consoleErrors.push(`HTTP ${r.status()} ${r.url()}`); });

  // 1. Landing
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Describe the infrastructure/ })).toBeVisible();
  await shot(page, "01-landing.png");

  // 2. Initial request
  await page.getByRole("link", { name: /Start with this example/ }).click();
  await page.getByLabel("Project name").fill(`Customer Portal ${Date.now().toString().slice(-4)}`);
  await page.getByRole("button", { name: "Start interview" }).click();
  await expect(page.getByText(/Demo mode/)).toBeVisible();
  const projectName = await page.locator("h1").first().textContent();

  // Free-text answer interpreted by the deterministic parser
  await expect(prompt(page)).toHaveText(/Which best describes the business/);
  await page.getByLabel("Answer in your own words").fill("we sell software subscriptions to businesses");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(prompt(page)).toHaveText(/Where are most of the people/);

  // Adaptive, tailored questions
  for (let i = 0; i < 30; i++) {
    const text = await currentPrompt(page);
    if (!text) break;
    if (/monthly AWS budget/.test(text)) break;
    if (/upload or download files/.test(text)) {
      await expect(page.getByText("Customer profile")).toBeVisible();
      await expect(page.getByText("Production").first()).toBeVisible();
      await shot(page, "13-tailored-interview.png");
    }
    const typed = FREE_TEXT.find(([re]) => re.test(text));
    if (typed) {
      await page.getByLabel("Answer in your own words").fill(typed[1]);
      await page.getByRole("button", { name: "Send" }).click();
    } else {
      const match = ANSWERS.find(([re]) => re.test(text));
      expect(match, `unexpected question: ${text}`).toBeTruthy();
      await page.getByRole("group", { name: "Options" }).getByRole("button", { name: startsWith(match![1]) }).click();
    }
    await expect(prompt(page).first()).not.toHaveText(text);
  }
  await expect(page.getByText("ops@example.com").first()).toBeVisible();
  // Infeasible budget is detected as a conflict, not silently accepted
  await page.getByRole("spinbutton").fill("90");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/can't cover the cheapest architecture/).first()).toBeVisible();
  await shot(page, "02-requirements-interview.png");
  await page.getByRole("button", { name: /Revise budget/ }).first().click();
  await expect(page.getByText(/Revising an earlier answer/)).toBeVisible();
  await page.getByRole("spinbutton").fill("400");
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Interview complete" })).toBeVisible();
  await expect(page.getByText("$400 / month").first()).toBeVisible();

  // 3. Structured requirements
  await page.getByRole("button", { name: "Compile requirements specification" }).click();
  await expect(page.getByText(/Requirements specification · revision 1/)).toBeVisible();
  await expect(page.getByText("REQ-SEC-001")).toBeVisible();
  await shot(page, "03-requirements-summary.png", true);

  // 4-6. Architecture comparison, diagram and costs
  await page.getByRole("link", { name: /Compare architectures/ }).click();
  await expect(page.getByTestId("architecture-diagram")).toBeVisible();
  await page.getByRole("button", { name: /^Balanced/ }).click();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await page.locator(".react-flow__node", { hasText: "RDS PostgreSQL" }).click();
  await expect(page.getByText("Ingress: app security group, 5432 only")).toBeVisible();
  await shot(page, "04-architecture-diagram.png");
  await page.getByRole("heading", { name: "Cost estimate" }).scrollIntoViewIfNeeded();
  await shot(page, "05-cost-comparison.png", true);

  // 7. Generate Terraform
  await page.getByRole("button", { name: /Use Balanced and generate Terraform/ }).click();
  await page.getByRole("link", { name: /Open Terraform/ }).click();
  await expect(page.getByText("publicly_accessible").first()).toBeVisible();

  // 8. Validation and security scan
  await runValidation(page, "passed");
  await expect(page.getByText("terraform validate").first()).toBeVisible();
  await shot(page, "06-terraform-validation.png", true);

  // 9. Deliberately insecure configuration is caught by a real policy failure
  await page.getByRole("button", { name: /Introduce insecure test change/ }).click();
  await page.getByRole("menuitem", { name: /Make the database publicly accessible/ }).click();
  await expect(page.getByText(/Test change applied to database.tf/)).toBeVisible();
  await runValidation(page, "blocked");
  await page.getByRole("link", { name: "Security", exact: true }).click();
  await expect(page.getByText("Deployment is blocked")).toBeVisible();
  await expect(page.getByText("POL-RDS-001").first()).toBeVisible();
  await shot(page, "07-security-findings-insecure.png", true);

  // 10. Correct and re-run
  await page.getByRole("link", { name: "Terraform", exact: true }).click();
  await page.getByRole("button", { name: "database.tf" }).click();
  await page.getByRole("button", { name: /Revert to generated/ }).click();
  await expect(page.getByText(/reverted to the generated version/)).toBeVisible();
  await runValidation(page, "passed");
  await page.getByRole("link", { name: "Security", exact: true }).click();
  await expect(page.getByText("No blocking findings")).toBeVisible();
  await shot(page, "08-security-corrected.png", true);

  // 11. Human-readable plan review
  await page.getByRole("link", { name: "Deployment", exact: true }).click();
  await expect(page.getByText(/Plan: \d+ to create/).first()).toBeVisible();
  await shot(page, "09-deployment-plan-review.png");

  // 12. Explicit approval, then simulated deployment
  await page.getByLabel("I reviewed every change in this plan.").check();
  await page.getByRole("button", { name: "Approve this exact plan" }).click();
  await page.getByRole("button", { name: "Run simulated deployment" }).click();
  await expect(page.getByText(/Deployment succeeded/)).toBeVisible({ timeout: 5 * 60_000 });
  await expect(page.getByText("SIMULATED").first()).toBeVisible();

  // 13-14. Traceability and evidence
  await page.getByRole("link", { name: "Evidence", exact: true }).click();
  await expect(page.getByText(/No AWS resources were created/)).toBeVisible();
  await shot(page, "10-evidence-report.png", true);

  // 15. Safe teardown of simulated resources
  await page.getByRole("link", { name: "Deployment", exact: true }).click();
  await page.getByRole("button", { name: "Plan teardown" }).click();
  await expect(page.getByText(/This plan destroys or replaces resources/).first()).toBeVisible({ timeout: 3 * 60_000 });
  await page.getByLabel("I reviewed every change in this plan.").check();
  await page.getByLabel(/I understand resources will be destroyed/).check();
  await page.getByLabel("Type project name to confirm").fill(projectName!.trim());
  await page.getByRole("button", { name: "Approve this exact plan" }).click();
  await page.getByRole("button", { name: "Run simulated teardown" }).click();
  await expect(page.getByText(/Teardown succeeded/)).toBeVisible({ timeout: 3 * 60_000 });
  await shot(page, "11-teardown.png");

  // Mobile layout of the project list
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
  await shot(page, "12-mobile-projects.png");

  expect(consoleErrors.filter((e) => !/Download the React DevTools/.test(e))).toEqual([]);
});
