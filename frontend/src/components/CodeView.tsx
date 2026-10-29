"use client";

import { tokenize } from "@/lib/hcl";

export function CodeView({ code, language }: { code: string; language: "hcl" | "text" }) {
  const lines = code.split("\n");
  const tokens = language === "hcl" ? tokenize(code) : [{ type: "plain" as const, text: code }];
  return (
    <div className="flex overflow-auto font-mono text-[12.5px] leading-[1.6]">
      <div aria-hidden className="select-none border-r border-slate-200 bg-slate-50 px-3 py-3 text-right text-slate-400">
        {lines.map((_, i) => <div key={i}>{i + 1}</div>)}
      </div>
      <pre className="min-w-0 flex-1 px-4 py-3 text-slate-800"><code>
        {tokens.map((t, i) => (t.type === "plain" ? t.text : <span key={i} className={`hcl-${t.type}`}>{t.text}</span>))}
      </code></pre>
    </div>
  );
}
