"""Clarity check: find the sentences of a draft that are hard to read and say why (too long, asides in
parentheses, ideas chained with colons and semicolons, long lists), and ask a small local instruction
model (start-clarity.sh) for clearer wording of one sentence at a time.
"""
import json
import re
import urllib.request
from typing import List, Tuple

from humanizer import hz_text as T

LONG, VERY_LONG = 30, 40   # words
FLAG = 2                   # sentences scoring this much are flagged; 1 is shown as a mild hint

# ── finding the prose sentences ─────────────────────────────────────────────────────────────────
_ABBR = re.compile(r"(?:\b(?:e\.g|i\.e|et al|etc|vs|approx|ca|cf|fig|figs|eq|ref|refs|suppl|no|dr|prof|st)|\b[A-Z])\.$", re.I)
_BOUNDARY = re.compile(r"[.!?]+[\"')\]”’]*(?=\s+(?:[\"'(\[“‘]?[A-Z0-9]|--))")
_MARKER = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+")
_SKIP = re.compile(r"\s*(?:#|\||<|>|!\[|\[[^\]]*\]\([^)]*\)\s*$)")   # headings, tables, HTML, quotes, images, links


def paragraphs(text: str) -> List[Tuple[int, int]]:
    """(start, end) of prose paragraphs; headings, code blocks, tables, HTML and quotes are skipped."""
    spans, start, end, fence = [], None, 0, False
    for m in re.finditer(r"[^\n]*\n?", text):
        line = m.group()
        if not line:
            break
        if re.match(r"\s*(?:```|~~~)", line):
            fence, prose = not fence, False
        else:
            prose = bool(not fence and line.strip() and not _SKIP.match(line))
        if prose:
            if start is None:
                start = m.start()
            end = m.start() + len(line.rstrip("\n"))
        elif start is not None:
            spans.append((start, end))
            start = None
    if start is not None:
        spans.append((start, end))
    return spans


def sentences(text: str, s0: int, e0: int) -> List[Tuple[int, int]]:
    """Sentence spans inside text[s0:e0]; a line break always ends a sentence. List markers stay outside."""
    out = []
    for lm in re.finditer(r"[^\n]+", text[s0:e0]):
        ls, line = s0 + lm.start(), lm.group()
        cuts, start = [], 0
        for b in _BOUNDARY.finditer(line):
            if _ABBR.search(line[start:b.start() + 1]):
                continue
            cuts.append((start, b.end()))
            start = b.end()
        cuts.append((start, len(line)))
        for a, b in cuts:
            mk = _MARKER.match(line[a:b]) if a == 0 else None
            if mk:
                a += mk.end()
            while a < b and line[a].isspace():
                a += 1
            while b > a and line[b - 1].isspace():
                b -= 1
            if b > a:
                out.append((ls + a, ls + b))
    return out


# ── what makes a sentence hard to read ──────────────────────────────────────────────────────────
def _asides(s: str) -> List[str]:
    out, depth, start = [], 0, 0
    for i, c in enumerate(s):
        if c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")" and depth:
            depth -= 1
            if depth == 0:
                out.append(s[start + 1:i])
    return out


def reasons(s: str) -> Tuple[int, List[str]]:
    """→ (score, reasons in plain words) for one sentence."""
    score, why = 0, []
    n = T.count_words(s)
    if n > VERY_LONG:
        score += 2
        why.append(f"{n} words long; readers lose the thread past about 25–30")
    elif n > LONG:
        score += 1
        why.append(f"{n} words long; consider splitting it")
    asides = _asides(s)
    lists = [a for a in asides if a.count(",") >= 2]
    if lists:
        score += 1
        why.append("a list in parentheses interrupts the sentence; it could be its own sentence")
    if len(asides) >= 2:
        score += 1
        why.append(f"{len(asides)} asides in parentheses break the flow")
    chain = s.count(":") + s.count(";")
    if chain >= 2:
        score += 1
        why.append(f"{chain} colons or semicolons chain {chain + 1} ideas into one sentence")
    commas = re.sub(r"\([^)]*\)", "", s).count(",")
    if commas >= 6:
        score += 1
        why.append(f"{commas} commas outside parentheses: long lists are hard to follow")
    return score, why


def check(text: str) -> List[dict]:
    """→ [{start, end, score, flagged, reasons}] for every prose sentence of `text` that has a reason."""
    out = []
    for ps, pe in paragraphs(text):
        for a, b in sentences(text, ps, pe):
            score, why = reasons(text[a:b])
            if score:
                out.append({"start": a, "end": b, "score": score, "flagged": score >= FLAG, "reasons": why})
    return out


def paragraph_of(text: str, a: int, b: int) -> str:
    for ps, pe in paragraphs(text):
        if ps <= a and b <= pe:
            return text[ps:pe]
    return text[a:b]


# ── suggested wording ───────────────────────────────────────────────────────────────────────────
SYSTEM = """You edit scientific and technical writing for clarity. Rewrite the sentence you are given so it is easier to read.
- If it is long, split it into two or three shorter sentences. A long list in parentheses can become its own sentence.
- Keep the author's meaning, terms and register: precise and plain, not chatty, not promotional.
- Keep the author's spelling (British or American) and punctuation style; do not add dashes the original does not use.
- Keep every fact, number, unit, symbol (such as −, ′, ″, β, Å, °), name, abbreviation and command-line option exactly as written.
- Do not add information, examples, hedges or filler, and no stock phrases such as "in order to", "it is important to note", "a wide range of" or "plays a key role".
- Reply with the rewritten text only."""


def suggest(url: str, sentence: str, context: str, why: List[str], avoid: List[str] = ()) -> str:
    """Clearer wording for `sentence`; `avoid` holds earlier suggestions the new one should differ from."""
    user = (f"Paragraph, for context:\n{context}\n\nSentence to rewrite:\n{sentence}\n\n"
            f"Why it is hard to read: {'; '.join(why) or 'it is hard to follow'}")
    if avoid:
        user += "\n\nWrite a version that differs clearly from these earlier ones:\n" + "\n".join("- " + a for a in avoid)
    body = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0,
            "max_tokens": max(200, 3 * T.count_words(sentence) + 80)}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.load(r)["choices"][0]["message"]["content"]
    text = text.strip().strip("`").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"“”'":
        text = text[1:-1].strip()
    return _author_dashes(sentence, " ".join(text.split()))


def _author_dashes(orig: str, new: str) -> str:
    """The small model adds em dashes even when told not to; if the author used none, a pair around a phrase
    becomes parentheses and a single one a comma."""
    if "—" in orig:
        return new
    new = re.sub(r"\s*—\s*([^—]+?)\s*—\s*", r" (\1) ", new)
    new = re.sub(r"\s*—\s*", ", ", new)
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s+", "(", new)).strip()


_OPTION = re.compile(r"(?<![\w-])--[\w-]+(?:\s+(?!the\b|a\b)[\w.-]+)?")


def missing_options(orig: str, new: str) -> List[str]:
    """Command-line options from the sentence (--focus auto) that the suggestion dropped."""
    return [o for o in dict.fromkeys(m.group().split()[0] for m in _OPTION.finditer(orig)) if o not in new]
