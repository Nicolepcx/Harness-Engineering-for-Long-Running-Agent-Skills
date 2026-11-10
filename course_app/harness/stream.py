"""
Hands-on 2: one shipment, a stream of scans and corrections over a shift, one notice due at the end.

Three harnesses process the same stream with the same tracker model:
  transcript  the paper's ReAct baseline: instructions + every earlier event, appended in full
  window      the same, cut to the state harness's mean prompt size (the budget-matched control)
  state       skill_state.SkillStateRuntime: (P, Σ_t, O_t) in, (R_t, ΔΣ_t, a_t) out, Σ ⊕ ΔΣ validated, rollback-retry

At the WRITE event the writer is identical for all three; only its input differs: the event log, or Σ.
Then: deterministic graders, a judge-verifier, a provenance test, and targeted repair of one leaf.
"""

import copy
import json
import re
from dataclasses import dataclass

from skill_state import LLMResult, ParseError, Skill, SkillStateRuntime, build_prompt, merge, parse_response, validate

from harness import artifacts as A
from harness import evaluate as E
from harness.models import JUDGE, WRITER, call_json
from core import llm

# ------------------------------------------------------------------ the stream
@dataclass
class Event:
    id: str
    text: str
    kind: str         # fact | correction | trap | noise | write
    note: str = ""    # what a correct tracker does with it


CORE = [
    Event("e1", "Scan: parcel 1Z999AA10123456784 (UPS) departed Louisville KY hub Nov 11 06:40, after the scheduled linehaul. Exception EXC-204 missed linehaul connection.", "fact", "record location, status, exception"),
    Event("e2", "Carrier estimate: arrival Nov 12. Status: estimate, not confirmed.", "trap", "record the date as an estimate (confirmed=false); it is not a promise"),
    Event("e3", "Recipient request: delivery address corrected to 1420 Maple St, Apt 4B, Columbus OH (was Apt 2B).", "fact", "replace the address"),
    Event("e4", "Scan: parcel arrived at Chicago IL hub, Nov 11 15:10.", "fact", "update location"),
    Event("e5", "Correction from UPS: the 15:10 Chicago scan was mis-posted. The parcel is at the Indianapolis IN hub; arrived Nov 11 14:52.", "correction", "replace the location (the Chicago scan never happened)"),
    Event("e6", "UPS confirmation: delivery Nov 13, confirmed. Recipient asked for redirect to UPS Access Point #118; redirect is now in force.", "fact", "eta becomes confirmed Nov 13; record the reroute"),
    Event("e7", "Correction from UPS: confirmed delivery date is Nov 14, not Nov 13. The Access Point redirect was cancelled by the recipient; home delivery stands.", "correction", "replace the eta; delete the reroute with null"),
    Event("e8", "Dispatch request: send the recipient the delivery notice now.", "write", "the deliverable is due: action SEND"),
]
TELEMETRY = [   # Appendix C style distractors, appended under a telemetry header to every observation
    "[Hub] sorter 3 throughput 4,120/h, belt temp 88F, jam count 0",
    "[Scan] parcel 1Z999AA10123456791 arrived Chicago IL hub",
    "[Chat] 'anyone seen the printer paper?'",
    "[Scan] parcel 1Z999AA10123456802 delivered, Dayton OH",
    "[Hub] dock 7 occupied, trailer KY-4411, dwell 00:42",
    "[CI] exceptions-dashboard build #4821 passed in 6m12s",
    "[Scan] parcel 1Z999AA10123456815 departed Louisville KY hub",
    "[Weather] Indianapolis 43F, light rain, wind 9 mph",
    "[Sensor] humidity 45%, temp 72F, light 310 lux, CO2 450 ppm",
    "[Camera OCR] forklift parked, bay 2 clear",
    "[Hub] inbound ETA board refreshed, 14 trailers listed",
    "[Scan] parcel 1Z999AA10123456828 held for address check, Cincinnati OH",
]


