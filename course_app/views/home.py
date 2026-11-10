"""Start here."""

import streamlit as st

from harness.models import JUDGE, WRITER

st.caption("HARNESS ENGINEERING FOR LONG-RUNNING AGENT SKILLS · LAB")
st.title("The skill harness, hands-on")
st.markdown("""
A `SKILL.md` is the easy part. Around it, something has to decide **which skill applies** to a task, **which parts of it**
apply, **what the agent remembers** while a task runs for hours, **whether the output is right**, **how to fix the one part
that is wrong**, and **what was recorded** so the run can be reproduced. That something is the harness. This lab is the two
hands-on exercises of the course, run on one production workload: a parcel carrier's **shipment exception desk**, which
writes delivery notices to recipients while scans, corrections and requests keep arriving.

Both pages run real model calls. The harness itself is ordinary Python; every step has a **Show the code** panel with
the source that actually ran. Writer: `{writer}`. Judges: `{judge}`, a different model family, so no author grades its own work.
""".format(writer=WRITER, judge=JUDGE))

c1, c2 = st.columns(2)
with c1:
    st.markdown("#### Hands-on 1 · Compile and evaluate")
    st.markdown("Select the `delivery-notice` skill for one task, compile only the applicable sections into a surface with a "
                "digest, generate three candidate notices, then run a deterministic check, a relative judge and a verifier on "
                "them and read the trace.")
    st.page_link("views/h1_compile_evaluate.py", label="Open hands-on 1", icon=":material/rule:")
with c2:
    st.markdown("#### Hands-on 2 · State and repair")
    st.markdown("Process one shipment's stream of scans and delayed corrections three ways (full transcript, fixed window, "
                "explicit state with `skill_state`), write the notice from each, grade it, and repair one leaf without "
                "regenerating the rest. Compare context growth, retained facts, findings, retry scope and cost.")
    st.page_link("views/h2_state_repair.py", label="Open hands-on 2", icon=":material/timeline:")

st.markdown("""
#### Sources this lab follows
- The course deck and the book chapter: skill artifacts with version and digest, `slice_section` by task axes,
  `compile_surface` with manifest and surface digest, "match the checker to the question", rank then verify, four gates
  before a repair is accepted.
- *SKILL.state* (Badhe, Tiwari & Chung, 2026) and its reference implementation, the `skill_state` package, used as is:
  `(P, Σ_t, O_t)` in, `(R_t, ΔΣ_t, a_t)` out, `Σ ⊕ ΔΣ` with null deletes, validation on the merged state, rollback and retry.
- The course notebook on explicit execution state: identical writer for every harness, the budget-matched window, traps
  and facts in the writer's input, deterministic graders, the provenance test, surface digest and state digest in the trace.
""")
st.caption("Each browser session has its own runs. Model calls are budgeted per session and per server.")
