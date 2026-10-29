// Deterministic diagram layout derived from the architecture specification.
// Nothing here invents components: every node is a component from the spec.
import type { ArchOption, Component } from "./types";

export interface LayoutNode {
  id: string;
  label: string;
  position: { x: number; y: number };
  parent?: string;
  group?: boolean;
  width?: number;
  height?: number;
  tone?: string;
  boundary?: string | null;
  component?: Component;
}

const ROW = ["iam", "ssm", "secrets", "uploads", "logs", "cloudtrail", "flowlogs", "alerts"];
const PER_ROW = 6;

export function buildLayout(option: ArchOption): { nodes: LayoutNode[]; ids: Set<string> } {
  const byId = new Map(option.components.map((c) => [c.id, c]));
  const nodes: LayoutNode[] = [];
  const res = (id: string, x: number, y: number, parent?: string) => {
    const c = byId.get(id);
    if (c) nodes.push({ id, label: c.label, position: { x, y }, parent, component: c });
  };
  const group = (id: string, compId: string, x: number, y: number, w: number, h: number, tone: string, parent?: string) => {
    const c = byId.get(compId);
    if (!c) return false;
    nodes.push({ id, label: c.label, position: { x, y }, width: w, height: h, group: true, tone, parent, boundary: c.security_boundary });
    return true;
  };
  const privateApp = byId.has("app_subnets");
  const regional = ROW.filter((id) => byId.has(id));
  const rows = Math.max(1, Math.ceil(regional.length / PER_ROW));
  res("users", 0, 190);
  res("waf", 0, 320);
  group("g-region", "region", 230, 0, 1090, 520 + rows * 90, "#334155");
  group("g-vpc", "vpc", 20, 40, 850, 370, "#0369a1", "g-region");
  group("g-public", "public_subnets", 20, 50, 250, 300, "#d97706", "g-vpc");
  res("alb", 40, 60, "g-public");
  if (privateApp) {
    res("nat", 40, 200, "g-public");
    group("g-app", "app_subnets", 300, 50, 250, 300, "#0e7563", "g-vpc");
    res("app", 40, 120, "g-app");
  } else {
    res("app", 40, 200, "g-public");
  }
  if (group("g-data", "data_subnets", 580, 50, 250, 300, "#7c3aed", "g-vpc")) res("db", 40, 120, "g-data");
  regional.forEach((id, i) => res(id, 30 + (i % PER_ROW) * 175, 450 + Math.floor(i / PER_ROW) * 90, "g-region"));
  return { nodes, ids: new Set(nodes.map((n) => n.id)) };
}
