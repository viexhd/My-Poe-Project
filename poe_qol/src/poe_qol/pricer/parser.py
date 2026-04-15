"""PoE clipboard-item text parser.

PoE's ``Ctrl+C`` format is stable and section-delimited. Sections are
separated by a line of eight dashes (``--------``). Each section either:

    * starts with ``Key: value`` lines (header / properties / requirements)
    * contains a socket string (``Sockets: R-G-B G-G``)
    * lists item-level / talisman-tier (``Item Level: 85``)
    * lists mods, one per line, optionally suffixed with tags in
      parentheses (``(implicit)``, ``(crafted)``, ``(fractured)``)
    * is the flavour text of a unique
    * is the note line written by PoE or the user (``Note: ~price 1 divine``)

We parse the first two sections deterministically (they carry
``Item Class`` / ``Rarity`` / name / base) then walk the remaining
sections heuristically. The goal isn't 100% fidelity — it's *enough*
structure to build a trade-site query and know which pricing endpoint
(bulk exchange vs search) to hit.

Test coverage lives in ``tests/test_pricer_parser.py``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


SECTION_RE = re.compile(r"^-{4,}\s*$", re.MULTILINE)  # PoE uses 8, tolerate 4+


class Category(str, Enum):
    """Coarse pricing category. Drives endpoint selection in search.py.

    Values are the strings pathofexile.com uses for bulk-exchange
    slugs where applicable, so the search layer can pass them through.
    """
    CURRENCY = "currency"       # stackable currency → bulk exchange
    FRAGMENT = "fragment"       # sac fragments / scarabs → bulk exchange
    DIVINATION = "divination"   # div cards → bulk exchange
    ESSENCE = "essence"         # essences → bulk exchange
    UNIQUE = "unique"           # name + type search
    MAP = "map"                 # type search + map-tier filter
    GEM = "gem"                 # type search + level/quality filters
    JEWEL = "jewel"             # stat-filter search (MVP: type-only)
    FLASK = "flask"             # stat-filter search (MVP: type-only)
    EQUIPMENT = "equipment"     # rare/magic/normal gear (stat filters needed)
    UNKNOWN = "unknown"


@dataclass
class ParsedItem:
    # ---- header ----
    item_class: str = ""          # "Item Class: <value>"
    rarity: str = ""              # Normal | Magic | Rare | Unique | Currency | ...
    name: str = ""                # first name line; for rares this is the prefix+base
    base_type: str = ""           # base type (second name line when present)

    # ---- derived ----
    category: Category = Category.UNKNOWN

    # ---- properties / meta ----
    item_level: int | None = None
    gem_level: int | None = None
    map_tier: int | None = None
    quality: int | None = None
    sockets: str | None = None    # raw "R-G-B G" string
    stack_size: tuple[int, int] | None = None   # (current, max) for stackables
    note: str | None = None       # "~price X Y" or free-form

    # ---- mods ----
    implicits: list[str] = field(default_factory=list)
    explicits: list[str] = field(default_factory=list)
    fractured: list[str] = field(default_factory=list)
    crafted: list[str] = field(default_factory=list)
    enchants: list[str] = field(default_factory=list)

    # ---- flags ----
    corrupted: bool = False
    mirrored: bool = False
    unidentified: bool = False
    influences: list[str] = field(default_factory=list)

    # Raw sections (for debugging / future extensions).
    raw: list[str] = field(default_factory=list)

    # ---- query helpers ----
    @property
    def is_stackable_currency_like(self) -> bool:
        return self.category in (Category.CURRENCY, Category.FRAGMENT,
                                 Category.DIVINATION, Category.ESSENCE)

    @property
    def trade_name(self) -> str:
        """What to send as ``query.name`` on the trade API.

        Uniques need their unique name; everything else leaves it empty
        (the type field carries enough information). Rares in this MVP
        also drop the name — the random prefix/suffix isn't searchable.
        """
        if self.rarity.lower() == "unique":
            return self.name
        return ""

    @property
    def trade_type(self) -> str:
        """What to send as ``query.type`` (item base type)."""
        return self.base_type or self.name


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_NOTE_RE = re.compile(r"^\s*(?:Note:|~price|~b/o)\s*", re.IGNORECASE)
_PROP_RE = re.compile(r"^([^:]+):\s*(.+?)\s*$")
_TAG_RE = re.compile(r"\s*\((implicit|crafted|fractured|enchant|"
                     r"enchanted|scourge|exarch|eater|veiled)\)\s*$",
                     re.IGNORECASE)
_AUGMENTED_RE = re.compile(r"\s*\((?:augmented|unmet)\)\s*$")
_STACK_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")

# Item-class strings we actively recognise. Matching is case-insensitive
# and substring-based so new league-specific variants (e.g. "Heist
# Contracts") still bucket sensibly.
_CLASS_CATEGORY: list[tuple[str, Category]] = [
    ("stackable currency",       Category.CURRENCY),
    ("currency",                 Category.CURRENCY),
    ("delirium orb",             Category.CURRENCY),
    ("incubator",                Category.CURRENCY),
    ("map fragment",             Category.FRAGMENT),
    ("fragment",                 Category.FRAGMENT),
    ("scarab",                   Category.FRAGMENT),
    ("divination card",          Category.DIVINATION),
    ("essence",                  Category.ESSENCE),
    ("map",                      Category.MAP),
    ("active skill gem",         Category.GEM),
    ("support skill gem",        Category.GEM),
    ("gem",                      Category.GEM),
    ("jewel",                    Category.JEWEL),
    ("flask",                    Category.FLASK),
]


def _split_sections(text: str) -> list[list[str]]:
    """Split on ``--------`` lines, keep non-empty lines per section."""
    blocks = SECTION_RE.split(text.strip("\r\n"))
    sections: list[list[str]] = []
    for b in blocks:
        lines = [ln.rstrip() for ln in b.splitlines() if ln.strip()]
        if lines:
            sections.append(lines)
    return sections


def _parse_header(lines: list[str], item: ParsedItem) -> None:
    """Consume the first section: Item Class / Rarity / name / base."""
    props: dict[str, str] = {}
    name_lines: list[str] = []
    for ln in lines:
        m = _PROP_RE.match(ln)
        if m and m.group(1).strip().lower() in ("item class", "rarity"):
            props[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            name_lines.append(ln)
    item.item_class = props.get("item class", "")
    item.rarity = props.get("rarity", "")
    # name-lines length varies by rarity:
    #   Currency / Normal / Magic → one line (the base / magic roll)
    #   Rare / Unique            → two lines (affix line + base type)
    if len(name_lines) >= 2:
        item.name = name_lines[0]
        item.base_type = name_lines[1]
    elif name_lines:
        item.name = name_lines[0]
        item.base_type = name_lines[0]


def _category_for(item_class: str, base_type: str, rarity: str) -> Category:
    cls = item_class.lower()
    for needle, cat in _CLASS_CATEGORY:
        if needle in cls:
            return cat
    # Fallback: infer from rarity.
    r = rarity.lower()
    if r == "unique":
        return Category.UNIQUE
    # Rare / magic / normal equipment lives in the long tail of
    # item-class strings ("Gloves", "Two Hand Swords", …). Group them
    # as EQUIPMENT so the search layer can choose a type-only query.
    return Category.EQUIPMENT if cls else Category.UNKNOWN


def _strip_value_suffix(value: str) -> str:
    """Drop ``(augmented)`` etc. and trailing whitespace."""
    return _AUGMENTED_RE.sub("", value).strip()


def _parse_properties_section(lines: list[str], item: ParsedItem) -> None:
    """Section of ``Key: value`` rows. May include quality, map tier,
    stack size, gem level, etc."""
    for ln in lines:
        m = _PROP_RE.match(ln)
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = _strip_value_suffix(m.group(2))
        if key == "quality":
            try:
                item.quality = int(val.lstrip("+").rstrip("%"))
            except ValueError:
                pass
        elif key == "stack size":
            sm = _STACK_RE.match(val)
            if sm:
                item.stack_size = (int(sm.group(1)), int(sm.group(2)))
        elif key == "map tier":
            try:
                item.map_tier = int(val)
            except ValueError:
                pass
        elif key == "level" and item.category == Category.GEM:
            # Gem level in a properties section; requirement level uses
            # the same key but lives in a different section handled
            # separately.
            try:
                item.gem_level = int(val)
            except ValueError:
                pass


def _parse_mods_section(lines: list[str], item: ParsedItem) -> None:
    """Explicit / implicit / crafted / fractured mods.

    Mods tagged ``(implicit)``/``(crafted)``/… are bucketed accordingly.
    Untagged mods in this section are treated as explicits.
    """
    for ln in lines:
        tag = ""
        m = _TAG_RE.search(ln)
        stripped = ln
        if m:
            tag = m.group(1).lower()
            stripped = _TAG_RE.sub("", ln).rstrip()
        if tag == "implicit":
            item.implicits.append(stripped)
        elif tag == "crafted":
            item.crafted.append(stripped)
        elif tag == "fractured":
            item.fractured.append(stripped)
        elif tag in ("enchant", "enchanted"):
            item.enchants.append(stripped)
        else:
            item.explicits.append(stripped)


def _looks_like_mod_section(lines: list[str]) -> bool:
    """Heuristic: section is a mod-list if at least half its lines
    either carry a mod-tag (implicit/crafted/…) or contain numeric
    rolls (``+71 to maximum Life``). Otherwise it's probably flavour
    text or vendor recipe prose."""
    hits = 0
    for ln in lines:
        if _TAG_RE.search(ln):
            hits += 1
        elif re.search(r"\d", ln) and not _PROP_RE.match(ln):
            hits += 1
    return hits * 2 >= len(lines)


def parse_item(text: str) -> ParsedItem | None:
    """Parse a PoE clipboard string. Returns ``None`` for non-item
    text so callers can no-op on stray clipboard changes."""
    if not text or "Item Class:" not in text:
        return None
    sections = _split_sections(text)
    if not sections:
        return None
    item = ParsedItem(raw=[", ".join(s) for s in sections])

    # First section is always the header.
    _parse_header(sections[0], item)
    item.category = _category_for(item.item_class, item.base_type, item.rarity)

    # Flag lines that can appear anywhere in the middle sections.
    for sec in sections[1:]:
        for ln in sec:
            low = ln.lower()
            if low == "corrupted":
                item.corrupted = True
            elif low == "mirrored":
                item.mirrored = True
            elif low == "unidentified":
                item.unidentified = True
            elif low.endswith(" item") and "influence" in low:
                # "Shaper Item", "Elder Item", "Crusader Item", …
                item.influences.append(ln.split()[0].lower())

    # Note: price hint — PoE places it in its own section.
    for sec in sections:
        for ln in sec:
            if _NOTE_RE.match(ln):
                item.note = _NOTE_RE.sub("", ln).strip()
                break
        if item.note:
            break

    # Walk the remaining sections and classify.
    for sec in sections[1:]:
        first = sec[0]
        # "Sockets: ..." is a single-line section.
        if first.lower().startswith("sockets:"):
            item.sockets = first.split(":", 1)[1].strip()
            continue
        # "Item Level: 85" – can share a section with requirements.
        if any(l.lower().startswith("item level:") for l in sec):
            for l in sec:
                if l.lower().startswith("item level:"):
                    try:
                        item.item_level = int(l.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                    break
            continue
        # "Requirements:" header → skip, we don't use it for pricing.
        if first.lower().startswith("requirements"):
            continue
        # Properties (quality / tier / stack / map tier / gem level).
        if any(_PROP_RE.match(l) for l in sec) and not _looks_like_mod_section(sec):
            _parse_properties_section(sec, item)
            continue
        # Mod section.
        if _looks_like_mod_section(sec):
            _parse_mods_section(sec, item)
            continue
        # Fallback: ignore flavour / vendor blurb.

    return item
