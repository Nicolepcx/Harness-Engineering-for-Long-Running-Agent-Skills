"""Hands-on 1 through the real app: selection refusals, compile, candidates, rank, verify, trace (live calls)."""
import os
os.environ["ALLOW_NO_PASSWORD"] = "1"
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("../course_app/app.py", default_timeout=300)
at.run(); at.switch_page("views/h1_compile_evaluate.py"); at.run(); assert not at.exception, at.exception

def click(label_part):
    b = [x for x in at.button if label_part in x.label]
    assert b, f"no button containing {label_part!r}; have {[x.label for x in at.button]}"
    b[0].click(); at.run(); assert not at.exception, at.exception

radio = at.radio(key="h1_choice")
for opt in radio.options:
    radio.set_value(opt); at.run(); assert not at.exception, at.exception
    errs = [e.value for e in at.error]
    print(f"{opt!r}: " + (errs[0][:110] if errs else f"compiled, metrics {[m.value for m in at.metric][:3]}"))
radio.set_value(radio.options[0]); at.run()
click("Use the fixed teaching set")
print("rows after det:", [r for r in at.dataframe[-1].value.to_dict('records')][:1])
click("Rank the"); click("Verify #1")
s = at.session_state.h1
print("ranking", [r["id"] for r in s["ranking"]], "verdicts", {k: v["verdict"] for k, v in s["verdicts"].items()})
if any(v["verdict"] == "fail" for v in s["verdicts"].values()):
    click("Verify #2")
print("verdicts", {k: (v["verdict"], [f["rule_id"] for f in v["findings"] if f.get("rule_exists")]) for k, v in at.session_state.h1["verdicts"].items()})
print("trace accepted:", at.session_state.h1["trace"]["accepted"], "surface", at.session_state.h1["trace"]["compiled_surface"]["digest"])
click("Generate 3 candidates")
print("live cands:", list(at.session_state.h1["cands"]["items"]), "source", at.session_state.h1["cands"]["source"])
click("Rank the"); click("Verify #1")
print("live verdicts", {k: v["verdict"] for k, v in at.session_state.h1["verdicts"].items()})
