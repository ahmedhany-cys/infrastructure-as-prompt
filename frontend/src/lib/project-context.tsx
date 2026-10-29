"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { ArchitectureSpec, Operation, ProjectDetail, RequirementsSpec, SystemInfo } from "./types";

interface Ctx {
  project: ProjectDetail;
  spec: RequirementsSpec | null;
  arch: ArchitectureSpec | null;
  system: SystemInfo | null;
  refresh: () => Promise<void>;
}
const ProjectContext = createContext<Ctx | null>(null);

type Raw = Omit<ProjectDetail, "requirements"> & { requirements: RequirementsSpec | null; architecture: ArchitectureSpec | null };

export function useProjectLoader(id: string) {
  const [state, setState] = useState<{ project: ProjectDetail; spec: RequirementsSpec | null; arch: ArchitectureSpec | null } | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<{ status?: number; message: string } | null>(null);
  const load = useCallback(
    () =>
      api<Raw>(`/projects/${id}`).then(
        (raw) => {
          const spec = raw.requirements;
          const counts = spec ? Object.fromEntries(["passing", "failing", "unverified", "blocked", "not_applicable"].map((s) => [s, spec.requirements.filter((r) => r.status === s).length])) : null;
          setState({ project: { ...(raw as unknown as ProjectDetail), requirements: counts }, spec, arch: raw.architecture });
          setError(null);
        },
        (e: { status?: number; message: string }) => setError({ status: e.status, message: e.message }),
      ),
    [id],
  );
  const refresh = useCallback(async () => {
    await load();
  }, [load]);
  useEffect(() => {
    load();
    api<SystemInfo>("/system").then(setSystem).catch(() => setSystem(null));
  }, [load]);
  return { state, system, error, refresh };
}

export function ProjectProvider({ value, children }: { value: Ctx; children: React.ReactNode }) {
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>;
}

export function useProject(): Ctx {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used inside a project workspace");
  return ctx;
}

/** Polls an operation until it finishes. */
export function useOperation(opId: string | null, onDone?: (op: Operation) => void) {
  const [op, setOp] = useState<Operation | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });
  useEffect(() => {
    if (!opId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const o = await api<Operation>(`/operations/${opId}`);
        if (stop) return;
        setOp(o);
        if (o.status === "queued" || o.status === "running") timer = setTimeout(tick, 900);
        else done.current?.(o);
      } catch {
        if (!stop) timer = setTimeout(tick, 2000);
      }
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [opId]);
  return op;
}
