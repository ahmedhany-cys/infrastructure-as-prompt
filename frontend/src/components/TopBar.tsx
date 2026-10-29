"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Plus } from "lucide-react";
import { Logo } from "./Logo";
import { cx } from "./ui";

export function TopBar() {
  const pathname = usePathname();
  const onProjects = pathname === "/projects";
  return (
    <header className="no-print sticky top-0 z-30 border-b border-white/10 bg-ink-950/95 text-white backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">
            <span className="hidden sm:inline">Infrastructure as Prompt</span><span className="sm:hidden">IaP</span>
          </span>
          <span className="hidden rounded-full border border-white/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white/60 md:inline">MVP</span>
        </Link>
        <nav className="flex items-center gap-1.5 text-sm">
          <Link href="/projects" aria-current={onProjects ? "page" : undefined}
                className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 transition-colors", onProjects ? "bg-white/10 text-white" : "text-white/70 hover:bg-white/5 hover:text-white")}>
            Projects
          </Link>
          <Link href="/projects/new" className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-white px-3 py-1.5 font-medium text-ink-950 shadow-sm transition-colors hover:bg-brand-50">
            <Plus className="h-4 w-4" aria-hidden /> New project
          </Link>
        </nav>
      </div>
    </header>
  );
}
