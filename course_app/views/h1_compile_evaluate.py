"""Hands-on 1 · Compile a skill, generate candidates, compare deterministic validation with model-based judging, read the trace."""

import pandas as pd
import streamlit as st

from core.ui import code_panel, highlight, page_header, quiz as ui_quiz, show_text, takeaway, task_card
from harness import artifacts as A
from harness import evaluate as E
from harness.models import JUDGE, WRITER, count_tokens
from harness.session import live, space, usage_line

page_header(1, "Compile a skill, generate candidates, evaluate", "The runtime compiler, then three checkers on the same outputs.",
            20, notebook_path=None)

task_card(
    task="Compile a skill for a predefined task, generate several candidate outputs, and compare deterministic validation with "
         "relative model-based judging; inspect how the selected skill version, compiled rules, model bindings, and evaluation "
         "results are captured in the execution trace.",
    todos=["**Compile**: pick what the harness should load for the task `carrier=ups · recipient=consumer · notice=delay`, read "
           "what the compiler refuses, and read the compiled surface, its manifest and its digest.",
           "**Generate several candidates**: three notices from the same surface (the exercise set, or three live ones).",
           "**Compare the checkers**: run the deterministic checks, the relative judge and the verifier on the same candidates and "
           "say where they disagree and why.",
           "**Inspect the trace**: find the skill version, the compiled rules, the model bindings and every verdict in the record."],
    why="A skill covers many variants of a task (two carriers, two recipient types, two kinds of notice). Sending the whole file "
        "makes the model resolve the variants on every call, and sometimes it resolves them wrong. The **runtime compiler** slices "
        "by the task's axes, refuses two owners for one section, and emits one flat surface with a digest, so the trace can say "
        "exactly which rules a run saw. Then: a count is right every time and blind to paraphrase; a relative judge says which "
        "candidate reads best and nothing about whether it may ship; a verifier that must quote a rule catches what both miss. "
        "Writer and judges are different models, so no author grades its own work.",
    remember="Settle everything the harness can decide before calling a model. Rank first, then verify. A finding is an address: rule id plus leaf.",
)

S = space("h1")
ARTS = A.load_all()
TASK, FACTS = E.TASK_AXES, E.TASK_FACTS
BAD = {"shortly": "implies timing", "day or two": "implies timing", "tomorrow": "implies timing", "soon": "implies timing",
       "EXC-204": "internal code", "Nov 13": "a date with no confirmed ETA", "Nov 12": "a date with no confirmed ETA"}
GOOD = ["1Z999AA10123456784", "has not yet confirmed", "has not confirmed"]


def quiz(key, question, options, correct, hints, explain) -> bool:
    return ui_quiz(S, key, question, options, correct, hints, explain)


def reset_eval():
    for k in list(S):
        if k in ("ranking", "pool", "verdicts") or k.startswith(("ans_split", "ans_why", "ans_ship", "hint_split", "hint_why", "hint_ship")):
            S.pop(k)


# ------------------------------------------------------------------ 1 · compile
st.markdown("### 1 · Compile the skill for the task")
st.markdown(f"Task: **{' · '.join(f'{k}={v}' for k, v in TASK.items())}**. The index shows metadata only; no skill body is read "
            "until one is selected.")
st.dataframe(pd.DataFrame(A.catalogue(ARTS))[["kind", "name", "version", "status", "digest", "axes", "description", "always_loaded"]],
             hide_index=True, width="stretch")
LOAD = ["delivery-notice 2.1.0 (active), sliced to the task axes", "delivery-notice 1.4.0 (deprecated)",
        "delivery-notice 2.1.0 plus the warm-voice persona", "Everything on the index, unsliced"]
sel_ok = quiz("load", "1a · What should the harness load for this task?", LOAD, LOAD[0],
              ["Only one skill covers delivery notices at an active version; the persona also claims a section that skill owns.",
               "The first option: the active delivery-notice skill, sliced to carrier=ups, recipient=consumer, notice=delay."],
              "Selection resolves the task to one skill at one version; compilation keeps only the sections whose axis matches.")
