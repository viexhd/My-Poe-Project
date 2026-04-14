"""Small poe.re-style query parser.

Grammar (intentionally tiny — **not** a real regex engine):

    query   := group (AND_SEP group)*
    group   := atom (PIPE atom)*
    atom    := ['!'] phrase
    phrase  := BARE_WORD | '"' any_chars '"'
    AND_SEP := ',' | '\n'
    PIPE    := '|'

Semantics (matches poe.re conventions):

    * Top-level groups separated by comma or newline are AND.
    * `|` inside a group is OR.
    * `!` negates a single atom.
    * Multi-word mods may be written with spaces **or** in quotes — the
      tokenizer treats `|`, `,`, `"` as the only structural characters
      so `!no regen | reflect` is unambiguous.

Examples:

    "!reflect"                 -> NOT reflect
    "!reflect|!no regen"       -> one OR group: NOT reflect OR NOT no regen
                                  (= NOT(reflect AND no regen))
    "!reflect, !no regen"      -> two AND groups, both negated
    "reflect|elemental weakness" -> at least one of {reflect, ele weak}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Atom:
    mod: str
    negate: bool = False

    def __str__(self) -> str:
        return ("!" if self.negate else "") + self.mod


@dataclass
class Group:
    atoms: List[Atom] = field(default_factory=list)

    @property
    def all_negative(self) -> bool:
        return bool(self.atoms) and all(a.negate for a in self.atoms)

    @property
    def all_positive(self) -> bool:
        return bool(self.atoms) and all(not a.negate for a in self.atoms)

    def __str__(self) -> str:
        return " | ".join(str(a) for a in self.atoms)


@dataclass
class ParsedQuery:
    groups: List[Group] = field(default_factory=list)

    def __str__(self) -> str:
        return ", ".join(str(g) for g in self.groups)


def _split_top(text: str, sep_chars: str) -> List[str]:
    """Split on sep_chars but respect double-quoted spans."""
    out: List[str] = []
    buf: List[str] = []
    in_q = False
    for ch in text:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif not in_q and ch in sep_chars:
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _clean(s: str) -> str:
    return s.strip().strip('"').strip()


def parse(text: str) -> ParsedQuery:
    if not text:
        return ParsedQuery()
    query = ParsedQuery()
    for raw_group in _split_top(text, ",\n"):
        atoms: List[Atom] = []
        for raw_atom in _split_top(raw_group, "|"):
            t = _clean(raw_atom)
            if not t:
                continue
            neg = t.startswith("!")
            if neg:
                t = _clean(t[1:])
            if t:
                atoms.append(Atom(mod=t, negate=neg))
        if atoms:
            query.groups.append(Group(atoms=atoms))
    return query
