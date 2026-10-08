"""Parse FRONTEND_ORIGIN into what CORSMiddleware needs.

Browsers send the Origin header as just scheme://host[:port] with no trailing slash or path, and
the check is an exact match. A value like "https://my-app.vercel.app/" or "my-app.vercel.app" never
matches, so the preflight (OPTIONS) gets a 400. This normalizes such values and also accepts
wildcards, e.g. "https://*.vercel.app" or "https://voicecircle-*.vercel.app" for preview deployments.
"""
import re
from urllib.parse import urlsplit


def normalize_origin(value: str) -> str:
    v = value.strip().strip("\"'").strip()
    if not v:
        return ""
    if "://" not in v:
        v = ("http://" if v.startswith(("localhost", "127.0.0.1")) else "https://") + v
    parts = urlsplit(v)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def parse_origins(raw: str) -> tuple[list[str], str | None]:
    exact: list[str] = []
    patterns: list[str] = []
    for item in re.split(r"[,\s]+", raw or ""):
        o = normalize_origin(item)
        if not o:
            continue
        if o == "https://*" or item.strip() == "*":
            return ["*"], None
        if "*" in o:
            patterns.append(re.escape(o).replace(r"\*", r"[a-z0-9-]+"))
        elif o not in exact:
            exact.append(o)
    return exact, ("|".join(f"(?:{p})" for p in patterns) or None)
