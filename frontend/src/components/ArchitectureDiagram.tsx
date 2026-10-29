"use client";

import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Activity, BellRing, Database, Eye, Globe, HardDrive, KeyRound, Lock, Network, Router, Server, Shield, ShieldCheck, Terminal, Users } from "lucide-react";
import { useMemo } from "react";
import type { ArchOption, Component } from "@/lib/types";
import { buildLayout } from "@/lib/diagram-layout";

const ICONS: Record<string, typeof Server> = {
  users: Users, alb: Router, asg: Server, rds: Database, s3: HardDrive, cloudtrail: Eye, flowlogs: Activity, nat: Globe, waf: Shield,
  iam: KeyRound, ssm: Terminal, secrets: Lock, vpc: Network, subnet: Network, region: Globe, account: ShieldCheck, alerts: BellRing,
};
const TIER_COLOR: Record<string, string> = { edge: "#64748b", public: "#d97706", private_app: "#0d9488", private_data: "#7c3aed", regional: "#4f46e5", account: "#334155" };

type ResData = { component: Component; selected: boolean };

function ResourceNode({ data }: NodeProps<Node<ResData>>) {
  const c = data.component;
  const Icon = ICONS[c.kind] ?? Server;
  const first = Object.entries(c.details)[0];
  return (
    <div className={`w-[170px] rounded-lg border bg-white px-2.5 py-2 text-left shadow-sm transition-shadow hover:shadow-md ${data.selected ? "border-brand-600 ring-2 ring-brand-200" : "border-slate-200"}`}
         style={{ borderLeft: `4px solid ${TIER_COLOR[c.tier] ?? "#64748b"}` }}>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
      <div className="flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5 shrink-0 text-slate-600" aria-hidden />
        <span className="truncate text-[12px] font-semibold text-slate-900">{c.label}</span>
      </div>
      {first && <p className="mt-0.5 truncate text-[10.5px] text-slate-500">{first[0]}: {first[1]}</p>}
      {c.requirements.length > 0 && <p className="mt-0.5 truncate font-mono text-[9.5px] text-brand-700">{c.requirements.slice(0, 3).join(" ")}</p>}
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-300" />
    </div>
  );
}

function GroupNode({ data }: NodeProps<Node<{ label: string; tone: string; boundary?: string | null }>>) {
  return (
    <div className="h-full w-full rounded-xl border-2 border-dashed" style={{ borderColor: data.tone, background: `${data.tone}0d` }}>
      <div className="px-2 py-1 text-[11px] font-semibold" style={{ color: data.tone }}>{data.label}</div>
      {data.boundary && <div className="px-2 text-[10px] text-slate-500">{data.boundary}</div>}
    </div>
  );
}

const nodeTypes = { resource: ResourceNode, group: GroupNode };
const EDGE_STYLE: Record<string, { stroke: string; dash?: string }> = {
  traffic: { stroke: "#0f172a" }, data: { stroke: "#7c3aed", dash: "6 3" }, logs: { stroke: "#94a3b8", dash: "2 3" }, admin: { stroke: "#0369a1", dash: "6 3" }, egress: { stroke: "#d97706", dash: "4 3" },
};

export function ArchitectureDiagram({ option, selectedId, onSelect }: { option: ArchOption; selectedId: string | null; onSelect: (id: string | null) => void }) {
  const { nodes, edges } = useMemo(() => {
    const layout = buildLayout(option);
    const nodes: Node[] = layout.nodes.map((n) =>
      n.group
        ? { id: n.id, type: "group", position: n.position, data: { label: n.label, tone: n.tone, boundary: n.boundary }, style: { width: n.width, height: n.height }, selectable: false, draggable: false, zIndex: -1, ...(n.parent ? { parentId: n.parent, extent: "parent" as const } : {}) }
        : { id: n.id, type: "resource", position: n.position, data: { component: n.component!, selected: n.id === selectedId }, draggable: false, ...(n.parent ? { parentId: n.parent, extent: "parent" as const } : {}) });
    const edges: Edge[] = option.connections.filter((c) => layout.ids.has(c.source) && layout.ids.has(c.target)).map((c) => {
      const s = EDGE_STYLE[c.kind] ?? EDGE_STYLE.traffic;
      return { id: c.id, source: c.source, target: c.target, label: c.label, animated: c.kind === "traffic", style: { stroke: s.stroke, strokeDasharray: s.dash, strokeWidth: 1.4 },
               labelStyle: { fontSize: 10, fill: "#334155" }, labelBgStyle: { fill: "#fff" }, markerEnd: { type: MarkerType.ArrowClosed, color: s.stroke, width: 14, height: 14 }, zIndex: 5 };
    });
    return { nodes, edges };
  }, [option, selectedId]);

  return (
    <div className="h-[660px] w-full rounded-xl border border-slate-200 bg-slate-50/40" data-testid="architecture-diagram">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.08 }} minZoom={0.3} maxZoom={1.6}
                 nodesConnectable={false} elementsSelectable onNodeClick={(_, n) => n.type === "resource" && onSelect(n.id)} onPaneClick={() => onSelect(null)}
                 proOptions={{ hideAttribution: true }}>
        <Background gap={20} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