with st.expander("What the other choices do (the compiler's own messages)"):
    for label, names, pool_ in [("1.4.0 (deprecated)", ["delivery-notice"], [a for a in ARTS if not (a.name == "delivery-notice" and a.version == "2.1.0")]),
                                ("2.1.0 + warm-voice", ["delivery-notice", "warm-voice"], ARTS)]:
        try:
            A.load_for_task(pool_, names); msg = "accepted"
        except A.CompileError as e:
            msg = str(e)
        st.markdown(f"- **{label}** → `{msg}`")
    ev = A.everything_surface(ARTS, FACTS)
    st.markdown(f"- **Everything, unsliced** → compiles, {count_tokens(ev.text):,} tokens: both carriers, both recipient types, both "
                "notice kinds, the deprecated edition and a persona that contradicts the skill's style section. The model has to pick.")
if not sel_ok:
    st.stop()
selection = A.load_for_task(ARTS, ["delivery-notice"])
surface = A.compile_surface(selection, TASK, FACTS)
everything = A.everything_surface(ARTS, FACTS)
S["surface"], S["selection"] = surface, selection
c = st.columns(4)
c[0].metric("Compiled surface", f"{count_tokens(surface.text):,} tokens")
c[1].metric("Everything, unsliced", f"{count_tokens(everything.text):,} tokens")
c[2].metric("Sections kept", len(surface.manifest["sections"]))
c[3].metric("Surface digest", surface.digest)
l, r = st.columns([1.3, 1])
with l:
    st.markdown("**Compiled surface** (what the writer gets)")
    st.code(surface.text, language="markdown", height=340)
with r:
    st.markdown("**Manifest** (what the trace keeps)")
    st.dataframe(pd.DataFrame(surface.manifest["sections"]), hide_index=True, width="stretch", height=200)
    st.markdown("**Rules the verifier may quote**")
    st.code("\n".join(surface.rules()), language="text")
dig_ok = quiz("digest", "1b · Tomorrow the same skill version runs for carrier=dhl. Which identifier changes?",
              ["The artifact version", "The artifact digest", "The surface digest", "None of them"], "The surface digest",
              ["The skill file itself is untouched; a human sets the version and the artifact digest is the file's hash.",
               "The surface digest: it hashes the assembled text, and the DHL slice is different text."],
              "Version: a human assigns it. Artifact digest: the file's contents, so a silent edit shows. Surface digest: the "
              "assembled text for one task. The trace records all three.")
code_panel("the runtime compiler", [A.slice_section, A.compile_surface])
if not dig_ok:
    st.stop()

# ------------------------------------------------------------------ 2 · candidates
st.markdown("### 2 · Generate several candidates")
st.markdown(f"Three notices for the same facts. The **exercise set** is fixed so the checkers will disagree; the live set is written by "
            f"`{WRITER}` from the compiled surface. Red marks words that will matter; green marks the facts.")
b1, b2 = st.columns(2)
if b1.button("Use the exercise set", type="primary", disabled=S.get("cands", {}).get("source") == "rehearsal"):
    S["cands"] = {"items": dict(E.REHEARSAL), "source": "rehearsal", "usage": None}
    reset_eval()
if b2.button("Generate 3 live candidates instead (1 call)", icon=":material/bolt:"):
    out = live(1, "Writing three candidates…", E.generate_candidates, surface)
    if out:
        S["cands"] = {"items": out[0], "source": "live", "usage": out[1].as_dict()}
        reset_eval()
cands = S.get("cands")
if not cands:
    st.stop()
cols = st.columns(3)
for col, (k, c_) in zip(cols, cands["items"].items()):
    with col:
        st.markdown(f"**Candidate {k}**")
        show_text(highlight("\n".join(f"{i + 1}. {l}: {c_[l]}" for i, l in enumerate(E.LEAVES)), BAD, GOOD), 190)
if cands["usage"]:
    st.caption("Writer call: " + usage_line(cands["usage"]))

# ------------------------------------------------------------------ 3 · three checkers
st.markdown("### 3 · Three checkers on the same candidates")
st.markdown("""
| Checker | Asks | Blind to | Runs |
|---|---|---|---|
| Deterministic | too many words? id quoted? a date where none is confirmed? an internal code? | paraphrase | Python, free |
| Relative judge | which candidate reads best? | whether any may ship | `""" + JUDGE + """` |
| Verifier | does leaf *eta* break `notice.eta-confirmed`? | rules it was not given | `""" + JUDGE + """`, must quote the rule |
""")
det = {k: E.deterministic_problems(c_, surface, FACTS, TASK) for k, c_ in cands["items"].items()}
eligible = [k for k, p in det.items() if not p]
ranking, verdicts, pool = S.get("ranking"), S.get("verdicts", {}), S.get("pool")
rank_pos = {r_["id"]: i + 1 for i, r_ in enumerate(ranking or [])}
rows = []
for k, c_ in cands["items"].items():
    v = verdicts.get(k)
    rows.append({"": k, "deterministic (Python)": "pass" if not det[k] else "; ".join(f"{p['rule']}@{p['leaf']}" for p in det[k]),
                 "relative judge": f"#{rank_pos[k]}" if k in rank_pos else ("not eligible" if k not in eligible else "·"),
                 "verifier": "·" if not v else ("pass" if v["verdict"] == "pass" else
                                                 "; ".join(f"{f['rule_id']}@{f['leaf']}" for f in v["findings"] if f.get("rule_exists") and f.get("leaf_known")))})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
