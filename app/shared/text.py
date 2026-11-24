"""Tiny text helpers shared by news, job discovery and personalization: cleaning and keywords."""

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Keeps tech terms like c++, c#, .net, node.js, next.js, k8s, gpt-5 together.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")


def words(text: str) -> frozenset[str]:
    """A word set from a whitespace-separated literal (keeps long keyword lists readable)."""
    return frozenset(text.split())


STOPWORDS = words(
    """
    a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers him his how i if in into is it its itself just
    me more most my no nor not now of off on once only or other our ours out over own same she
    should so some such than that the their them then there these they this those through to
    too under until up very was we were what when where which while who whom why will with you
    your yours new how why what show ask tell use using used via vs get got make made way ways
    one two first last year years day days week weeks today now time best better good great top
    more most less many much really still even every like just need needs want wants work works
    working build building built help helps based based guide introducing announcing released
    release launch launches launched update updates version news thing things people company
    companies team teams job jobs role roles remote senior junior lead staff full part contract
    hire hiring looking join apply experience required requirements responsibilities strong
    ability skills skill knowledge preferred plus years etc including within across about
    """
)


def clean_text(raw: str | None, limit: int = 400) -> str:
    """Strip HTML, unescape entities, collapse whitespace and cut at a word boundary."""
    if not raw:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def tokens(text: str | None) -> list[str]:
    """Lower-cased keyword tokens without stopwords or bare numbers."""
    if not text:
        return []
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        tok = tok.strip(".-")
        if len(tok) < 2 or tok in STOPWORDS or tok.isdigit():
            continue
        out.append(tok)
    return out


def token_set(*texts: str | None) -> set[str]:
    found: set[str] = set()
    for text in texts:
        found.update(tokens(text))
    return found


def normalise_tag(tag: str) -> str:
    return _WS_RE.sub(" ", tag.strip().lower())[:50]
