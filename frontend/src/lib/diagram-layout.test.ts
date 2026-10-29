import { buildLayout } from "./diagram-layout";
import type { ArchOption, Component } from "./types";

const comp = (id: string, kind = id): Component => ({ id, kind, label: id, parent: null, tier: "regional", details: {}, rationale: "", requirements: [], terraform_addresses: [], security_boundary: null });

function option(ids: string[]): ArchOption {
  return { id: "balanced", name: "Balanced", summary: "", params: { region: "us-east-1", app_subnets_private: true, db_enabled: true }, components: ids.map((i) => comp(i)),
           connections: [], decisions: [], cost: {} as ArchOption["cost"], tradeoffs: {}, satisfies: [], violates: [] };
}

describe("buildLayout", () => {
  it("places only components that exist in the specification", () => {
    const { ids } = buildLayout(option(["users", "region", "vpc", "public_subnets", "alb", "app", "logs"]));
    expect(ids.has("alb")).toBe(true);
    expect(ids.has("db")).toBe(false);
    expect(ids.has("g-data")).toBe(false);
  });

  it("puts app servers in the public tier when there are no private app subnets", () => {
    const { nodes } = buildLayout(option(["region", "vpc", "public_subnets", "alb", "app", "data_subnets", "db"]));
    expect(nodes.find((n) => n.id === "app")?.parent).toBe("g-public");
    expect(nodes.find((n) => n.id === "db")?.parent).toBe("g-data");
  });

  it("puts app servers in the private tier when it exists", () => {
    const { nodes } = buildLayout(option(["region", "vpc", "public_subnets", "app_subnets", "alb", "app", "nat"]));
    expect(nodes.find((n) => n.id === "app")?.parent).toBe("g-app");
  });

  it("wraps shared services onto a second row and grows the region to fit", () => {
    const all = ["region", "vpc", "public_subnets", "alb", "app", "iam", "ssm", "secrets", "uploads", "logs", "cloudtrail", "flowlogs", "alerts"];
    const { nodes } = buildLayout(option(all));
    const y = (id: string) => nodes.find((n) => n.id === id)?.position.y;
    expect(y("iam")).toBe(450);
    expect(y("alerts")).toBe(540);
    expect(nodes.find((n) => n.id === "g-region")?.height).toBe(700);
    const one = buildLayout(option(["region", "iam", "logs"])).nodes.find((n) => n.id === "g-region");
    expect(one?.height).toBe(610);
  });
});