def make_stream(noise_per_turn: int = 4, horizon: int | None = None) -> list[Event]:
    """
    The shipment events, each delivered with `noise_per_turn` telemetry lines appended (the paper's noise setting).
    With `horizon` > 12, 'nothing new' observations are inserted between shipment events to make a longer shift;
    the shipment facts and the final WRITE stay the same.
    """
    core = list(CORE)
    if horizon and horizon > len(core):
        extra = horizon - len(core)
        out, k = [], 0
        for i, e in enumerate(core[:-1]):
            out.append(e)
            n_fill = extra // (len(core) - 1) + (1 if i < extra % (len(core) - 1) else 0)
            for _ in range(n_fill):
                out.append(Event(f"q{k}", "No new scan for parcel 1Z999AA10123456784.", "noise")); k += 1
        out.append(core[-1])
        core = out
    events = []
    for i, e in enumerate(core):
        lines = [TELEMETRY[(i * 5 + j) % len(TELEMETRY)] for j in range(noise_per_turn)]
        text = e.text + ("\n--- BACKGROUND TELEMETRY ---\n" + "\n".join(lines) if lines else "")
        events.append(Event(e.id, text, e.kind, e.note))
    return events


# The truth at the deadline, from the stream: what the writer needs, and what it must not use.
FACTS_REQUIRED = {
    "F1": ("confirmed delivery Nov 14", lambda s: "Nov 14" in s),
    "F2": ("location Indianapolis", lambda s: "Indianapolis" in s),
    "F3": ("address Apt 4B", lambda s: "4B" in s),
    "F4": ("home delivery (redirect cancelled)", lambda s: "access point" not in s.lower() and "#118" not in s),
    "F5": ("tracking id", lambda s: "1Z999AA10123456784" in s),
}
TRAPS = {
    "T1": ("Nov 12 (superseded estimate)", lambda s: "Nov 12" in s),
    "T2": ("Nov 13 (superseded confirmation)", lambda s: "Nov 13" in s),
    "T3": ("Chicago (mis-posted scan)", lambda s: "Chicago" in s),
    "T4": ("Apt 2B (old address)", lambda s: "2B" in s),
    "T5": ("Access Point #118 (cancelled redirect)", lambda s: "#118" in s),
}


# ------------------------------------------------------------------ Σ: the state schema, authored like a skill
STATE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["tracking_id", "carrier"],
    "properties": {
        "tracking_id": {"type": "string"}, "carrier": {"type": "string"},
        "status": {"type": "string"},
        "location": {"type": "object", "additionalProperties": False,
                     "properties": {"hub": {"type": "string"}, "at": {"type": "string"}}},
        "eta": {"type": "object", "additionalProperties": False,
                "properties": {"date": {"type": "string"}, "confirmed": {"type": "boolean"}}},
        "address": {"type": "string"},
        "exception": {"type": "string"},
        "cause": {"type": "string"},
        "reroute": {"type": "object", "additionalProperties": False, "properties": {"to": {"type": "string"}}},
        "notice_due": {"type": "boolean"},
    },
}
INITIAL_STATE = {"tracking_id": "1Z999AA10123456784", "carrier": "UPS", "notice_due": False}
STATE_SPEC = """
## Execution state
Earlier events will not be shown to you again. The state below is your only memory of this shipment.
Keys (all at the top level): tracking_id, carrier, status, location, eta, address, exception, cause, reroute, notice_due.
- location: {"hub": "<city>", "at": "<Mon d HH:MM>"}. A correction that a scan was mis-posted replaces it.
- eta: {"date": "<Mon d>", "confirmed": true|false}. An estimate is confirmed=false. A carrier confirmation
  replaces the whole object. A later confirmation supersedes an earlier one.
- address: the current delivery address only.
- reroute: {"to": "<place>"} only while a reroute is in force; set reroute to null when it is cancelled.
- cause: only a cause the carrier states. Questions and guesses are not causes.
- notice_due: true when a dispatch request arrives.
The action is exactly "SEND" when the latest observation is a dispatch request for the notice, and exactly "WAIT" on
every other observation (recording a correction is still WAIT). Ignore scans for other parcels and hub telemetry.
Keep your reasoning to two sentences.
"""


