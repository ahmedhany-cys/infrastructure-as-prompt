import { tokenize } from "./hcl";

describe("tokenize", () => {
  it("round-trips the source text exactly", () => {
    const src = 'resource "aws_db_instance" "main" {\n  # comment\n  publicly_accessible = false\n  port = 5432\n}\n';
    expect(tokenize(src).map((t) => t.text).join("")).toBe(src);
  });

  it("classifies keywords, strings, attributes, numbers and booleans", () => {
    const toks = tokenize('resource "x" "y" {\n  multi_az = true\n  size = 20\n}');
    const types = Object.fromEntries(toks.filter((t) => t.type !== "plain").map((t) => [t.text, t.type]));
    expect(types["resource"]).toBe("keyword");
    expect(types['"x"']).toBe("string");
    expect(types["multi_az"]).toBe("attr");
    expect(types["true"]).toBe("bool");
    expect(types["20"]).toBe("number");
  });

  it("treats HTML-looking content as plain text", () => {
    const toks = tokenize('description = "<script>alert(1)</script>"');
    expect(toks.find((t) => t.type === "string")?.text).toBe('"<script>alert(1)</script>"');
  });
});
