"""Optional AI writing of the narrative sections (Abstract, Introduction, Results text, Discussion, Conclusion) with
Claude, through the user's own Anthropic API key.

What the model receives is only what the app already holds: the study details, the structured findings and the exact
Results sentences built from the data, the Methods, and the user's numbered references with their abstracts. It is
asked to cite only those references (as [R#]) and to use only the numbers it was given. After it answers, the app
checks both: a citation id that does not exist becomes a highlighted [ref], and any number that does not occur in the
data is wrapped as a highlighted [check: …] for the authors. The paper then carries an AI-use declaration.

The Methods are not sent for rewriting: they stay exactly as built from the data and the study form."""
from __future__ import annotations

import json
import os
import re

DEFAULT_MODEL = "claude-opus-5-5"
MODELS = {"claude-opus-5-5": "Claude Opus 5.5 (best writing)", "claude-sonnet-5-5": "Claude Sonnet 5.5 (faster, cheaper)"}

SYSTEM = """You are an experienced pharmacology and toxicology scientist writing an original research article for an \
indexed, peer-reviewed journal (Elsevier, Springer, Wiley, Taylor & Francis). You write the narrative sections from \
the study data you are given. Write the way a careful senior author writes, not the way a text generator writes.

Hard rules (a paper that breaks them is rejected):
1. Use only numbers that appear in the data. Never invent or round differently a mean, SD, median, fold change, \
percentage, p value, dose, sample size or time. Copy p values exactly as given (for example "p < 0.001", "p = 0.037"). \
Use the p symbol given in p_symbol.
2. Cite only the numbered references supplied, as [R1] or [R2, R5], placed before the full stop. Cite a reference only \
for what its title or abstract actually supports. Where a statement needs support and no supplied reference fits, write \
[ref] instead of a citation. Never invent authors, years or studies, and do not mention a study's findings unless they \
are in its abstract.
3. Mechanisms that were not measured are hypotheses: write "may", "could", "is likely to"; never claim that the \
compound acted through a pathway the study did not test. Do not name enzymes, cytokines or genes as findings unless they \
are in the markers list.
4. Do not describe procedures, doses, durations, kits or animal details that are not in the data. If the Introduction or \
Discussion needs a fact only the authors know, write it as a short bracketed prompt, e.g. [state the reperfusion time], \
and keep such prompts to a minimum.
5. Group names: use them exactly as given, or define a short abbreviation once and then use it consistently.

Style:
- Past tense for what was done and found; present tense for established knowledge.
- Vary sentence length and structure. Prefer concrete verbs and specific nouns. One idea per paragraph.
- Avoid the stock phrases of machine-written text: delve, crucial, pivotal, notably, furthermore/moreover at the start of \
consecutive sentences, plays a crucial role, sheds light, underscores, highlights the importance, a testament, landscape, \
realm, multifaceted, intricate, holistic, robust (except for statistics), novel insights, paving the way, in summary, \
it is worth noting, it is important to note. No em dashes. No lists inside prose. No rhetorical questions.
- Do not repeat the same opening ("LIR increased...") across consecutive sentences; vary the subject.
- Be economical: every sentence must carry information.

Sections to write:
- title: a declarative, specific title (max 20 words) only if the study title is empty; otherwise return the study title \
unchanged.
- highlights: 3 to 5 bullet sentences of at most 85 characters each, findings only.
- abstract: background, methods, results, conclusion; at most 250 words in total; results with the key numbers and p \
values from the data.
- keywords: 5 or 6.
- introduction: 4 or 5 paragraphs that narrow from the clinical and experimental importance of the disease model, to the \
mechanisms that the measured markers report on, to the limits of current protection, to what is known about the test \
compound (from the references), ending with the gap and the aim of this study. Cite generously but only as allowed.
- results: rewrite results_text as clear prose grouped by mechanism (for example "Oxidative and nitrosative stress", \
"Neutrophil infiltration"), keeping every number and p value exactly. Refer to Table 1 and Figure 1. Add a \
histopathology subsection only if histopathology_results is not empty, using only that text.
- discussion: 5 to 7 paragraphs: the principal findings in plain words; one paragraph per mechanism that interprets what \
the measured markers mean biologically and compares the direction and size of the changes with the cited literature; \
how the compound may have produced the effect (hypotheses grounded in the cited references); the dose comparison; \
specific limitations of this design (only those that follow from the data: single time point, markers measured, sample \
size, no mechanistic inhibitors, etc.); what should be done next.
- conclusion: 2 or 3 sentences, no new data, no overstatement.

Return only the JSON object required by the schema."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "highlights", "abstract", "keywords", "introduction", "results", "discussion", "conclusion"],
    "properties": {
        "title": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "abstract": {"type": "object", "additionalProperties": False,
                     "required": ["background", "methods", "results", "conclusion"],
                     "properties": {k: {"type": "string"} for k in ("background", "methods", "results", "conclusion")}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "introduction": {"type": "array", "items": {"type": "string"}},
        "results": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": ["heading", "paragraphs"],
                                                "properties": {"heading": {"type": "string"},
                                                               "paragraphs": {"type": "array", "items": {"type": "string"}}}}},
        "discussion": {"type": "array", "items": {"type": "string"}},
        "conclusion": {"type": "string"},
    },
}


class AIWriterError(Exception):
    pass


def api_key(saved: str = "") -> str:
    return (saved or os.environ.get("ANTHROPIC_API_KEY", "")).strip()


def _user_message(ctx: dict) -> str:
    return ("Write the narrative sections of this paper from the data below. The data are complete; do not add "
            "anything that is not supported by them.\n\n<study_data>\n" + json.dumps(ctx, ensure_ascii=False, indent=1,
                                                                                    default=str) + "\n</study_data>")


def call_claude(ctx: dict, key: str, model: str = DEFAULT_MODEL, effort: str = "high", client=None) -> dict:
    """One streamed request; returns the parsed sections. `client` is injectable for tests."""
    if client is None:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise AIWriterError("The 'anthropic' package is not installed.") from e
        if not key:
            raise AIWriterError("No Anthropic API key. Enter it in the Output tab or set ANTHROPIC_API_KEY.")
        client = anthropic.Anthropic(api_key=key, timeout=900, max_retries=2)
    kw = dict(model=model, max_tokens=32000, system=SYSTEM, thinking={"type": "adaptive"},
              output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
              messages=[{"role": "user", "content": _user_message(ctx)}])
    try:     # server-side fallback: if the model declines, the API reruns the request on a suitable model
        with client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw) as s:
            msg = s.get_final_message()
    except Exception as e:
        if not _is_param_error(e):
            raise _friendly(e) from e
        try:
            with client.messages.stream(**kw) as s:
                msg = s.get_final_message()
        except Exception as e2:
            raise _friendly(e2) from e2
    if msg.stop_reason == "refusal":
        raise AIWriterError("The model declined to write this text.")
    if msg.stop_reason == "max_tokens":
        raise AIWriterError("The answer was cut off (too long). Try again, or use fewer references.")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        return json.loads(text)
    except ValueError as e:
        raise AIWriterError("The answer could not be read. Please try again.") from e


def _is_param_error(e) -> bool:
    s = str(e).lower()
    return getattr(e, "status_code", None) == 400 and ("fallback" in s or "beta" in s)


def _friendly(e) -> Exception:
    name = type(e).__name__
    code = getattr(e, "status_code", None)
    if name == "AuthenticationError" or code == 401:
        return AIWriterError("The API key was rejected. Check it in console.anthropic.com → API keys.")
    if name == "PermissionDeniedError" or code == 403:
        return AIWriterError("This API key has no access to the chosen model.")
    if name == "RateLimitError" or code == 429:
        return AIWriterError("Rate limit reached. Wait a minute and try again.")
    if name == "APIConnectionError":
        return AIWriterError("No connection to api.anthropic.com. Check the internet connection or proxy.")
    if code and code >= 500:
        return AIWriterError("The Anthropic service had a temporary error. Try again in a few minutes.")
    return AIWriterError(f"{name}: {e}")


# ----------------------------------------------------------------------------- checks


_NUM = re.compile(r"(?<![\w.])[-−]?\d+(?:\.\d+)?(?![\w])")


def _norm(x: str) -> str:
    x = x.replace("−", "-").lstrip("-")
    if "." in x:
        x = x.rstrip("0").rstrip(".")
    return x


def allowed_numbers(ctx: dict) -> set:
    blob = json.dumps(ctx, ensure_ascii=False, default=str)
    nums = {_norm(n) for n in _NUM.findall(blob)}
    for n in list(nums):            # 0.037 may be written as 3.7% only if the data said so; keep rounding variants of %
        try:
            f = float(n)
        except ValueError:
            continue
        nums.add(_norm(f"{f:.0f}")); nums.add(_norm(f"{f:.1f}"))
    nums |= {str(i) for i in range(0, 21)}          # counts, section and table numbers
    return nums


def check_numbers(text: str, allowed: set) -> tuple[str, list]:
    """Wrap numbers that are not in the data as [check: …]; years inside citations are left alone."""
    bad = []

    def sub(m):
        tok = m.group(0)
        if _norm(tok) in allowed or re.fullmatch(r"(19|20)\d\d", tok):
            return tok
        bad.append(tok)
        return f"[check: {tok}]"
    out = []
    for part in re.split(r"(\[R\d+(?:\s*[,;–-]\s*R?\d+)*\])", text):     # leave the citation markers alone
        out.append(part if part.startswith("[R") else _NUM.sub(sub, part))
    return "".join(out), bad


def verify(sections: dict, ctx: dict) -> tuple[dict, dict]:
    """Return the sections with unsupported numbers flagged, and a report of what was flagged."""
    allowed = allowed_numbers(ctx)
    n_refs = len(ctx.get("references", []))
    report = {"numbers": [], "bad_citations": []}

    def fix(t):
        t, bad = check_numbers(t, allowed)
        report["numbers"] += bad
        for ids in re.findall(r"\[(R\d+(?:\s*[,;–-]\s*R?\d+)*)\]", t):
            for i in re.findall(r"R(\d+)", ids):
                if not 1 <= int(i) <= n_refs:
                    report["bad_citations"].append("R" + i)
        return t

    out = dict(sections)
    for k in ("introduction", "discussion", "highlights"):
        out[k] = [fix(p) for p in sections.get(k, [])]
    out["results"] = [{"heading": b.get("heading", ""), "paragraphs": [fix(p) for p in b.get("paragraphs", [])]}
                      for b in sections.get("results", [])]
    out["abstract"] = {k: fix(v) for k, v in (sections.get("abstract") or {}).items()}
    out["conclusion"] = fix(sections.get("conclusion", ""))
    return out, report


def write_sections(ctx: dict, key: str, model: str = DEFAULT_MODEL, effort: str = "high", client=None):
    raw = call_claude(ctx, key, model, effort, client)
    return verify(raw, ctx)
