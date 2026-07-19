#!/usr/bin/env python3
"""Render PAPER.md -> paper.html (self-contained, academic preprint styling).
Clickable inline [n] citations that jump to the reference list."""
import re, html, pathlib

HERE = pathlib.Path(__file__).parent
md = (HERE / "PAPER.md").read_text(encoding="utf-8")

def esc(s):
    return html.escape(s, quote=False)

def inline(s):
    # escape first
    s = esc(s)
    # bold, italic, code
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'`(.+?)`', r'<code>\1</code>', s)
    s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', s)
    # inline math-ish $...$ -> italic span (keep readable, no MathJax dependency)
    s = re.sub(r'\$(.+?)\$', r'<span class="math">\1</span>', s)
    # clickable citations [1] or [1, 2] or [1, 2, 3] -> links (only pure-number groups)
    def citelink(m):
        inner = m.group(1)
        parts = [p.strip() for p in inner.split(',')]
        if not all(re.fullmatch(r'\d+', p) for p in parts):
            return m.group(0)
        links = ', '.join(f'<a href="#ref{p}" class="cite">{p}</a>' for p in parts)
        return f'[{links}]'
    s = re.sub(r'\[([\d,\s]+?)\]', citelink, s)
    return s

lines = md.split('\n')
out = []
i = 0
in_ref = False
while i < len(lines):
    line = lines[i]
    stripped = line.strip()
    if not stripped:
        i += 1
        continue
    if stripped == '---':
        out.append('<hr>')
        i += 1
        continue
    # headings
    m = re.match(r'^(#{1,4})\s+(.*)', stripped)
    if m:
        level = len(m.group(1))
        text = m.group(2)
        if re.match(r'^##\s*References', '## ' + text) or text.strip().lower() == 'references':
            in_ref = True
        anchor = ''
        out.append(f'<h{level}>{inline(text)}</h{level}>')
        i += 1
        continue
    # reference list items: [n] ...
    mref = re.match(r'^\[(\d+)\]\s+(.*)', stripped)
    if mref and in_ref:
        n = mref.group(1)
        body = mref.group(2)
        # gather continuation lines
        j = i + 1
        while j < len(lines) and lines[j].strip() and not re.match(r'^\[(\d+)\]', lines[j].strip()) and lines[j].strip() != '---':
            body += ' ' + lines[j].strip()
            j += 1
        out.append(f'<p class="ref" id="ref{n}"><span class="refnum">[{n}]</span> {inline(body)}</p>')
        i = j
        continue
    # bullet list
    if re.match(r'^[-*]\s+', stripped) or re.match(r'^\d+\.\s+', stripped):
        ordered = bool(re.match(r'^\d+\.\s+', stripped))
        tag = 'ol' if ordered else 'ul'
        out.append(f'<{tag}>')
        while i < len(lines) and (re.match(r'^[-*]\s+', lines[i].strip()) or re.match(r'^\d+\.\s+', lines[i].strip())):
            item = re.sub(r'^([-*]|\d+\.)\s+', '', lines[i].strip())
            j = i + 1
            while j < len(lines) and lines[j].strip() and not re.match(r'^[-*]\s+', lines[j].strip()) and not re.match(r'^\d+\.\s+', lines[j].strip()) and not lines[j].strip().startswith('#') and lines[j].strip() != '---':
                item += ' ' + lines[j].strip()
                j += 1
            out.append(f'<li>{inline(item)}</li>')
            i = j
        out.append(f'</{tag}>')
        continue
    # paragraph (gather continuation)
    body = stripped
    j = i + 1
    while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith('#') and lines[j].strip() != '---' and not re.match(r'^[-*]\s+', lines[j].strip()) and not re.match(r'^\d+\.\s+', lines[j].strip()) and not (in_ref and re.match(r'^\[\d+\]', lines[j].strip())):
        body += ' ' + lines[j].strip()
        j += 1
    out.append(f'<p>{inline(body)}</p>')
    i = j

body_html = '\n'.join(out)

page = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PetriLab — Steering an Open Genome Toward the Edge of Chaos</title>
<meta name="description" content="A scientific preprint: an open-ended-evolution engine with an autonomous experimenter and a falsification-first measurement contract.">
<meta property="og:title" content="PetriLab: Steering an Open Genome Toward the Edge of Chaos">
<meta property="og:description" content="Scientific preprint grounding the PetriLab open-ended-evolution engine in the edge-of-chaos and OEE literature.">
<meta property="og:type" content="article">
<meta property="og:url" content="https://petrilab.slambert.com/paper">
<meta property="og:image" content="https://petrilab.slambert.com/og-image.png">
<style>
:root{--ink:#1a1d24;--soft:#54606f;--bg:#faf9f6;--paper:#fff;--line:#e5e2da;--accent:#0b6b5f;--cite:#0b6b5f}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:Georgia,'Times New Roman',serif;line-height:1.62;font-size:18px}
.wrap{max-width:760px;margin:0 auto;padding:56px 24px 120px}
.back{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:13px;letter-spacing:.5px;text-transform:uppercase;color:var(--accent);text-decoration:none;display:inline-block;margin-bottom:40px}
.back:hover{text-decoration:underline}
h1{font-size:30px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:22px;margin:44px 0 12px;padding-top:8px;border-top:1px solid var(--line);letter-spacing:-.01em}
h3{font-size:18.5px;margin:28px 0 8px;color:var(--ink)}
h4{font-size:16px;margin:22px 0 6px;color:var(--soft);font-family:-apple-system,BlinkMacSystemFont,sans-serif}
/* the byline block (first few h3/paragraphs after h1) */
h1 + h3{font-size:16px;font-weight:normal;color:var(--soft);font-style:italic;border:0;margin-top:0}
p{margin:0 0 15px}
strong{font-weight:700}
em{font-style:italic}
code{font-family:'SF Mono',ui-monospace,Menlo,Consolas,monospace;font-size:.86em;background:#f0eee8;padding:1px 5px;border-radius:4px;color:#8a3b2e}
.math{font-style:italic;font-family:Georgia,serif}
a.cite{color:var(--cite);text-decoration:none;font-weight:600;font-size:.9em}
a.cite:hover{text-decoration:underline}
ul,ol{margin:0 0 16px;padding-left:26px}
li{margin:0 0 9px}
hr{border:0;border-top:1px solid var(--line);margin:34px 0}
.ref{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14.5px;line-height:1.5;color:var(--soft);padding:9px 12px;margin:0 0 2px;border-radius:8px;scroll-margin-top:20px;transition:background .3s}
.ref:target{background:#eafaf4;color:var(--ink)}
.refnum{color:var(--accent);font-weight:700;margin-right:6px}
h2 + p em:only-child, p:last-child em{color:var(--soft)}
@media (max-width:600px){body{font-size:16.5px}.wrap{padding:36px 18px 90px}h1{font-size:25px}h2{font-size:20px}}
</style>
</head>
<body>
<div class="wrap">
<a class="back" href="/">&larr; Live observatory</a>
''' + body_html + '''
</div>
</body>
</html>'''

(HERE / "paper.html").write_text(page, encoding="utf-8")
print("wrote paper.html", len(page), "bytes")