with st.expander("Deterministic details"):
    for k, p in det.items():
        st.markdown(f"**{k}** · " + ("no problems" if not p else "; ".join(f"`{x['rule']}` ({x['leaf']}): {x['detail']}" for x in p)))
    st.caption(f"The word limit ({E.word_limit(surface)}) is read from the compiled rule, not kept as a copy in the validator.")
e1, e2, e3 = st.columns(3)
if eligible and e1.button(f"Rank the {len(eligible)} eligible (1 call)", type="primary", icon=":material/bolt:", disabled=bool(ranking)):
    out = live(1, "Ranking…", E.rank, {k: cands["items"][k] for k in eligible}, FACTS)
    if out:
        S["ranking"], S["ranking_usage"] = out[0], out[1].as_dict(); st.rerun()
if ranking and e2.button(f"Verify the {len(eligible)} eligible ({len(eligible)} calls)", type="primary", icon=":material/bolt:", disabled=bool(verdicts)):
    def verify_all():
        return {k: E.verify(cands["items"][k], surface, FACTS) for k in eligible}
    out = live(len(eligible), "Verifying each eligible candidate against the compiled rules…", verify_all)
    if out:
        S["verdicts"] = {k: {**v, "usage": u.as_dict()} for k, (v, u) in out.items()}; st.rerun()
if ranking and len(eligible) > 1 and e3.button("Optional: judge pool (3 calls)", disabled=bool(pool)):
    out = live(3, "Three judges ranking independently…", E.pool_rank, {k: cands["items"][k] for k in eligible}, FACTS)
    if out:
        S["pool"] = out[0]; st.rerun()
if not eligible:
    st.warning("No candidate passed the deterministic checks, so there is nothing to rank. Load the exercise set or regenerate.")
if ranking:
    st.markdown("**Relative judge** · " + " > ".join(r_["id"] for r_ in ranking) + " · " + usage_line(S["ranking_usage"]))
    for r_ in ranking:
        st.caption(f"{r_['id']}: {r_['reason']}")
if pool:
    st.markdown("**Judge pool** · " + " > ".join(pool["aggregate"]) + (" · unanimous" if pool["unanimous"] else " · judges disagree"))
    st.dataframe(pd.DataFrame(pool["votes"])[["judge", "model", "lens", "ranking"]], hide_index=True, width="stretch")
for k, v in verdicts.items():
    cited = [f for f in v["findings"] if f.get("rule_exists") and f.get("leaf_known")]
    if v["verdict"] == "pass":
        st.success(f"Verifier on {k}: pass")
    else:
        st.error(f"Verifier on {k}: " + "; ".join(f"[{f['rule_id']}] leaf {f['leaf']}: “{f.get('quote', '')}” — {f.get('explanation', '')}" for f in cited))
code_panel("deterministic checks, relative judge, judge-verifier", [E.deterministic_problems, E.rank, E.verify])
if not (ranking and verdicts):
    st.stop()

