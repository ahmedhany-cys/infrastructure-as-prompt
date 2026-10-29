// Tiny, dependency-free HCL tokenizer for read-only syntax highlighting.
// Output is a list of typed tokens rendered as React text nodes (never HTML).
export type TokenType = "comment" | "string" | "keyword" | "number" | "bool" | "attr" | "plain";
export interface Token { type: TokenType; text: string }

const KEYWORDS = new Set(["resource", "variable", "output", "locals", "provider", "terraform", "data", "module", "required_providers", "for", "in", "if", "dynamic"]);
const RULES: [TokenType, RegExp][] = [
  ["comment", /^(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/)/],
  ["string", /^"(?:[^"\\\n]|\\.)*"/],
  ["number", /^\d+(?:\.\d+)?\b/],
  ["bool", /^(true|false|null)\b/],
  ["attr", /^[A-Za-z_][\w-]*(?=\s*=(?!=))/],
  ["plain", /^[A-Za-z_][\w-]*/],
  ["plain", /^\s+/],
  ["plain", /^./],
];

export function tokenize(src: string): Token[] {
  const out: Token[] = [];
  let rest = src;
  while (rest.length) {
    for (const [type, re] of RULES) {
      const m = re.exec(rest);
      if (m) {
        let t: TokenType = type;
        if (type === "plain" && KEYWORDS.has(m[0])) t = "keyword";
        const last = out[out.length - 1];
        if (t === "plain" && last?.type === "plain") last.text += m[0];
        else out.push({ type: t, text: m[0] });
        rest = rest.slice(m[0].length);
        break;
      }
    }
  }
  return out;
}