def _hub_by_city(state: dict) -> list[str]:
    """Network convention: hubs are referred to by city, never by code."""
    hub = (state.get("location") or {}).get("hub", "")
    return [f"location.hub must be a city name, not a code: {hub!r}"] if re.search(r"\d|HUB-|[A-Z]{3,}", hub) else []


def _date_format(state: dict) -> list[str]:
    d = (state.get("eta") or {}).get("date", "")
    return [] if not d or re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}", d) else [f"eta.date must look like 'Nov 12', got {d!r}"]


STATE_CHECKS = [_hub_by_city, _date_format]


def state_errors(state: dict) -> list[str]:
    return validate(state, STATE_SCHEMA) or [e for c in STATE_CHECKS for e in c(state)]


def tracker_surface() -> A.Surface:
    """P for the tracker: the network conventions only. The identity and the notice skill belong to the writer."""
    arts = A.load_all()
    return A.compile_surface([a for a in arts if a.kind == "project"], {}, {"shipment": "1Z999AA10123456784 (UPS)"})


def tracker_instructions() -> str:
    """The same P for every harness: conventions + the tracking task. Only the state harness adds Σ."""
    return tracker_surface().text + "\n" + STATE_SPEC


# ------------------------------------------------------------------ the prompts, side by side (paper, Appendix A)
def react_prompt(events: list[Event], t: int, history: list[str] | None = None) -> str:
    """A.1: instructions, every earlier observation and action, the latest observation (a correct tracker WAITs until the request)."""
    hist = history if history is not None else [f"[{i}] {events[i].text}\n-> Action: WAIT" for i in range(t)]
    return REACT.format(P=tracker_surface().text, history="\n".join(hist) or "(none)", obs=events[t].text)


def window_prompt(events: list[Event], t: int, budget_chars: int, history: list[str] | None = None) -> str:
    """Budget-matched: the most recent history lines that fit the state harness's mean prompt size."""
    hist = history if history is not None else [f"[{i}] {events[i].text}\n-> Action: WAIT" for i in range(t)]
    kept, size = [], 0
    for line in reversed(hist):
        if size + len(line) > budget_chars:
            break
        kept.insert(0, line); size += len(line)
    return REACT.format(P=tracker_surface().text, history="\n".join(kept) or "(none)", obs=events[t].text)


def state_prompt(events: list[Event], t: int, sigma: dict) -> str:
    """A.4: (P, Σ_t, O_t), built by skill_state itself."""
    from skill_state import build_prompt
    return build_prompt(tracker_instructions(), sigma, events[t].text)


def projected_growth(events: list[Event], budget_chars: int | None = None) -> list[int]:
    """Prompt size per step for the transcript (or window) with a correct tracker (WAIT until the WRITE): no model call."""
    return [len(window_prompt(events, t, budget_chars) if budget_chars else react_prompt(events, t)) for t in range(len(events))]


# ------------------------------------------------------------------ the LLM adapter and the three harnesses
class OpenRouterLLM:
    """skill_state's LLM protocol over the course's OpenRouter client. Each call is a fresh single-turn request."""

    def __init__(self, model: str, on_call=None):
        self.model, self.on_call, self.rejections = model, on_call, []

    def complete(self, prompt: str) -> LLMResult:
        m = re.search(r"was rejected: (.*?)\nThe state shown above is unchanged", prompt, re.S)
        if m:
            self.rejections.append(m.group(1).strip())     # the diagnostics skill_state fed back: the trace keeps them
        r = llm.client().chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}],
                                                 max_tokens=1500, temperature=0)
        u = r.usage
        if self.on_call:
            self.on_call(u.prompt_tokens, u.completion_tokens, getattr(u, "cost", None))
        return LLMResult(r.choices[0].message.content or "", u.prompt_tokens, u.completion_tokens)


class StreamEnv:
    def __init__(self, events: list[Event]):
        self.events, self.i = events, 0

    def reset(self) -> str:
        self.i = 0
        return self.events[0].text

    def step(self, action: str):
        self.i += 1
        done = self.i >= len(self.events)
        return ("All events processed." if done else self.events[self.i].text), done