# The exercise questions, answered from the actual results.
split = [k for k in eligible if verdicts.get(k, {}).get("verdict") == "fail"]
accepted = next((k for k in [r_["id"] for r_ in ranking] if verdicts.get(k, {}).get("verdict") == "pass"), None)
S["accepted"] = accepted
if split:
    k0 = split[0]
    f0 = next(f for f in verdicts[k0]["findings"] if f.get("rule_exists") and f.get("leaf_known"))
    split_ok = quiz("split", "3a · Which candidate passed the deterministic checks, was ranked by the judge, and was then rejected by the verifier?",
                    list(cands["items"]), k0,
                    ["Look down the table: a row that says pass in the first column and names a rule in the last.",
                     f"Candidate {k0}: the verifier cites {f0['rule_id']} on leaf {f0['leaf']}."],
                    f"The deterministic check saw no forbidden string; the judge ranked it #{rank_pos.get(k0, '?')} on how it reads; the verifier "
                    f"read the rule and quoted “{f0.get('quote', '')}”.")
    if not split_ok:
        st.stop()
    WHY = ["The deterministic check was not run on it", "The deterministic check matches strings and counts; it cannot see a paraphrase",
           "The rule was not in the compiled surface", "The judge overruled it"]
    why_ok = quiz("why", "3b · Why did the deterministic check let it through?", WHY, WHY[1],
                  ["Compare the red words in the candidate with what the deterministic check looks for (dates, codes, the word limit, the id).",
                   "The second option: counting and matching are right every time for what they can see, and blind to meaning."],
                  "Match the checker to the question: countable rules go to code; rules about meaning go to a verifier that must quote the rule.")
    if not why_ok:
        st.stop()
else:
    st.info("In this set no candidate split the checkers (every eligible one passed the verifier). Load the exercise set to see the split.")
SHIP = [f"Candidate {k}" for k in cands["items"]] + ["None"]
ship_ok = quiz("ship", "3c · Which candidate ships?", SHIP, f"Candidate {accepted}" if accepted else "None",
               ["Shipping needs a pass from the deterministic checks and from the verifier; the ranking only orders the survivors.",
                f"{'Candidate ' + accepted if accepted else 'None'}: the first one in ranking order that the verifier passed."],
               "Rank first, then verify. A relative score has no meaning outside its group and never gates release.")
if not ship_ok:
    st.stop()
takeaway("Three checkers, three different answers on the same text. Code is exact and cheap; the judge knows which reads best; only the "
         "verifier read the rules, and because it must cite a rule id and a leaf, its finding is checkable and repairable.")

# ------------------------------------------------------------------ 4 · the trace
st.markdown("### 4 · Inspect the execution trace")
tr = E.trace_record(selection, surface, cands["items"], cands["source"], det, ranking, pool, verdicts, accepted)
S["trace"] = tr
c1, c2 = st.columns([1, 1.2])
with c1:
    st.markdown("\n".join([
        "- **Skill version**: " + ", ".join(f"{a['ref']} ({a['digest']})" for a in tr["skill"]["artifacts"] if a["kind"] == "skill"),
        "- **Always loaded**: " + ", ".join(f"{a['ref']} ({a['digest']})" for a in tr["skill"]["artifacts"] if a["kind"] != "skill"),
        f"- **Axes**: {tr['skill']['axes']}",
        f"- **Compiled rules**: {', '.join(tr['compiled_surface']['rules'])} · surface digest `{tr['compiled_surface']['digest']}`",
        f"- **Model bindings**: writer `{tr['model_bindings']['writer'] or 'exercise set'}`, judge `{tr['model_bindings']['judge']}`"
        + (f", pool {tr['model_bindings']['pool']}" if tr["model_bindings"]["pool"] else ""),
        f"- **Deterministic**: {tr['evaluation']['deterministic']}",
        f"- **Relative**: {tr['evaluation']['relative']}",
        f"- **Verifier**: {tr['evaluation']['verifier']}",
        f"- **Accepted**: {tr['accepted']}",
    ]))
with c2:
    st.json(tr, expanded=2)
TRACE_Q = ["skill.artifacts[].version", "skill.artifacts[].digest", "model_bindings.judge", "evaluation.relative"]
quiz("trace", "4a · Someone edits the ETA rule in the skill file next week without bumping the version. Which trace field shows that "
     "this run used different text?", TRACE_Q, TRACE_Q[1],
     ["The version is assigned by a human and was not bumped; look for the field computed from the file's contents.",
      "skill.artifacts[].digest (and compiled_surface.digest with it): both are hashes of the text this run actually saw."],
     "That is why the trace keeps hashes, not only versions: a changed file shows even when nobody updates its declared version.")
code_panel("the trace record", [E.trace_record])
with st.expander("Numbers from the course material"):
    st.markdown("""
- Compiled surface vs everything loaded in the book's example: 788 vs 1,177 tokens, 33% fewer instruction tokens per call.
- A relative score: the same text scored 0.35 among three weak siblings and 0.92 against its own retry. A fixed threshold on it fires at random.
- Hashing every model-facing prompt shows a rule edit's blast radius before deployment: one rule changed 5 prompts, another 24.
""")
