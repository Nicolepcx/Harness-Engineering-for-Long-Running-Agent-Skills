"""Hands-on 2 through the app: recorded stream, write+verify, the repair quiz, targeted repair, regeneration."""
import os, time
os.environ["ALLOW_NO_PASSWORD"] = "1"
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("../course_app/app.py", default_timeout=900)
at.run(); at.switch_page("views/h2_state_repair.py"); at.run(); assert not at.exception, at.exception

def click(part):
    b = [x for x in at.button if part in x.label]; assert b, f"no button {part!r}: {[x.label for x in at.button]}"
    t = time.time(); b[0].click(); at.run(); assert not at.exception, at.exception
    print(f"clicked {part!r} ({time.time()-t:.0f}s) errors {[e.value[:90] for e in at.error]}")

def answer(key, value):
    at.radio(key=f"q_{key}").set_value(value); at.run()
    [b for b in at.button if b.key == f"chk_{key}"][0].click(); at.run(); assert not at.exception, at.exception
    print(f"  {key} -> {value!r}: success={bool(at.success)} error={[e.value[:60] for e in at.error]}")

click("recorded run")
click("Write and verify")
H = at.session_state.h2
for n, d in H["deliverables"].items(): print(" ", n, d["grade"]["score"], [(f["rule_id"], f["leaf"]) for f in d["findings"] if f.get("rule_exists")])
tgt = at.session_state.h2["target"]; print("  target:", tgt)
answer("leaf", "1. status")   # deliberately wrong once
answer("leaf", f"{['status','eta','action','contact'].index(tgt['leaf']) + 1}. {tgt['leaf']}")
answer("rule", tgt["rule_id"])
answer("prompt", at.radio(key="q_prompt").options[2])
click("Run the targeted repair")
rep = at.session_state.h2["repair"]; print("  repair", rep["accepted"], [(g["gate"][:26], g["ok"]) for g in rep["gates"]], rep["usage"]["prompt_tokens"])
answer("gate", "index: only the flagged leaf came back")
click("Regenerate the whole notice")
rg = at.session_state.h2["regen"]; print("  regen changed", sum(d["changed"] for d in rg["diff"]), rg["usage"]["prompt_tokens"])
print("  scorecard rows:", len(at.dataframe[-1].value), "calls", at.session_state.llm_calls)