def run_state(events: list[Event], tracker_model: str = WRITER, budget_call=None) -> dict:
    """The paper's loop, through the skill_state package."""
    P = tracker_surface()
    skill = Skill(name="shipment-tracker", instructions=tracker_instructions(), schema=STATE_SCHEMA,
                  initial_state=copy.deepcopy(INITIAL_STATE), checks=STATE_CHECKS, fallback_action="WAIT")
    log, usage = [], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}

    def on_call(pt, ct, cost):
        usage["calls"] += 1; usage["prompt_tokens"] += pt; usage["completion_tokens"] += ct; usage["cost_usd"] += float(cost or 0)
        if budget_call:
            budget_call()

    def on_step(rec):
        log.append({"t": rec["t"], "event": events[rec["t"]].id, "action": rec["action"], "attempts": rec["attempts"],
                    "fell_back": rec["fell_back"], "state": rec["state"], "reasoning": rec["reasoning"]})

    adapter = OpenRouterLLM(tracker_model, on_call)
    rt = SkillStateRuntime(skill, adapter, max_retries=2, max_state_chars=2500, on_step=on_step)
    res = rt.run(StreamEnv(events), max_steps=len(events))
    prompts = [s.prompt_chars for s in res.steps]
    return {"harness": "state", "steps": log, "final_state": res.final_state, "rejected_patches": res.rejected_patches,
            "rejections": adapter.rejections, "prompt_chars": prompts, "usage": usage, "surface_digest": P.digest,
            "wrote_at": [s["event"] for s in log if "SEND" in s["action"].upper()]}


ACTION_RULE = ('The action is exactly "SEND" when the latest observation is a dispatch request for the notice, and exactly '
               '"WAIT" on every other observation (a correction is still WAIT). Ignore scans for other parcels and hub telemetry.')
# ------------------------------------------------------------------ one step at a time (so the attendee can drive it)
def step_state(sigma: dict, events: list[Event], t: int, model: str = WRITER, max_retries: int = 2) -> dict:
    """
    One SKILL.state step, the package's Algorithm-1 loop made pausable: build (P, Σ_t, O_t) with skill_state.build_prompt,
    parse (R_t, ΔΣ_t, a_t) with parse_response, merge, validate on the merged state; on rejection keep Σ_t, feed the
    error back and retry; after max_retries fall back to WAIT with Σ unchanged. The reasoning is kept for the trace only.
    """
    adapter = OpenRouterLLM(model)
    attempts, retry_error, usage = [], None, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    adapter.on_call = lambda pt, ct, cost: (usage.__setitem__("calls", usage["calls"] + 1), usage.__setitem__("prompt_tokens", usage["prompt_tokens"] + pt),
                                             usage.__setitem__("completion_tokens", usage["completion_tokens"] + ct),
                                             usage.__setitem__("cost_usd", usage["cost_usd"] + float(cost or 0)))
    prompt_chars = None
    for _ in range(max_retries + 1):
        prompt = build_prompt(tracker_instructions(), sigma, events[t].text, retry_error)
        prompt_chars = prompt_chars or len(prompt)
        reply = adapter.complete(prompt)
        try:
            parsed = parse_response(reply.text)
            candidate = merge(sigma, parsed.state_patch)
            errors = state_errors(candidate)
            if errors:
                raise ParseError("; ".join(errors[:5]))
        except (ParseError, TypeError) as e:
            attempts.append({"patch": _patch_of(reply.text), "accepted": False, "error": str(e), "reasoning": _reasoning_of(reply.text)})
            retry_error = str(e)
            continue
        attempts.append({"patch": parsed.state_patch, "accepted": True, "error": None, "reasoning": parsed.reasoning.strip()})
        return {"t": t, "event": events[t].id, "mode": "model", "action": parsed.action.strip(), "attempts": attempts,
                "fell_back": False, "state": candidate, "reasoning": parsed.reasoning.strip(), "prompt_chars": prompt_chars, "usage": usage}
    return {"t": t, "event": events[t].id, "mode": "model", "action": "WAIT", "attempts": attempts, "fell_back": True,
            "state": copy.deepcopy(sigma), "reasoning": None, "prompt_chars": prompt_chars, "usage": usage}


