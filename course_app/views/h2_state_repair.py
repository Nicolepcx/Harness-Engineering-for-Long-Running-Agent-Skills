"""Hands-on 2 · Process a stream with delayed corrections, evaluate the deliverable, repair one failed section."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from skill_state import build_prompt, merge, validate

from core import llm
from core.ui import code_panel, page_header, takeaway, task_card
from core.ui import highlight as ui_highlight, quiz as ui_quiz, show_text as ui_show_text
from harness import artifacts as A
from harness import evaluate as E
from harness import stream as S
from harness.models import JUDGE, count_tokens
from harness.session import live, space

page_header(2, "State, delayed corrections, and repairing one section",
            "One shipment, three ways to carry its history, one notice, one repair.", 20, notebook_path=None)

task_card(
    task="Process a stream containing updates and delayed corrections, evaluate the resulting deliverable, and repair one "
         "failed section without regenerating the complete output; compare context growth, retained information, evaluation "
         "results, retry scope, and cost.",
    todos=["**Process the stream**: eight observations about one UPS shipment, two of them delayed corrections. One click runs "
           "the explicit-state tracker; the transcript and window are built from the same observations.",
           "**See what each harness hands the writer**: which facts survived, which stale values are still there, how many tokens.",
           "**Write and verify the three notices** with the identical writer; read the findings per leaf.",
           "**Repair one failed section** (the exercise): say which leaf fails and which rule it breaks, choose what the repair "
           "prompt may contain, run the targeted repair through the four gates, then compare with regenerating the whole notice.",
           "**Compare** context growth, retained information, evaluation results, retry scope and cost on one scorecard."],
    why="A long-running skill sees updates that revoke earlier ones. Replaying the transcript grows the prompt every step and "
        "leaves the revoked fact next to its correction; a fixed window forgets. Explicit state `(P, Σ_t, O_t)` with validated "
        "patches keeps the prompt flat and the facts current. When the deliverable still has one bad line, regenerating "
        "everything costs the full prompt again and may change lines that were right. A **targeted repair** sends the model "
        "only the failed section, the rule it broke and the one fact that matters, then gates the result before it lands.",
    remember="A finding is an address: rule id plus leaf. Repair the leaf, not the notice, and let the gates decide.",
)

H = space("h2")
EVENTS = S.make_stream()
T = len(EVENTS)
DATA = Path(__file__).resolve().parent.parent / "data"
COLORS = {"transcript": "#c9862b", "window": "#5aa9e6", "state": "#1fa37a"}
LABEL = {"transcript": "Full transcript", "window": "Fixed window", "state": "Explicit state"}
SURFACE = A.compile_surface(A.load_for_task(A.load_all(), ["delivery-notice"]), {"carrier": "ups", "recipient": "consumer", "notice": "delay"}, {})
RULES = SURFACE.rules()


STALE_TERMS = {"Nov 12": "superseded estimate", "Nov 13": "superseded date", "Chicago": "mis-posted scan", "Apt 2B": "old address",
               "2B": "old address", "#118": "cancelled redirect", "Access Point": "cancelled redirect"}
CURRENT_TERMS = ["Nov 14", "Indianapolis", "Apt 4B", "1Z999AA10123456784"]


def highlight(text: str) -> str:
    return ui_highlight(text, STALE_TERMS, CURRENT_TERMS)


def show_text(text: str, height: int = 200) -> None:
    ui_show_text(highlight(text), height)


def quiz(key, question, options, correct, hints, explain) -> bool:
    return ui_quiz(H, key, question, options, correct, hints, explain)


# ------------------------------------------------------------------ 1 · process the stream
st.markdown("### 1 · Process the stream")
st.dataframe(pd.DataFrame([{"id": e.id, "kind": e.kind, "observation": e.text.split("\n---")[0], "what a correct tracker does": e.note}
                           for e in EVENTS]), hide_index=True, width="stretch", height=320)
st.caption("Every observation arrives with four lines of background telemetry (other parcels, sensors, chat), as in the paper's "
           "noise setting. Open one below to see what the tracker receives.")
with st.expander("One observation as received · the state schema Σ · the merge rule"):
    st.code(EVENTS[4].text, language="text")
    l, r = st.columns(2)
    l.code(json.dumps(S.STATE_SCHEMA, indent=1), language="json", height=280)
    r.code(S.STATE_SPEC.strip(), language="markdown", height=280)
    st.dataframe(pd.DataFrame([{"patch": d["title"], "ΔΣ": json.dumps(d["patch"]), "result": "accepted" if not d["errors"] else "refused: " + "; ".join(d["errors"])}
                               for d in S.merge_demo()]), hide_index=True, width="stretch")
    code_panel("merge, validate, build_prompt (skill_state, used as is)", [merge, validate, build_prompt])

state_run = H.get("state_run")
b1, b2 = st.columns(2)
if b1.button(f"Process the stream with explicit state ({T} live calls)", type="primary", icon=":material/bolt:"):
    out = live(3 * T, "Tracking the shift: (P, Σ, O) → (reasoning, ΔΣ, action) at each step…", S.run_state, EVENTS)
    if out:
        llm.release_calls(3 * T - out["usage"]["calls"])
        H.clear(); H["state_run"], H["source"] = out, "live"
        st.rerun()
if (DATA / "reference_runs.json").exists() and b2.button("Use a recorded run instead"):
    ref = json.loads((DATA / "reference_runs.json").read_text())
    H.clear(); H["state_run"], H["source"] = ref["state_run"], f"recorded {ref['recorded_at']}"
    st.rerun()
if not state_run:
    st.stop()
budget = S.window_budget(state_run)
st.caption(f"{H['source']} · {state_run['usage']['calls']} calls · {state_run['rejected_patches']} refused patches · notice action at "
           f"{', '.join(state_run['wrote_at']) or 'never'} · ${state_run['usage']['cost_usd']:.4f}")
c1, c2 = st.columns([1, 1.2])
with c1:
    st.markdown("**Σ at the deadline**")
    st.json(state_run["final_state"], expanded=True)
with c2:
    growth = {"transcript": S.projected_growth(EVENTS), "window": S.projected_growth(EVENTS, budget), "state": state_run["prompt_chars"]}
    fig = go.Figure()
    for name, ys in growth.items():
        fig.add_trace(go.Scatter(x=list(range(1, len(ys) + 1)), y=ys, mode="lines+markers", name=LABEL[name],
                                 line=dict(color=COLORS[name], width=3, dash=None if name == "state" else "dot")))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=30, b=10), xaxis_title="step", yaxis_title="prompt characters",
                      title=dict(text="Context growth · prompt size per step", font=dict(size=14)), legend=dict(orientation="h", y=-0.3))
    st.plotly_chart(fig, width="stretch")
    st.caption("Transcript and window prompts are built from the same observations (dotted: computed, not sent); the state "
               "prompts were sent.")
cum = {"transcript": sum(count_tokens(S.react_prompt(EVENTS, i)) for i in range(T)),
       "window": sum(count_tokens(S.window_prompt(EVENTS, i, budget)) for i in range(T)),
       "state": state_run["usage"]["prompt_tokens"]}
with st.expander("The three prompts side by side at any step (the paper's Appendix A)"):
    t = st.slider("Step t", 0, T - 1, T - 1, key="h2_t")
    sigma_t = S.INITIAL_STATE if t == 0 else state_run["steps"][t - 1]["state"]
    cols = st.columns(3)
    for col, (name, p_) in zip(cols, {"transcript": S.react_prompt(EVENTS, t), "window": S.window_prompt(EVENTS, t, budget),
                                      "state": S.state_prompt(EVENTS, t, sigma_t)}.items()):
        with col:
            st.markdown(f"**{LABEL[name]}** · {count_tokens(p_):,} tokens")
            st.code(p_, language="text", height=320)
with st.expander("Σ after every step, and every refused patch"):
    for s_ in state_run["steps"]:
        n_att = len(s_["attempts"]) if isinstance(s_["attempts"], list) else s_["attempts"]
        st.markdown(f"**{s_['event']}** → {s_['action']}" + (f" · {n_att} attempts" if n_att > 1 else "") + f"  \n`{json.dumps(s_['state'])}`")
    for rj in state_run.get("rejections", []):
        st.caption("refused: " + rj)
if (DATA / "reference_long.json").exists():
    L = json.loads((DATA / "reference_long.json").read_text())
    with st.expander(f"The same shift stretched to {L['horizon']} steps, all three trackers run live once (recorded {L['recorded_at']})"):
        fig2 = go.Figure()
        for name, run in L["runs"].items():
            fig2.add_trace(go.Scatter(x=list(range(1, len(run["prompt_chars"]) + 1)), y=run["prompt_chars"], mode="lines",
                                      name=LABEL[name], line=dict(color=COLORS[name], width=3)))
        fig2.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="step", yaxis_title="prompt characters", legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig2, width="stretch")
        st.dataframe(pd.DataFrame({LABEL[n]: {"max prompt (chars)": max(r_["prompt_chars"]), "prompt tokens over the shift": r_["usage"]["prompt_tokens"],
                                               "tracker cost $": round(r_["usage"]["cost_usd"], 4), "facts in writer input (of 5)": r_["facts"],
                                               "traps in writer input (of 5)": r_["traps"]} for n, r_ in L["runs"].items()}).astype(str), width="stretch")
code_panel("the state tracker and the prompt builders", [S.run_state, S.react_prompt, S.window_prompt, S.state_prompt])

# ------------------------------------------------------------------ 2 · what the writer gets
st.markdown("### 2 · What each harness hands the writer")
inputs = {"transcript": S.log_input(EVENTS), "window": S.log_input(EVENTS, budget), "state": S.writer_input(state_run, EVENTS)}
H["inputs"] = inputs
cols = st.columns(3)
for col, name in zip(cols, inputs):
    inp, ret = inputs[name], S.retained(inputs[name])
    with col:
        st.markdown(f"**{LABEL[name]}** · {count_tokens(inp):,} tokens · facts {sum(ret['facts'].values())}/5 · stale values {sum(ret['traps'].values())}/5")
        show_text(inp, 220)
tab = pd.DataFrame({LABEL[n]: {**{f"fact: {v[0]}": "✓" if S.retained(inputs[n])["facts"][k] else "✗" for k, v in S.FACTS_REQUIRED.items()},
                               **{f"stale: {v[0]}": "present" if S.retained(inputs[n])["traps"][k] else "·" for k, v in S.TRAPS.items()}} for n in inputs})
st.dataframe(tab, width="stretch")
st.caption("Measured before any writer runs. The transcript has everything, current and stale; the window has forgotten the early "
           "facts; the state has only what is true now.")

# ------------------------------------------------------------------ 3 · write and verify
st.markdown("### 3 · Write the three notices, then verify them")
if st.button("Write and verify (6 live calls)", type="primary", icon=":material/bolt:", disabled=bool(H.get("deliverables"))):
    def write_verify():
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {n: ex.submit(S.write_notice, inputs[n]) for n in inputs}
            out = {}
            for n, f in futs.items():
                notice, usage, surface = f.result()
                out[n] = {"notice": notice, "usage": usage.as_dict(), "surface_digest": surface.digest, "grade": S.grade(notice, surface),
                          "provenance": S.provenance(notice, inputs[n]), "planted_caught": S.provenance(S.plant_stale(notice), inputs[n]),
                          "state_digest": S.state_digest(state_run["final_state"]) if n == "state" else None}
            vf = {n: ex.submit(S.verify_notice, out[n]["notice"], SURFACE, S.record_text(EVENTS)) for n in inputs}
            for n, f in vf.items():
                findings, usage = f.result()
                out[n]["findings"], out[n]["verify_usage"] = findings, usage.as_dict()
            return out
    out = live(6, "Writing three notices and verifying them…", write_verify)
    if out:
        H["deliverables"] = out
        for k in list(H):
            if k.startswith("ans_") or k in ("repair", "regen"):
                H.pop(k)
dl = H.get("deliverables")
if not dl:
    st.stop()
cols = st.columns(3)
for col, name in zip(cols, inputs):
    d = dl[name]
    cited = [f for f in d["findings"] if f.get("rule_exists") and f.get("leaf_known")]
    with col:
        st.markdown(f"**{LABEL[name]}** · deterministic score {d['grade']['score']} · verifier findings {len(cited)}")
        for i, leaf in enumerate(E.LEAVES):
            flag = " ⛔" if any(f["leaf"] == leaf for f in cited) else ""
            st.markdown(f"{i + 1}. *{leaf}*: {highlight(d['notice'][leaf])}{flag}", unsafe_allow_html=True)
        failed = [k for k, v in d["grade"]["checks"].items() if not v]
        if failed:
            st.caption("deterministic: ✗ " + "; ✗ ".join(failed))
        for f in cited:
            st.caption(f"[{f['rule_id']}] {f['leaf']}: {f.get('explanation', '')}")
st.caption(f"Verifier: `{JUDGE}`, against the verified record. A finding must name a rule that is in the surface and a leaf; "
           "anything else is dropped.")
code_panel("writer, deterministic grade, provenance, verifier", [S.write_notice, S.grade, S.provenance, S.verify_notice])

# ------------------------------------------------------------------ 4 · the exercise: repair one failed section
st.markdown("### 4 · Repair one failed section without regenerating the complete output")
# The notice under repair: a live finding about content (a stale date, place or reference) if the verifier produced one;
# format findings (leaf count, length) are the deterministic checks' business. Otherwise a superseded date is planted, and said so.
CONTENT_RULES = ("notice.eta-confirmed", "notice.tracking", "notice.cause", "notice.codes")
target = None
for n in inputs:
    for f in dl[n].get("findings", []):
        if f.get("rule_exists") and f.get("leaf_known") and f["rule_id"] in CONTENT_RULES:
            target = (n, dl[n]["notice"], f, f"live finding on the {LABEL[n].lower()} notice"); break
    if target:
        break
if target is None:
    target = ("state", S.plant_stale(dl["state"]["notice"]),
              {"rule_id": "notice.eta-confirmed", "leaf": "eta", "quote": "Nov 13",
               "explanation": "States a date the carrier later superseded; the confirmed date is Nov 14."},
              "no live content finding, so a superseded date was planted in the explicit-state notice: the defect a stale transcript produces")
tn, tnotice, tfinding, tlabel = target
H["target"] = {"harness": tn, "leaf": tfinding["leaf"], "rule_id": tfinding["rule_id"], "label": tlabel}
st.markdown(f"This is the notice under repair ({tlabel}). Four numbered leaves; one of them is wrong.")
show_text("\n".join(f"{i + 1}. {l}: {tnotice[l]}" for i, l in enumerate(E.LEAVES)), 160)
st.caption("Red: a value a later observation superseded. Green: a current fact.")
with st.expander("The verified facts at the deadline, and the rules"):
    st.markdown("\n".join(f"- {v[0]}" for v in S.FACTS_REQUIRED.values()))
    st.code("\n".join(f"[{k}] {v}" for k, v in RULES.items()), language="text")

leaf_ok = quiz("leaf", "4a · Which leaf fails?", [f"{i + 1}. {l}" for i, l in enumerate(E.LEAVES)],
               f"{E.LEAVES.index(tfinding['leaf']) + 1}. {tfinding['leaf']}",
               ["Compare each leaf against the verified facts above; look for a date, place or reference that a later observation superseded (stale values are marked red).",
                f"It is leaf {E.LEAVES.index(tfinding['leaf']) + 1}, {tfinding['leaf']}: “{tfinding.get('quote', tnotice[tfinding['leaf']])}”."],
               tfinding.get("explanation", ""))
if not leaf_ok:
    st.stop()
rule_ok = quiz("rule", "4b · Which compiled rule does it break?", list(RULES), tfinding["rule_id"],
               ["Open the rules above; the one you want is about what that leaf may state, not about length or format.",
                f"It is `{tfinding['rule_id']}`: {RULES[tfinding['rule_id']][:140]}…"],
               "A finding is an address: this rule id plus that leaf. That is all the repair needs to be told.")
if not rule_ok:
    st.stop()
PROMPT_OPTIONS = ["The whole notice, all the rules, and the full transcript",
                  "The whole notice and all the rules",
                  "Only the failed leaf, the rule it broke, and the one verified fact that fixes it",
                  "Only the failed leaf"]
prompt_ok = quiz("prompt", "4c · What should the targeted repair prompt contain?", PROMPT_OPTIONS, PROMPT_OPTIONS[2],
                 ["The repair should be able to change only the failed leaf, so the other leaves must not be sent; but the model needs the rule and the current fact.",
                  "It is the third option: only the failed leaf, the rule it broke, and the one verified fact."],
                 "The other three leaves are not sent, so they cannot change: the retry scope is one leaf by construction.")
if not prompt_ok:
    st.stop()
fact_line = S.fact_for(tfinding)
TARGET_KEY = (tfinding["rule_id"], tfinding["leaf"])
BEFORE = {(f["rule_id"], f["leaf"]) for f in dl[tn].get("findings", []) if f.get("rule_exists") and f.get("leaf_known")} | {TARGET_KEY}


def recheck_gate(findings):
    """Gate 4: the targeted finding is gone and nothing new appeared."""
    after = {(f["rule_id"], f["leaf"]) for f in findings if f.get("rule_exists") and f.get("leaf_known")}
    new = after - BEFORE
    ok = TARGET_KEY not in after and not new
    detail = "cleared, nothing new" if ok else "; ".join(x for x in ["target still present" if TARGET_KEY in after else "",
                                                                       "new: " + ", ".join(f"{r}@{l}" for r, l in new) if new else ""] if x)
    return {"gate": "re-check: finding cleared, none added", "ok": ok, "detail": detail}, after


st.markdown(f"**4d · Run the targeted repair.** The prompt will contain: leaf *{tfinding['leaf']}*, rule `{tfinding['rule_id']}`, "
            f"and the fact `{fact_line}`. Then four gates decide whether it lands.")
if st.button("Run the targeted repair (2 live calls: repair + re-check)", type="primary", icon=":material/bolt:", disabled=bool(H.get("repair"))):
    def do_repair():
        proposal, u1, prompt = S.repair_leaf(tnotice, tfinding["leaf"], tfinding, SURFACE, fact_line)
        gated = S.gate_repair(tnotice, proposal, tfinding["leaf"], SURFACE, inputs[tn], fact_line)
        gates, recheck = list(gated["gates"]), None
        if gated["ok"]:
            findings, u2 = S.verify_notice(gated["patched"], SURFACE, S.record_text(EVENTS))
            g4, _ = recheck_gate(findings); gates.append(g4)
            recheck = {"findings": findings, "usage": u2.as_dict()}
        accepted = all(g["ok"] for g in gates)
        return {"proposal": proposal, "prompt": prompt, "usage": u1.as_dict(), "gates": gates, "accepted": accepted,
                "patched": gated["patched"] if accepted else dict(tnotice), "recheck": recheck}
    out = live(2, "Repairing one leaf…", do_repair)
    if out:
        H["repair"] = out
rep = H.get("repair")
if not rep:
    st.stop()
st.markdown(f"**Result: {'accepted' if rep['accepted'] else 'rejected, the original stands'}** · the writer saw "
            f"{rep['usage']['prompt_tokens']:,} tokens")
for g in rep["gates"]:
    st.markdown(f"{'✅' if g['ok'] else '❌'} {g['gate']} · {g['detail']}")
for l in E.LEAVES:
    if l == tfinding["leaf"]:
        st.markdown((f"**{l}** · before: <s>{highlight(tnotice[l])}</s>  \n**{l}** · after: **{highlight(rep['patched'][l])}**") if rep["accepted"]
                    else f"**{l}** · unchanged, repair rejected: {highlight(tnotice[l])}", unsafe_allow_html=True)
    else:
        st.markdown(f"{l} · 🔒 not sent, byte-identical: {highlight(tnotice[l])}", unsafe_allow_html=True)
with st.expander("The repair prompt, in full"):
    st.code(rep["prompt"], language="text")
quiz("gate", "4e · Which gate guarantees the other three leaves did not change?",
     ["quote: the cited rule exists", "index: only the flagged leaf came back", "substance: no number beyond input + fact", "re-check: finding cleared, none added"],
     "index: only the flagged leaf came back",
     ["One of the three code gates looks at which keys the model's reply contains.",
      "It is the index gate: a reply that touches another leaf is refused before it is applied."],
     "And because the other leaves were never sent, the model could not have rewritten them in the first place.")

st.markdown("**4f · Compare with regenerating the whole notice.**")
if st.button("Regenerate the whole notice for comparison (2 live calls)", icon=":material/bolt:", disabled=bool(H.get("regen"))):
    def do_regen():
        notice, u1, prompt = S.regenerate(tnotice, tfinding, SURFACE, inputs[tn])
        findings, u2 = S.verify_notice(notice, SURFACE, S.record_text(EVENTS))
        return {"notice": notice, "prompt": prompt, "usage": u1.as_dict(), "diff": S.line_diff(tnotice, notice), "recheck": {"findings": findings, "usage": u2.as_dict()}}
    out = live(2, "Regenerating the whole notice…", do_regen)
    if out:
        H["regen"] = out
regen = H.get("regen")
if regen:
    rg4, after = recheck_gate(regen["recheck"]["findings"])
    changed = [d["leaf"] for d in regen["diff"] if d["changed"]]
    for d in regen["diff"]:
        st.markdown((f"**{d['leaf']}** · ✏️ changed  \nbefore: <s>{highlight(d['before'])}</s>  \nafter: {highlight(d['after'])}") if d["changed"]
                    else f"{d['leaf']} · same", unsafe_allow_html=True)
    comp = pd.DataFrame({
        "Targeted repair": {"retry scope": "1 leaf", "leaves the model could change": 1, "leaves actually changed": 1 if rep["accepted"] else 0,
                            "writer prompt tokens": rep["usage"]["prompt_tokens"],
                            "cost incl. re-check $": round((rep["usage"]["cost_usd"] or 0) + ((rep["recheck"] or {}).get("usage", {}).get("cost_usd") or 0), 5),
                            "gates": f"{sum(g['ok'] for g in rep['gates'])} of 4 passed", "result": "accepted" if rep["accepted"] else "rejected, original kept"},
        "Full regeneration": {"retry scope": f"{len(E.LEAVES)} leaves", "leaves the model could change": len(E.LEAVES), "leaves actually changed": len(changed),
                              "writer prompt tokens": regen["usage"]["prompt_tokens"],
                              "cost incl. re-check $": round((regen["usage"]["cost_usd"] or 0) + (regen["recheck"]["usage"]["cost_usd"] or 0), 5),
                              "gates": "none", "result": rg4["detail"]}}).astype(str)
    st.dataframe(comp, width="stretch")
    ratio = regen["usage"]["prompt_tokens"] / max(1, rep["usage"]["prompt_tokens"])
    takeaway(f"Targeted repair: one leaf, {rep['usage']['prompt_tokens']:,} tokens, four gates in the trace. Regeneration: all four "
             f"leaves exposed, {ratio:.0f}× the tokens, {len(changed)} leaf{'ves' if len(changed) != 1 else ''} changed"
             + (" including ones that were right" if len(changed) > 1 else "") + ", and no gate that could have stopped it.")
code_panel("targeted repair, the gates, the regeneration", [S.repair_leaf, S.gate_repair, S.regenerate])

# ------------------------------------------------------------------ 5 · compare
if regen:
    st.markdown("### 5 · Compare")
    score = pd.DataFrame({LABEL[n]: {
        "context growth: max tracker prompt (chars)": max(growth[n]),
        "context growth: prompt tokens over the shift": f"{cum[n]:,}" + ("" if n == "state" else " (computed)"),
        "retained information: facts in writer input (of 5)": sum(S.retained(inputs[n])["facts"].values()),
        "retained information: stale values in writer input (of 5)": sum(S.retained(inputs[n])["traps"].values()),
        "retained information: writer input tokens": count_tokens(inputs[n]),
        "evaluation: deterministic score": dl[n]["grade"]["score"],
        "evaluation: verifier findings": len([f for f in dl[n]["findings"] if f.get("rule_exists") and f.get("leaf_known")]),
        "evaluation: planted stale value caught by provenance": "yes" if dl[n]["planted_caught"] else "no",
        "trace: fact digest": dl[n]["state_digest"] or "no",
        "cost: writer $": round(dl[n]["usage"]["cost_usd"] or 0, 5),
    } for n in inputs}).astype(str)
    st.dataframe(score, width="stretch")
    st.markdown(f"**Retry scope and cost** · targeted repair {rep['usage']['prompt_tokens']:,} tokens, 1 leaf · regeneration "
                f"{regen['usage']['prompt_tokens']:,} tokens, {len(E.LEAVES)} leaves.")
    takeaway("The state harness keeps the prompt flat whatever arrives and hands the writer only what is true now, so the "
             "provenance test works (the stale value is not in the input). The repair fixes the one leaf that failed and the "
             "trace shows exactly what changed and why it was allowed to.")
with st.expander("Numbers from the paper and the course notebook"):
    st.markdown("""
- **SKILL.state, Table 1.** T=100: score 0.94 at 65k cumulative tokens, against 0.84 at 1.25M for ReAct. T=200: ReAct prompt 48k
  characters and growing; SKILL.state 1.8k. Cumulative cost O(T²) vs O(T).
- **Budget-matched (Table 5).** Same ~1,800-token budget: truncated window 0.18, summary 0.52, SKILL.state 0.94.
- **Noise (Table 2).** 50 distractor events per turn: ReAct 0.53, SKILL.state 0.98.
- **Course notebook (docs desk, T=90).** Transcript: 13 of 14 traps in the writer's input, planted stale values caught 0 of 2.
  State: 0 traps, 2 of 2 caught, fact digest in the trace.
""")
