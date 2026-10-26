#!/usr/bin/env python3
"""Two-panel web UI for the humanizer: draft on the left, rewrite on the right.

Uses hz's own pipeline (piece planning, retries, number/link/copy checks) against the local
llama-server, and streams the rewrite back one piece at a time as NDJSON. The finished rewrite is
checked by a local LanguageTool server for grammar, punctuation and spelling.

    python app.py [--port 8086] [--server http://127.0.0.1:8085] [--lt http://127.0.0.1:8081]
"""
import argparse
import io
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from humanizer import hz
from humanizer import hz_text as T

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()   # llama-server runs one slot; one rewrite at a time
ARGS = None


class QuietOut(hz.Out):
    def __init__(self):
        super().__init__(quiet=True)


def server_up(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


# LanguageTool categories that are safe to apply without asking. Spelling (TYPOS) and style are only
# shown: LanguageTool does not know lab jargon, and style is a matter of taste.
AUTO_FIX = {"GRAMMAR", "PUNCTUATION", "CASING", "CONFUSED_WORDS", "DRAFT_CASING"}
AUTO_RULES = {"ENGLISH_WORD_REPEAT_RULE", "EN_A_VS_AN"}   # "the the", "an custom" (filed under MISC)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]|[A-Za-z]")
_END = re.compile(r"[.!?:;…。！？：；][)\]\"'”’*`]*$")
_NOT_PROSE = re.compile(r"\s*(?:#|[-*+>|]\s|\d+[.)]\s|```|<)")   # headings, lists, quotes, tables, code, HTML


def draft_terms(draft):
    """Names whose capitalization must survive: GenBank, SnapGene, FASTA, ORF, HEK293T, pET-28a."""
    terms = {}
    for w in _WORD.findall(draft):
        if re.search(r"[A-Za-z]", w) and (any(c.isupper() for c in w[1:]) or (re.search(r"\d", w) and re.search(r"[A-Za-z]", w))):
            terms.setdefault(w.lower(), w)
            # singular and plural: ORFs in the draft also fixes "orf", ORF also fixes "orfs"
            if w.endswith("s") and len(w) > 3 and w[-2].isupper():
                terms.setdefault(w[:-1].lower(), w[:-1])
            elif w[-1].isupper():
                terms.setdefault(w.lower() + "s", w + "s")
    return terms


# multi-word names such as "Plasmid Viewer & Map" or "Protein Data Bank"; hz checks numbers and links, not names
_NAME = re.compile(r"[A-Z][\w-]*(?:\s+(?:(?:&|of|for)\s+)?[A-Z][\w-]*)+")
_JOIN = ("&", "of", "for")


def draft_names(draft):
    names = []
    for m in _NAME.finditer(draft):
        words = m.group().split()
        before = draft[:m.start()].rstrip()
        if not before or before[-1] in ".!?:#":   # first word of a sentence is capitalized anyway
            words = words[1:]
        while words and words[0] in _JOIN:
            words = words[1:]
        if sum(w[0].isupper() for w in words) >= 2:
            names.append(" ".join(words))
    return list(dict.fromkeys(names))


def missing_names(draft, out):
    o = " ".join(out.split()).lower()
    return [n for n in draft_names(draft) if n.lower() not in o]


# symbols the model tends to flatten to ASCII: −115.0° → -115.0°, A′ → A', β-augmentation → beta-augmentation
_FOLD = {"′": "'", "″": "''", "‴": "'''", "−": "-", "–": "-", "α": "alpha", "β": "beta", "γ": "gamma",
         "δ": "delta", "ε": "epsilon", "κ": "kappa", "λ": "lambda", "μ": "mu", "µ": "u", "σ": "sigma", "ω": "omega",
         "Δ": "Delta", "Å": "A", "×": "x", "±": "+/-", "≤": "<=", "≥": ">="}
_SYMBOL_TOKEN = re.compile(r"[^\s,;:()\[\]]*[" + "".join(_FOLD) + r"][^\s,;:()\[\]]*")


def symbol_issues(text, draft):
    """Places where the rewrite has the ASCII form of a symbol-bearing token from the draft."""
    issues, seen = [], set()
    for tok in _SYMBOL_TOKEN.findall(draft):
        tok = tok.rstrip(".")
        flat = "".join(_FOLD.get(c, c) for c in tok)
        if flat == tok or flat in seen or (flat.isalpha() and len(flat) <= 2):
            continue
        seen.add(flat)
        for m in re.finditer(r"(?<![\w'-])" + re.escape(flat) + r"(?![\w'])", text):
            issues.append({"offset": m.start(), "length": len(flat), "rule": "DRAFT_SYMBOL", "category": "DRAFT_CASING",
                           "message": f"Written “{tok}” in the draft.", "replacements": [tok], "auto": True})
    return issues


def science_words():
    """ui/science-words.txt, re-read on each check so edits apply without a restart."""
    try:
        with open(os.path.join(HERE, "science-words.txt"), encoding="utf-8") as f:
            words = {l.strip() for l in f if l.strip() and not l.startswith("#")}
    except OSError:
        return set()
    return words | {w.capitalize() for w in words if w.islower()}


def grammar_check(text, draft):
    """→ (available, issues). Each issue: offset, length, message, replacements, rule, category, auto."""
    issues = []
    terms = draft_terms(draft)
    for m in _WORD.finditer(text):
        want = terms.get(m.group().lower())
        if want and want != m.group():
            issues.append({"offset": m.start(), "length": len(m.group()), "rule": "DRAFT_CASING",
                           "category": "DRAFT_CASING", "message": f"Written “{want}” in the draft.",
                           "replacements": [want], "auto": True})
    taken = [(i["offset"], i["offset"] + i["length"]) for i in issues]
    issues += [i for i in symbol_issues(text, draft)
               if not any(i["offset"] < e and s < i["offset"] + i["length"] for s, e in taken)]
    # LanguageTool does not flag a prose line that just stops; the model writes those often
    draft_lines = {l.strip() for l in draft.splitlines()}
    for m in re.finditer(r"[^\n]+", text):
        line = m.group().rstrip()
        if (len(line.split()) >= 6 and not _END.search(line) and not _NOT_PROSE.match(line)
                and line.strip() not in draft_lines):
            end = m.start() + len(line)
            issues.append({"offset": end - 1, "length": 1, "rule": "LINE_END_PERIOD", "category": "PUNCTUATION",
                           "message": "This sentence has no closing punctuation.",
                           "replacements": [line[-1] + "."], "auto": True})
    try:
        body = urllib.parse.urlencode({"text": text, "language": ARGS.lt_lang,
                                       "preferredVariants": ARGS.lt_variant}).encode()
        with urllib.request.urlopen(ARGS.lt.rstrip("/") + "/v2/check", body, timeout=60) as r:
            matches = json.load(r).get("matches", [])
    except Exception:
        return False, issues
    draft_words = set(_WORD.findall(draft)) | science_words()
    taken = [(i["offset"], i["offset"] + i["length"]) for i in issues]
    for m in matches:
        o, n = m["offset"], m["length"]
        cat = m.get("rule", {}).get("category", {}).get("id", "")
        if cat == "TYPOS" and text[o:o + n] in draft_words:
            continue   # the draft spells it this way: a term, not a typo
        if any(o < e and s < o + n for s, e in taken):
            continue
        reps = [r["value"] for r in m.get("replacements", [])[:5]]
        rule = m.get("rule", {}).get("id", "")
        # hyphenation depends on meaning ("editable imported layer" is two adjectives): suggest, never apply
        hyphen_only = bool(reps) and re.sub(r"[\s-]", "", reps[0]) == re.sub(r"[\s-]", "", text[o:o + n])
        issues.append({"offset": o, "length": n, "message": m.get("message", ""), "replacements": reps,
                       "rule": rule, "category": cat,
                       "auto": (cat in AUTO_FIX or rule in AUTO_RULES) and bool(reps) and not hyphen_only})
        taken.append((o, o + n))
    return True, sorted(issues, key=lambda i: i["offset"])


def lt_up():
    try:
        with urllib.request.urlopen(ARGS.lt.rstrip("/") + "/v2/languages", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def docx_text(data):
    import docx
    doc = docx.Document(io.BytesIO(data))
    return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._send(200, {"server": ARGS.server, "up": server_up(ARGS.server), "busy": LOCK.locked(),
                             "lt": ARGS.lt, "lt_up": lt_up()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/import":
            try:
                self._send(200, {"text": docx_text(self._body())})
            except Exception as e:
                self._send(400, {"error": f"could not read the .docx: {e}"})
        elif self.path == "/api/rewrite":
            self._rewrite()
        elif self.path == "/api/redo":
            self._redo()
        elif self.path == "/api/synonyms":
            try:
                d = json.loads(self._body() or b"{}")
                import thesaurus   # needs nltk and lemminflect (requirements.txt)
                self._send(200, {"senses": thesaurus.synonyms(d.get("word", ""), d.get("sentence", ""))})
            except ImportError:
                self._send(501, {"error": "the thesaurus needs nltk and lemminflect: .venv/bin/pip install -r requirements.txt"})
            except Exception as e:
                self._send(500, {"error": f"thesaurus: {e}"})
        elif self.path == "/api/check":
            try:
                d = json.loads(self._body() or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad request"})
            ok, issues = grammar_check(d.get("text", ""), d.get("draft", ""))
            self._send(200, {"available": ok, "issues": issues})
        else:
            self._send(404, {"error": "not found"})

    def _emit(self, obj):
        self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        self.wfile.flush()

    def _rewrite(self):
        try:
            text = json.loads(self._body() or b"{}").get("text", "")
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if not text.strip():
            return self._send(400, {"error": "the draft is empty"})
        if not LOCK.acquire(blocking=False):
            return self._send(409, {"error": "another rewrite is running"})
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self._run(text)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the page pressed Stop or was closed; stop between pieces
        finally:
            LOCK.release()

    def _redo(self):
        """Rewrite a few sentences again: one JSON answer, no streaming."""
        try:
            text = json.loads(self._body() or b"{}").get("text", "")
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if not server_up(ARGS.server):
            return self._send(503, {"error": f"llama-server is not running at {ARGS.server}"})
        if not LOCK.acquire(blocking=False):
            return self._send(409, {"error": "another rewrite is running"})
        try:
            new, flags, pieces, _ = rewrite_pieces(text)
            self._send(200, {"text": new, "flags": flags, "pieces": pieces})
        except hz.HzError as e:
            self._send(502, {"error": str(e)})
        finally:
            LOCK.release()

    def _run(self, text):
        if not server_up(ARGS.server):
            return self._emit({"type": "error", "error": f"llama-server is not running at {ARGS.server}"})
        t0 = time.time()
        try:
            final, flags, pieces, copy = rewrite_pieces(text, self._emit)
        except hz.HzError as e:
            return self._emit({"type": "error", "error": str(e)})
        self._emit({"type": "checking"})
        lt_ok, issues = grammar_check(final, text)
        self._emit({"type": "done", "text": final, "seconds": round(time.time() - t0, 1),
                    "pieces": pieces, "flags": flags, "lt": lt_ok, "issues": issues, "copy_rate": copy,
                    "names": missing_names(text, final)})


def rewrite_pieces(text, emit=lambda ev: None):
    """hz pipeline over text → (rewrite, flagged pieces, piece count, copy rate). Emits plan/progress/piece events."""
    planner = T.Planner()
    plan = planner.plan_text(text)
    units = plan.units
    emit({"type": "plan", "pieces": len(units), "kept": dict(plan.kept)})
    backend = hz.Backend("server", ARGS.server)
    out = QuietOut()
    results, flags = {}, []

    def render():
        # pieces not rewritten yet show the draft, so the right panel fills in place
        return plan.render({u.id: results.get(u.id, u.text) for u in units})

    for k, u in enumerate(units, 1):
        emit({"type": "progress", "k": k, "total": len(units)})
        res, stats = hz.rewrite_units([u], backend, planner.sizer, out, lambda u: f"line {u.line}",
                                      retries=ARGS.retries)
        results.update(res)
        s = stats[0]
        if s["flagged"]:
            flags.append({"line": u.line, "start": s["draft_start"],
                          "note": hz._describe(s["issues"], s["copy_rate"], s["missing_numbers"],
                                               s["missing_urls"], s["added_numbers"])})
        emit({"type": "piece", "k": k, "total": len(units), "seconds": s["seconds"], "text": render()})

    drafts = "\n\n".join(u.text for u in units)
    rewrites = "\n\n".join(results[u.id] for u in units)
    return render(), flags, len(units), round(T.copy_rate(drafts, rewrites), 3) if units else 0.0


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("HUMANIZER_UI_PORT", 8086)))
    ap.add_argument("--server", default=f"http://127.0.0.1:{os.environ.get('HUMANIZER_PORT', 8085)}")
    ap.add_argument("--lt", default=f"http://127.0.0.1:{os.environ.get('LANGUAGETOOL_PORT', 8081)}",
                    help="LanguageTool server for the grammar check")
    ap.add_argument("--lt-lang", default=os.environ.get("LANGUAGETOOL_LANG", "auto"),
                    help="LanguageTool language, e.g. en-US, en-GB or auto")
    ap.add_argument("--lt-variant", default=os.environ.get("LANGUAGETOOL_VARIANT", "en-US"),
                    help="spelling variant when the language is auto: en-US or en-GB")
    ap.add_argument("--retries", type=int, default=1, help="extra tries for a piece with a problem (as hz)")
    ARGS = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    print(f"Humanizer UI on http://127.0.0.1:{ARGS.port}  (model server {ARGS.server}, LanguageTool {ARGS.lt})",
          flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