def manual_step(sigma: dict, events: list[Event], t: int, patch: dict, action: str = "WAIT") -> dict:
    """The attendee's own ΔΣ_t, through exactly the same merge and validation. No model call."""
    candidate = merge(sigma, patch)
    errors = state_errors(candidate)
    ok = not errors
    return {"t": t, "event": events[t].id, "mode": "manual", "action": action,
            "attempts": [{"patch": patch, "accepted": ok, "error": None if ok else "; ".join(errors), "reasoning": "(written by you)"}],
            "fell_back": not ok, "state": candidate if ok else copy.deepcopy(sigma), "reasoning": None,
            "prompt_chars": len(build_prompt(tracker_instructions(), sigma, events[t].text)),
            "usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}}


def run_from_steps(steps: list[dict], events: list[Event]) -> dict:
    """Assemble the same run record run_state produces, from steps taken one at a time (model or manual)."""
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    for s_ in steps:
        for k in usage:
            usage[k] += s_["usage"][k]
    return {"harness": "state", "steps": steps, "final_state": steps[-1]["state"] if steps else copy.deepcopy(INITIAL_STATE),
            "rejected_patches": sum(1 for s_ in steps for a in s_["attempts"] if not a["accepted"]),
            "rejections": [a["error"] for s_ in steps for a in s_["attempts"] if not a["accepted"]],
            "prompt_chars": [s_["prompt_chars"] for s_ in steps], "usage": usage, "surface_digest": tracker_surface().digest,
            "wrote_at": [s_["event"] for s_ in steps if "SEND" in s_["action"].upper()],
            "manual_steps": [s_["event"] for s_ in steps if s_["mode"] == "manual"]}


def _patch_of(text: str):
    try:
        return parse_response(text).state_patch
    except Exception:
        m = re.search(r"```json\s*(.*?)```", text, re.S)
        return (m.group(1).strip()[:300] if m else text.strip()[:300])


def _reasoning_of(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S).strip()[:400]


REACT = ("Instructions:\n{P}\n\nYou track one shipment through a shift of events. " + ACTION_RULE
         + "\n\nHistory:\n{history}\n\nLatest Observation: {obs}\n\n"
         "Reply with two lines:\nReasoning: <one sentence>\nAction: <SEND|WAIT>")


def base_prompt_chars() -> int:
    """The transcript prompt with no history: what the window's budget is measured on top of."""
    return len(REACT.format(P=tracker_surface().text, history="", obs=""))


def window_budget(state_run: dict) -> int:
    """Budget-matched control: the window gets the same total prompt size as the state harness's mean prompt."""
    mean_state = sum(state_run["prompt_chars"]) / len(state_run["prompt_chars"])
    return max(200, int(mean_state - base_prompt_chars()))


def run_transcript(events: list[Event], tracker_model: str = WRITER, budget_chars: int | None = None, budget_call=None) -> dict:
    """ReAct-style replay: every earlier event stays in the prompt. With budget_chars, the most recent that fit (the window)."""
    P = tracker_surface().text
    history, log, prompts = [], [], []
    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    for t, ev in enumerate(events):
        hist = history
        if budget_chars is not None:
            hist, size = [], 0
            for line in reversed(history):
                if size + len(line) > budget_chars:
                    break
                hist.insert(0, line); size += len(line)
        prompt = REACT.format(P=P, history="\n".join(hist) or "(none)", obs=ev.text)  # same builder as react_prompt/window_prompt
        r = llm.client().chat.completions.create(model=tracker_model, messages=[{"role": "user", "content": prompt}],
                                                 max_tokens=400, temperature=0)
        u = r.usage
        usage["calls"] += 1; usage["prompt_tokens"] += u.prompt_tokens; usage["completion_tokens"] += u.completion_tokens
        usage["cost_usd"] += float(getattr(u, "cost", 0) or 0)
        if budget_call:
            budget_call()
        text = r.choices[0].message.content or ""
        m = re.search(r"Action:\s*(SEND|WAIT)", text, re.I)
        action = m.group(1).upper() if m else "WAIT"
        prompts.append(len(prompt))
        history.append(f"[{t}] {ev.text}\n-> Action: {action}")
        log.append({"t": t, "event": ev.id, "action": action, "history_lines": len(hist)})
    return {"harness": "window" if budget_chars is not None else "transcript", "steps": log, "prompt_chars": prompts,
            "usage": usage, "wrote_at": [s["event"] for s in log if s["action"] == "SEND"],
            "history": history, "budget_chars": budget_chars}


# ------------------------------------------------------------------ what the writer is handed
def log_input(events: list[Event], budget_chars: int | None = None) -> str:
    """The log a transcript (or window) harness hands the writer, without running a tracker: every observation, as carried."""
    hist = [f"[{i}] {e.text}\n-> Action: WAIT" for i, e in enumerate(events[:-1])]
    if budget_chars is not None:
        kept, size = [], 0
        for line in reversed(hist):
            if size + len(line) > budget_chars:
                break
            kept.insert(0, line); size += len(line)
        hist = kept
    return "\n".join(hist) + "\n- contact: help@acmeparcel.example or 1-800-555-0199"


def writer_input(run: dict, events: list[Event]) -> str:
    """Transcript and window: the event log they carry. State: Σ-derived facts only."""
    if run["harness"] == "state":
        s = run["final_state"]
        eta = s.get("eta") or {}
        facts = {"tracking_id": s.get("tracking_id", ""), "carrier": s.get("carrier", ""),
                 "status": s.get("status", ""), "location": f"{(s.get('location') or {}).get('hub', '')} {(s.get('location') or {}).get('at', '')}".strip(),
                 "eta": (f"{eta.get('date')} (confirmed by the carrier)" if eta.get("confirmed") else
                         f"{eta.get('date')} (carrier estimate, not confirmed)" if eta.get("date") else "not yet confirmed by the carrier"),
                 "address": s.get("address", ""), "exception": s.get("exception", ""),
                 "cause": s.get("cause") or "none on file", "reroute": (s.get("reroute") or {}).get("to") or "none; home delivery",
                 "contact": "help@acmeparcel.example or 1-800-555-0199"}
        return "\n".join(f"- {k}: {v}" for k, v in facts.items() if v != "")
    lines = run["history"] if run["harness"] == "transcript" else _window_lines(run)
    return "\n".join(lines) + "\n- contact: help@acmeparcel.example or 0800 555 0199"


def _window_lines(run: dict) -> list[str]:
    hist, size = [], 0
    for line in reversed(run["history"]):
        if size + len(line) > run["budget_chars"]:
            break
        hist.insert(0, line); size += len(line)
    return hist


def retained(text: str) -> dict:
    return {"facts": {k: bool(fn(text)) for k, (_, fn) in FACTS_REQUIRED.items()},
            "traps": {k: bool(fn(text)) for k, (_, fn) in TRAPS.items()}}


def write_notice(input_text: str):
    """The hands-on 1 writer, unchanged: compiled surface for this task + the facts the harness hands over."""
    arts = A.load_all()
    sel = A.load_for_task(arts, ["delivery-notice"])
    surface = A.compile_surface(sel, {"carrier": "ups", "recipient": "consumer", "notice": "delay"}, {})
    user = (surface.text + "\n\n## What you know about this shipment\n" + input_text
            + "\n\nWrite the notice. Reply as {\"status\": \"...\", \"eta\": \"...\", \"action\": \"...\", \"contact\": \"...\"}.")
    data, usage, _ = call_json(WRITER, E.WRITER_SYSTEM, user, max_tokens=2000)
    return {k: re.sub(r"^\s*\d+\.\s*", "", str(data.get(k, ""))).strip() for k in E.LEAVES}, usage, surface


# ------------------------------------------------------------------ graders: deterministic, provenance, verifier
def grade(notice: dict, surface: A.Surface) -> dict:
    """Deterministic checks against the truth at the deadline. Each check names what it tests."""
    text = E.leaves_text(notice)
    checks = {
        "four leaves present": all(str(notice.get(k, "")).strip() for k in E.LEAVES),
        f"at most {E.word_limit(surface)} words": len(E._WORD.findall(text)) <= E.word_limit(surface),
        "tracking id quoted": "1Z999AA10123456784" in text,
        "confirmed date Nov 14 present": "Nov 14" in text,
        "superseded Nov 12 absent": "Nov 12" not in text,
        "superseded Nov 13 absent": "Nov 13" not in text,
        "mis-posted Chicago absent": "Chicago" not in text,
        "old address 2B absent": "2B" not in text,
        "cancelled Access Point absent": "#118" not in text and "access point" not in text.lower(),
        "no internal code": not E._CODE.search(text),
    }
    return {"checks": checks, "score": round(sum(checks.values()) / len(checks), 2)}


def provenance(notice: dict, input_text: str) -> list[str]:
    """Numbers, dates and ids in the output that are not in the writer's input. Toothless against a transcript."""
    text = E.leaves_text(notice)
    out = set(re.findall(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\b", text)) | set(re.findall(r"\b1Z[0-9A-Z]{16}\b|\b\d{1,2}:\d{2}\b|#\d+", text))
    return sorted(x for x in out if x not in input_text)


def plant_stale(notice: dict) -> dict:
    """Mutation test: put a superseded value back into a real notice and see which harness's provenance test catches it."""
    bad = dict(notice)
    bad["eta"] = re.sub(r"Nov 14", "Nov 13", bad["eta"]) if "Nov 14" in bad["eta"] else bad["eta"] + " Delivery is expected on Nov 13."
    return bad


def verify_notice(notice: dict, surface: A.Surface, truth: str):
    """Judge-verifier against the verified record (the harness keeps every event; the model never re-reads it)."""
    rules = surface.rules()
    system = ("You are the verifier for the shipment exception desk. Check the notice against the rules and the verified "
              "record. Later corrections replace earlier statements. Report each violation with the rule id, the leaf "
              "(status, eta, action, contact) and the words at fault. Reply with JSON only.")
    user = ("Rules:\n" + "\n".join(f"[{rid}] {t}" for rid, t in rules.items()) + "\n\nVerified record, in order:\n" + truth
            + "\n\nNotice:\n" + "\n".join(f"{i + 1}. {l}: {notice[l]}" for i, l in enumerate(E.LEAVES))
            + '\n\nReply as {"findings": [{"rule_id": "...", "leaf": "...", "quote": "...", "explanation": "one sentence"}]}.')
    data, usage, _ = call_json(JUDGE, system, user, max_tokens=2000)
    findings = [f for f in data.get("findings", []) if isinstance(f, dict)]
    for f in findings:
        f["rule_exists"] = f.get("rule_id") in rules
        f["leaf_known"] = f.get("leaf") in E.LEAVES
    return findings, usage


def record_text(events: list[Event]) -> str:
    """The verified record the verifier reads: shipment events only, telemetry stripped."""
    return "\n".join(f"[{e.id}] {e.text.split(chr(10) + '--- BACKGROUND')[0]}" for e in events if e.kind != "noise")


# ------------------------------------------------------------------ targeted repair: one leaf, four gates
TRUTH = {   # the harness's verified record at the deadline, by the rule a finding cites
    "notice.tracking": "tracking_id: 1Z999AA10123456784 (UPS)",
    "notice.eta-confirmed": "eta: Nov 14, confirmed by the carrier (Nov 12 was an estimate; Nov 13 was superseded)",
    "notice.cause": "cause: none on file beyond the exception EXC-204",
    "notice.codes": "recipient: consumer; exception codes stay internal",
    "notice.length": "limit: see the compiled rule",
    "notice.leaves": "four leaves: status, eta, action, contact; one sentence each",
}


def fact_for(finding: dict) -> str:
    """The one verified fact the repair may use. It comes from the harness's record, not from the writer's input."""
    return TRUTH.get(finding.get("rule_id"), "")


def repair_leaf(notice: dict, leaf: str, finding: dict, surface: A.Surface, fact_line: str):
    """The writer sees one leaf, the rule it broke, and the one fact that matters. Nothing else."""
    rule = surface.rules().get(finding["rule_id"], "")
    user = (f"One leaf of a delivery notice failed verification.\n\nLeaf {leaf}: {notice[leaf]}\n"
            f"Rule [{finding['rule_id']}]: {rule}\nFinding: {finding.get('explanation', '')}\n"
            f"Relevant fact: {fact_line}\n\nRewrite leaf {leaf} only, one sentence. "
            f'Reply as {{"rule_id": "{finding["rule_id"]}", "replace": {{"{leaf}": "..."}}}}.')
    data, usage, _ = call_json(WRITER, E.WRITER_SYSTEM, user, max_tokens=800)
    return data, usage, user


def gate_repair(original: dict, proposal: dict, leaf: str, surface: A.Surface, input_text: str, fact_line: str = "") -> dict:
    """Gates 1-3 in code: the quoted rule exists; only the flagged leaf came back; no number or date beyond input + the one fact."""
    rules = surface.rules()
    gates = [{"gate": "quote: cited rule exists", "ok": proposal.get("rule_id") in rules, "detail": str(proposal.get("rule_id"))}]
    repl = proposal.get("replace") if isinstance(proposal.get("replace"), dict) else {}
    confined = set(repl) == {leaf} and isinstance(repl.get(leaf), str) and repl[leaf].strip()
    gates.append({"gate": f"index: only leaf '{leaf}' came back", "ok": bool(confined), "detail": f"touched {sorted(repl) or 'nothing'}"})
    patched = dict(original)
    if confined:
        patched[leaf] = repl[leaf].strip()
    new_numbers = provenance(patched, input_text + "\n" + fact_line)
    gates.append({"gate": "substance: no number or date beyond the input and the one supplied fact", "ok": not new_numbers,
                  "detail": str(new_numbers or "clean")})
    return {"gates": gates, "patched": patched if confined else dict(original), "ok": all(g["ok"] for g in gates),
            "untouched_identical": all(patched[k] == original[k] for k in original if k != leaf)}


def regenerate(notice: dict, finding: dict, surface: A.Surface, input_text: str):
    """The comparison: the whole notice goes back to the writer."""
    user = (surface.text + "\n\n## What you know about this shipment\n" + input_text
            + "\n\nThe previous notice failed verification:\n" + "\n".join(f"{l}: {notice[l]}" for l in E.LEAVES)
            + f"\nFinding: [{finding['rule_id']}] leaf {finding.get('leaf')}: {finding.get('explanation', '')}"
            + "\n\nRewrite the whole notice. Reply as {\"status\": \"...\", \"eta\": \"...\", \"action\": \"...\", \"contact\": \"...\"}.")
    data, usage, _ = call_json(WRITER, E.WRITER_SYSTEM, user, max_tokens=2000)
    return {k: re.sub(r"^\s*\d+\.\s*", "", str(data.get(k, ""))).strip() for k in E.LEAVES}, usage, user


def line_diff(before: dict, after: dict) -> list[dict]:
    return [{"leaf": k, "before": before.get(k), "after": after.get(k), "changed": before.get(k) != after.get(k)} for k in E.LEAVES]


def state_digest(state: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()[:12]


def prompt_tokens_of(run: dict) -> list[int]:
    return [max(1, c // 4) for c in run["prompt_chars"]]


def merge_demo() -> list[dict]:
    """The merge rule with no model: a correction, a null-delete, and three patches the schema refuses."""
    s0 = {**INITIAL_STATE, "eta": {"date": "Nov 12", "confirmed": False},
          "location": {"hub": "Chicago", "at": "Nov 11 15:10"}, "reroute": {"to": "UPS Access Point #118"}}
    out = []
    for title, patch in [("carrier confirms Nov 13", {"eta": {"date": "Nov 13", "confirmed": True}}),
                         ("mis-posted scan: location replaced", {"location": {"hub": "Indianapolis", "at": "Nov 11 14:52"}}),
                         ("redirect cancelled: null deletes", {"reroute": None}),
                         ("refused: eta as a bare string", {"eta": "Nov 13"}),
                         ("refused: a key the schema doesn't know", {"weather": "rain"}),
                         ("refused: hub by code, not city", {"location": {"hub": "HUB-SDF", "at": "Nov 11"}})]:
        cand = merge(s0, patch)
        errs = state_errors(cand)
        out.append({"title": title, "patch": patch, "errors": errs, "after": None if errs else cand})
    return out
