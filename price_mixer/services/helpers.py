"""Text normalization and article extraction helpers."""

import re


def _normalize_compact(value):
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "").replace("-", "").replace("_", "").replace("/", "")


def _clean_article_token(token: str) -> str:
    t = token.strip().lower()
    t = re.sub(r"[()\[\]{}]", "", t)
    if t.endswith("mhz") or t.endswith("gb") or t.endswith("tb") or t.endswith("mb"):
        return ""
    if re.fullmatch(r"\d{1,2}", t):
        return ""
    if len(t) < 3:
        return ""
    return t


def extract_article(name: str) -> str:
    if not name:
        return ""
    # Try to extract article in parentheses or brackets
    m = re.search(r"[\[(]([A-Z0-9\-/_]{3,})[\])]", str(name))
    if m:
        return m.group(1)
    # Fallback: first all-caps token with numbers
    tokens = re.findall(r"[A-Z]+[A-Z0-9\-/_]*[0-9]+[A-Z0-9\-/_]*", str(name))
    if tokens:
        return tokens[0]
    return ""


def extract_article_candidates(name: str) -> list[str]:
    if not name:
        return []
    text = str(name)
    candidates = []
    # Parentheses/brackets content
    for m in re.finditer(r"[\[(]([^\[\]()]{3,})[\])]", text):
        cand = _clean_article_token(m.group(1))
        if cand:
            candidates.append(cand)
    # CamelCase / uppercase tokens with digits
    for token in re.findall(r"[A-Z]+[A-Z0-9\-/_]*[0-9]+[A-Z0-9\-/_]*", text):
        cand = _clean_article_token(token)
        if cand and cand not in candidates:
            candidates.append(cand)
    # Mixed tokens (e.g. Ryzen-5-5600X)
    for token in re.findall(r"[A-Za-z]+[\-][A-Za-z0-9\-]+", text):
        cand = _clean_article_token(token)
        if cand and cand not in candidates:
            candidates.append(cand)
    return candidates
