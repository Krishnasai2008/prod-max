import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

from pm.db import DEFAULTS, get_setting
from pm.excerpt import _LINES, _PAGE, outline

_MARKUP = "$`[<\\"


def slug(text: str) -> str:
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def anchors(titles: list[str]) -> list[str]:
    used: set[str] = set()
    out = []
    for title in titles:
        ident = slug(title)
        while ident in used or not ident:
            match = re.match(r"^(.*)_(\d+)$", ident)
            ident = f"{match[1]}_{int(match[2]) + 1}" if match else f"{ident}_1"
        used.add(ident)
        out.append(ident)
    return out


def notes_dir(conn) -> Path | None:
    value = get_setting(conn, "notes_dir", DEFAULTS["notes_dir"])
    if not value:
        return None
    try:
        path = Path(value).expanduser().resolve()
        return path if path.is_dir() else None
    except (OSError, RuntimeError):
        return None


def url_of(path: Path, locator: str | None, notes_dir: Path | None) -> str | None:
    if notes_dir is None:
        return None
    try:
        target = path.expanduser().resolve()
        base = notes_dir.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if target.suffix.lower() != ".md":
        return None
    try:
        rel = target.relative_to(base)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] in ("index", "README"):
        parts.pop()
    url = "/" + "/".join(quote(part) for part in parts) + ("/" if parts else "")
    if (not locator or _LINES.match(locator) or _PAGE.match(locator)
            or any(ch in locator for ch in _MARKUP)):
        return url
    try:
        sections = outline(target)
    except (OSError, ValueError):
        return url
    found = next((i for i, section in enumerate(sections)
                  if section.title.casefold() == locator.casefold()), None)
    if found is None:
        return url
    return f"{url}#{anchors([section.title for section in sections])[found]}"
