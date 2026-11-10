"""
Skill artifacts and the runtime compiler, following the course's Chapter 3 pattern.

parse()            a markdown file with frontmatter and <!-- section: id --> markers -> a typed, hashed, versioned record
catalogue()        discovery metadata only: what the skill index shows
slice_section()    keep only the blocks whose "### Axis: value" heading matches the task axes
load_for_task()    selection; refuses an ambiguous surface (two artifacts owning one section)
compile_surface()  one flat instruction surface for one task + a manifest with every digest
everything_surface() the baseline that injects every artifact unsliced

Rule ids like [notice.eta-confirmed] stay in the text verbatim so a finding can quote them.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
KIND_PRECEDENCE = ("identity", "project", "skill", "persona")

_FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
_SECTION = re.compile(r"<!--\s*section:\s*([\w.-]+)\s*-->")
_H3 = re.compile(r"^### ([A-Za-z]+): ([\w-]+)\s*$", re.M)
_RULE = re.compile(r"\[([a-z]+\.[a-z-]+)\]")


class CompileError(Exception):
    pass


@dataclass(frozen=True)
class Artifact:
    kind: str            # identity | project | skill | persona
    name: str
    version: str
    path: str
    meta: dict
    sections: dict       # section id -> body
    digest: str          # sha256 of the file contents, 12 chars: a changed file shows even without a version bump

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def always_loaded(self) -> bool:
        return bool(self.meta.get("always_loaded"))

    @property
    def owns(self) -> list:
        return list(self.meta.get("owns") or [])

    @property
    def axes(self) -> list:
        return list(self.meta.get("axes") or [])

    @property
    def status(self) -> str:
        return str(self.meta.get("status", "active"))


def _parse_front(text: str) -> dict:
    """A deliberately small YAML subset: key: scalar | [a, b]."""
    meta = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        elif value in ("true", "false"):
            meta[key.strip()] = value == "true"
        else:
            meta[key.strip()] = value
    return meta


def parse(path: Path) -> Artifact:
    raw = Path(path).read_text()
    m = _FRONT.match(raw)
    if not m:
        raise CompileError(f"{path}: no frontmatter")
    meta = _parse_front(m.group(1))
    body = raw[m.end():]
    parts = _SECTION.split(body)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    declared = set(meta.get("owns") or [])
    if declared != set(sections):
        raise CompileError(f"{path}: owns {sorted(declared)} but writes {sorted(sections)}")
    return Artifact(meta["artifact"], meta["name"], str(meta["version"]), str(path), meta, sections,
                    hashlib.sha256(raw.encode()).hexdigest()[:12])


def load_all() -> list[Artifact]:
    return sorted((parse(p) for p in SKILLS_DIR.rglob("*.md")), key=lambda a: (KIND_PRECEDENCE.index(a.kind), a.name, a.version))


def catalogue(artifacts: list[Artifact]) -> list[dict]:
    """Discovery: the index shows metadata, never bodies."""
    return [{"kind": a.kind, "name": a.name, "version": a.version, "status": a.status, "digest": a.digest,
             "axes": a.axes, "description": a.meta.get("description", ""), "always_loaded": a.always_loaded}
            for a in artifacts]


def overlap(artifacts: list[Artifact]) -> dict:
    owners: dict[str, list] = {}
    for a in artifacts:
        for s in a.owns:
            owners.setdefault(s, []).append(a.ref)
    return {s: refs for s, refs in owners.items() if len(refs) > 1}


def load_for_task(artifacts: list[Artifact], names: list[str]) -> list[Artifact]:
    """Selection: the always-loaded artifacts plus the named ones, at their active version. One owner per section."""
    chosen = [a for a in artifacts if a.always_loaded]
    for name in names:
        matches = [a for a in artifacts if a.name == name and not a.always_loaded]
        if not matches:
            raise CompileError(f"selection: no artifact named {name!r}")
        active = [a for a in matches if a.status == "active"]
        if not active:
            a = matches[-1]
            raise CompileError(f"selection: {a.ref} is {a.status}; use {name}@{a.meta.get('superseded_by', '?')}")
        chosen.append(sorted(active, key=lambda a: a.version)[-1])
    clash = overlap(chosen)
    if clash:
        raise CompileError("ambiguous surface — every section needs exactly one owner: "
                           + "; ".join(f"{s} <- {', '.join(r)}" for s, r in clash.items()))
    return chosen


def _heading_axes(heading: str) -> dict:
    m = _H3.match(heading)
    return {m.group(1).lower(): m.group(2).lower()} if m else {}


def slice_section(body: str, axes: dict) -> str:
    """Keep the text before the first variant heading, then only the blocks whose axis matches the task."""
    marks = list(_H3.finditer(body))
    if not marks:
        return body
    kept = [body[:marks[0].start()].strip()]
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        block = body[mark.end():end].strip()
        wanted = _heading_axes(mark.group(0))
        if wanted and any(str(axes.get(k, "")).lower() != v for k, v in wanted.items()):
            continue
        kept.append(block)
    return "\n\n".join(x for x in kept if x)


@dataclass
class Surface:
    text: str
    manifest: dict

    @property
    def digest(self) -> str:
        return self.manifest["surface_digest"]

    def rules(self) -> dict:
        """Rule id -> the sentence that carries it, read back from the compiled text."""
        out = {}
        for para in re.split(r"\n\s*\n", self.text):
            for rid in _RULE.findall(para):
                out[rid] = para.strip()
        return out


def compile_surface(artifacts: list[Artifact], axes: dict, facts: dict) -> Surface:
    """Settle everything the harness can decide before calling a model: one flat surface, one manifest, one digest."""
    blocks, used, seen = [], [], set()
    for a in artifacts:
        for sid, body in a.sections.items():
            text = slice_section(body, axes) if a.axes else body
            text = "\n\n".join(p for p in re.split(r"\n\s*\n", text) if p.strip() and not (p.strip() in seen or seen.add(p.strip())))
            if not text.strip():
                continue
            blocks.append(text)
            used.append({"artifact": a.name, "version": a.version, "digest": a.digest, "section": sid})
    if facts:
        blocks.append("## Facts supplied by the harness\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())
                      + "\nDo not infer any fact that is not listed.")
    compiled = "\n\n".join(blocks)
    return Surface(compiled, {"axes": dict(axes), "facts": dict(facts), "sections": used,
                              "surface_digest": hashlib.sha256(compiled.encode()).hexdigest()[:12]})


def everything_surface(artifacts: list[Artifact], facts: dict) -> Surface:
    """The baseline: every artifact, every variant, unsliced. What a harness without a compiler sends."""
    blocks = [body for a in artifacts for body in a.sections.values()]
    if facts:
        blocks.append("## Facts\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items()))
    compiled = "\n\n".join(blocks)
    return Surface(compiled, {"axes": {}, "facts": dict(facts), "sections": [{"artifact": a.name, "version": a.version,
                              "digest": a.digest, "section": s} for a in artifacts for s in a.sections],
                              "surface_digest": hashlib.sha256(compiled.encode()).hexdigest()[:12]})
