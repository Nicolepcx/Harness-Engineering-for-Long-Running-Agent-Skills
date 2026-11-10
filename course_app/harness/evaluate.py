"""
Hands-on 1: generate several candidates from one compiled surface, then match the checker to the question.

deterministic_problems()  counts and closed sets, read from the compiled rules: right every time, blind to paraphrase
rank()                    relative judging: which candidate reads best; says nothing about whether any may ship
verify()                  judge-verifier: one candidate against the rules; every finding must quote a rule id and name a leaf
pool_rank()               judge pool: several judges rank independently, the harness aggregates
trace_record()            what the execution trace keeps: skill version, surface digest, model bindings, every verdict
"""

import re

from harness.artifacts import Surface
from harness.models import JUDGE, WRITER, call_json

LEAVES = ["status", "eta", "action", "contact"]

# The fixed task for the hands-on: one shipment, one exception.
TASK_AXES = {"carrier": "ups", "recipient": "consumer", "notice": "delay"}
TASK_FACTS = {
    "tracking_id": "1Z999AA10123456784",
    "carrier": "UPS",
    "recipient": "consumer",
    "last_scan": "Louisville KY, Nov 11 06:40: departed the hub after the scheduled linehaul",
    "exception": "EXC-204 missed linehaul connection",
    "eta": "not yet confirmed by the carrier",
    "contact": "help@acmeparcel.example or 1-800-555-0199",
}

# Fixed teaching candidates: the same facts, written to make the three checkers disagree. Always labelled rehearsal.
REHEARSAL = {
    "A": {"status": "Your parcel left our Louisville hub late on Nov 11 after missing its onward connection.",
          "eta": "It should be with you shortly, most likely within the next day or two.",
          "action": "Nothing is needed from you.",
          "contact": "Reply to help@acmeparcel.example quoting UPS tracking id 1Z999AA10123456784."},
    "B": {"status": "We are sorry: your parcel departed our Louisville hub on Nov 11 later than scheduled.",
          "eta": "UPS has not yet confirmed a new delivery date.",
          "action": "Nothing is needed from you, and we will write again once a date is confirmed.",
          "contact": "You can reach us at help@acmeparcel.example, quoting UPS tracking id 1Z999AA10123456784."},
    "C": {"status": "Your parcel (EXC-204) left Louisville on Nov 11 after a missed linehaul connection.",
          "eta": "UPS has not yet confirmed a new date; expect delivery on Nov 13.",
          "action": "Nothing is needed from you.",
          "contact": "Reach us at help@acmeparcel.example with tracking id 1Z999AA10123456784."},
}

_WORD_LIMIT = re.compile(r"at most (\d+) words")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’@.-]*")
_DATE = re.compile(r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|\d{1,2}/\d{1,2}|monday|tuesday|"
                   r"wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|today)\b", re.I)
_CODE = re.compile(r"\b(EXC-\d+|HUB-\w+|SDF\d*)\b")


def leaves_text(cand: dict) -> str:
    return " ".join(str(cand.get(k, "")) for k in LEAVES)


def word_limit(surface: Surface) -> int:
    """The validator keeps no copy of the number: it reads the limit from the compiled rule (chapter pattern)."""
    m = _WORD_LIMIT.search(surface.text)
    if not m:
        raise ValueError("the compiled surface no longer states a word limit")
    return int(m.group(1))


def deterministic_problems(cand: dict, surface: Surface, facts: dict, axes: dict) -> list[dict]:
    """Everything decidable by counting or matching. Each problem names the rule and the leaf."""
    problems = []
    missing = [k for k in LEAVES if not str(cand.get(k, "")).strip()]
    if missing:
        problems.append({"rule": "notice.leaves", "leaf": ",".join(missing), "detail": f"missing leaves {missing}"})
    n = len(_WORD.findall(leaves_text(cand)))
    limit = word_limit(surface)
    if n > limit:
        problems.append({"rule": "notice.length", "leaf": "all", "detail": f"{n} words > {limit}"})
    if facts["tracking_id"] not in leaves_text(cand):
        problems.append({"rule": "notice.tracking", "leaf": "contact", "detail": "tracking id not quoted exactly"})
    if axes.get("recipient") == "consumer" and _CODE.search(leaves_text(cand)):
        problems.append({"rule": "notice.codes", "leaf": _leaf_with(cand, _CODE),
                         "detail": "internal code " + repr(_CODE.search(leaves_text(cand)).group(0))})
    if "not yet confirmed" in facts.get("eta", "") and _DATE.search(str(cand.get("eta", ""))):
        problems.append({"rule": "notice.eta-confirmed", "leaf": "eta",
                         "detail": f"names a time {_DATE.search(str(cand.get('eta', ''))).group(0)!r} with no confirmed ETA"})
    return problems


def _leaf_with(cand: dict, rx) -> str:
    return next((k for k in LEAVES if rx.search(str(cand.get(k, "")))), "all")


# ------------------------------------------------------------------ the writer
WRITER_SYSTEM = "You are the shipment exception desk agent. Follow the instructions exactly. Reply with JSON only."


def generate_candidates(surface: Surface, n: int = 3):
    user = (surface.text + f"\n\nWrite {n} different candidate notices for this shipment. Vary the wording.\n"
            'Reply as {"candidates": [{"status": "...", "eta": "...", "action": "...", "contact": "..."}, ...]}.')
    data, usage, _ = call_json(WRITER, WRITER_SYSTEM, user, max_tokens=2500)
    cands = [c for c in data.get("candidates", []) if isinstance(c, dict)][:n]
    if not cands:
        raise ValueError("the writer returned no candidates")
    return {chr(65 + i): {k: re.sub(r"^\s*\d+\.\s*", "", str(c.get(k, ""))).strip() for k in LEAVES}
            for i, c in enumerate(cands)}, usage


