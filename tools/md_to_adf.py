#!/usr/bin/env python3
"""Convert a constrained Markdown subset to Atlassian Document Format (ADF) JSON.

Usage:
    python md_to_adf.py <input.md> <output.adf.json>

Supports: headings (#..######), paragraphs, bold/italic/inline-code/links,
fenced code blocks, bullet/numbered lists (single level), GFM pipe tables,
horizontal rules, and blockquotes. Built for posting SDD workflow comments
(step1/step2/decomp/review) to Jira via `acli jira workitem comment create`.

This is a purpose-built subset converter, not a full CommonMark implementation
— it covers what the spec-driven-designer / implementation-plan skills
actually emit. Unsupported constructs fall back to plain paragraphs.
"""
import json
import re
import sys


def parse_inline(text):
    """Turn inline markdown (bold, italic, code, links) into ADF text nodes."""
    nodes = []
    # Token pattern: `code`, **bold**, *italic*, [text](url)
    pattern = re.compile(
        r"`([^`]+)`"
        r"|\*\*([^*]+)\*\*"
        r"|\*([^*]+)\*"
        r"|\[([^\]]+)\]\(([^)]+)\)"
    )
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            plain = text[pos:m.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})
        if m.group(1) is not None:
            nodes.append({"type": "text", "text": m.group(1), "marks": [{"type": "code"}]})
        elif m.group(2) is not None:
            nodes.append({"type": "text", "text": m.group(2), "marks": [{"type": "strong"}]})
        elif m.group(3) is not None:
            nodes.append({"type": "text", "text": m.group(3), "marks": [{"type": "em"}]})
        elif m.group(4) is not None:
            nodes.append({
                "type": "text",
                "text": m.group(4),
                "marks": [{"type": "link", "attrs": {"href": m.group(5)}}],
            })
        pos = m.end()
    if pos < len(text):
        remainder = text[pos:]
        if remainder:
            nodes.append({"type": "text", "text": remainder})
    if not nodes:
        nodes.append({"type": "text", "text": text})
    return nodes


def make_paragraph(text):
    stripped = text.strip()
    if not stripped:
        return None
    return {"type": "paragraph", "content": parse_inline(stripped)}


def parse_table(lines):
    rows = [ln for ln in lines if ln.strip().startswith("|")]
    if len(rows) < 2:
        return None, lines

    def split_row(row):
        cells = row.strip()
        if cells.startswith("|"):
            cells = cells[1:]
        if cells.endswith("|"):
            cells = cells[:-1]
        return [c.strip() for c in cells.split("|")]

    header_cells = split_row(rows[0])
    # rows[1] is the separator (---|---); data starts at rows[2:]
    data_rows = [split_row(r) for r in rows[2:]]

    def cell_node(text, header=False):
        node_type = "tableHeader" if header else "tableCell"
        para = make_paragraph(text) or {"type": "paragraph", "content": []}
        return {"type": node_type, "attrs": {}, "content": [para]}

    table_rows = [{
        "type": "tableRow",
        "content": [cell_node(c, header=True) for c in header_cells],
    }]
    for row in data_rows:
        # pad/truncate to header width
        row = (row + [""] * len(header_cells))[:len(header_cells)]
        table_rows.append({
            "type": "tableRow",
            "content": [cell_node(c) for c in row],
        })

    table_node = {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": table_rows,
    }
    return table_node, lines[len(rows):]


def convert(markdown_text):
    lines = markdown_text.splitlines()
    content = []
    i = 0
    n = len(lines)
    list_buffer = []
    list_type = None

    def flush_list():
        nonlocal list_buffer, list_type
        if list_buffer:
            items = [{"type": "listItem", "content": [make_paragraph(item) or {"type": "paragraph", "content": []}]}
                      for item in list_buffer]
            content.append({"type": list_type, "content": items})
        list_buffer = []
        list_type = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_list()
            i += 1
            continue

        # Fenced code block
        if stripped.startswith("```"):
            flush_list()
            lang = stripped[3:].strip() or None
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code_node = {
                "type": "codeBlock",
                "attrs": {"language": lang} if lang else {},
                "content": [{"type": "text", "text": "\n".join(code_lines)}] if code_lines else [],
            }
            content.append(code_node)
            continue

        # Horizontal rule
        if re.fullmatch(r"-{3,}|_{3,}|\*{3,}", stripped):
            flush_list()
            content.append({"type": "rule"})
            i += 1
            continue

        # Heading
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_list()
            level = len(heading_match.group(1))
            text = heading_match.group(2).strip()
            content.append({"type": "heading", "attrs": {"level": level}, "content": parse_inline(text)})
            i += 1
            continue

        # Table
        if stripped.startswith("|"):
            flush_list()
            table_lines = []
            j = i
            while j < n and lines[j].strip().startswith("|"):
                table_lines.append(lines[j])
                j += 1
            table_node, _ = parse_table(table_lines)
            if table_node:
                content.append(table_node)
            i = j
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_list()
            quote_lines = []
            j = i
            while j < n and lines[j].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[j].strip()))
                j += 1
            para = make_paragraph(" ".join(quote_lines))
            content.append({"type": "blockquote", "content": [para] if para else []})
            i = j
            continue

        # Bullet list item
        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            if list_type and list_type != "bulletList":
                flush_list()
            list_type = "bulletList"
            list_buffer.append(bullet_match.group(1))
            i += 1
            continue

        # Ordered list item
        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            if list_type and list_type != "orderedList":
                flush_list()
            list_type = "orderedList"
            list_buffer.append(ordered_match.group(1))
            i += 1
            continue

        # Default: paragraph (collect contiguous non-blank plain lines)
        flush_list()
        para_lines = [stripped]
        i += 1
        while i < n and lines[i].strip() and not re.match(
            r"^(#{1,6})\s|^[-*]\s|^\d+\.\s|^```|^\||^>|^-{3,}$", lines[i].strip()
        ):
            para_lines.append(lines[i].strip())
            i += 1
        para = make_paragraph(" ".join(para_lines))
        if para:
            content.append(para)

    flush_list()
    return {"type": "doc", "version": 1, "content": content}


def main():
    if len(sys.argv) != 3:
        print("Usage: python md_to_adf.py <input.md> <output.adf.json>", file=sys.stderr)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "r", encoding="utf-8") as f:
        md = f.read()
    adf = convert(md)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(adf, f, ensure_ascii=False, indent=2)
    print(f"Wrote {dst}")


if __name__ == "__main__":
    main()