# ------------------------------------------------------------------ relative judging
def rank(cands: dict, facts: dict):
    system = ("You judge customer delivery notices against each other for clarity, calm and usefulness to the "
              "recipient. You do not check rules. Reply with JSON only.")
    listing = "\n\n".join(f"{k}:\n" + "\n".join(f"  {i + 1}. {c[l]}" for i, l in enumerate(LEAVES)) for k, c in cands.items())
    user = ("Shipment facts:\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items()) + f"\n\nCandidates:\n{listing}\n\n"
            'Rank all candidates from best to worst. Reply as {"ranking": [{"id": "A", "reason": "one sentence, under 20 words"}, ...]}.')
    data, usage, _ = call_json(JUDGE, system, user, max_tokens=1200)
    seen, order = set(), []
    for r in data.get("ranking", []):
        if isinstance(r, dict) and r.get("id") in cands and r["id"] not in seen:
            seen.add(r["id"]); order.append({"id": r["id"], "reason": str(r.get("reason", ""))})
    order += [{"id": k, "reason": "(not ranked)"} for k in cands if k not in seen]
    return order, usage


def pool_rank(cands: dict, facts: dict):
    """Three judges, two lenses, two model families; Borda aggregate; disagreement shown, never hidden."""
    pool = [("judge-1", JUDGE, "clarity and calm"), ("judge-2", JUDGE, "usefulness to the recipient: do they know what happens next"),
            ("judge-3", "openai/gpt-6-luna-pro", "clarity and calm")]
    listing = "\n\n".join(f"{k}: " + " ".join(c[l] for l in LEAVES) for k, c in cands.items())
    votes, usages, scores = [], [], {k: 0 for k in cands}
    for name, model, lens in pool:
        data, usage, _ = call_json(model, f"You are {name}. You compare delivery notices for {lens}. You do not check rules. JSON only.",
                                   f"Candidates:\n{listing}\n\nRank all from best to worst for {lens}. Reply as {{\"ranking\": [\"A\", ...]}}.",
                                   max_tokens=600)
        order = [x for x in data.get("ranking", []) if x in cands] + [k for k in cands if k not in data.get("ranking", [])]
        for pos, k in enumerate(order):
            scores[k] += len(cands) - 1 - pos
        votes.append({"judge": name, "model": model, "lens": lens, "ranking": order})
        usages.append(usage)
    return {"votes": votes, "scores": scores, "aggregate": sorted(cands, key=lambda k: -scores[k]),
            "unanimous": len({tuple(v["ranking"]) for v in votes}) == 1}, usages


# ------------------------------------------------------------------ judge-verifier
def verify(cand: dict, surface: Surface, facts: dict):
    """One candidate against the compiled rules. A finding must quote a rule id that exists and name a leaf."""
    rules = surface.rules()
    system = ("You are the verifier for the shipment exception desk. You check one notice against numbered rules and "
              "the shipment facts. Report every rule it breaks, naming the leaf (status, eta, action or contact) and quoting "
              "the words that break it. Paraphrase counts: implying a time is stating a time. Reply with JSON only.")
    user = ("Rules:\n" + "\n".join(f"[{rid}] {text}" for rid, text in rules.items())
            + "\n\nFacts:\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())
            + "\n\nNotice:\n" + "\n".join(f"{i + 1}. {l}: {cand[l]}" for i, l in enumerate(LEAVES))
            + '\n\nReply as {"findings": [{"rule_id": "...", "leaf": "...", "quote": "...", "explanation": "one sentence"}]}. '
              "Empty list if it follows every rule.")
    data, usage, _ = call_json(JUDGE, system, user, max_tokens=1500)
    findings = [f for f in data.get("findings", []) if isinstance(f, dict)]
    for f in findings:
        f["rule_exists"] = f.get("rule_id") in rules          # gate: a quote that is not in the rules is dropped
        f["leaf_known"] = f.get("leaf") in LEAVES
    cited = [f for f in findings if f["rule_exists"] and f["leaf_known"]]
    return {"verdict": "fail" if cited else "pass", "findings": findings}, usage


# ------------------------------------------------------------------ the trace
def trace_record(selection: list, surface: Surface, cands: dict, source: str, det: dict, ranking: list | None,
                 pool: dict | None, verdicts: dict, accepted: str | None) -> dict:
    return {
        "skill": {"artifacts": [{"ref": a.ref, "kind": a.kind, "digest": a.digest} for a in selection],
                  "axes": surface.manifest["axes"]},
        "compiled_surface": {"digest": surface.digest, "sections": surface.manifest["sections"],
                             "rules": list(surface.rules())},
        "model_bindings": {"writer": WRITER if source == "live" else None, "judge": JUDGE,
                           "pool": [v["model"] for v in pool["votes"]] if pool else None},
        "candidates": {"source": source, "items": cands},
        "evaluation": {"deterministic": {k: [p["rule"] for p in v] for k, v in det.items()},
                       "relative": [r["id"] for r in ranking] if ranking else None,
                       "pool": pool["aggregate"] if pool else None,
                       "verifier": {k: {"verdict": v["verdict"],
                                        "findings": [f"{f['rule_id']}@{f['leaf']}" for f in v["findings"] if f.get("rule_exists")]}
                                    for k, v in verdicts.items()}},
        "accepted": accepted,
    }
