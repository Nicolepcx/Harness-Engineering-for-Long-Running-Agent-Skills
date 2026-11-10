"""The execution trace of this session: what the harness recorded, with every digest, model binding and verdict."""

import json

import pandas as pd
import streamlit as st

from core.ui import page_header

page_header(0, "Execution trace", "Everything this session's runs recorded. Yours only; other attendees have their own.", 5,
            notebook_path=None, kind="TRACE")

h1 = st.session_state.get("h1", {})
h2 = st.session_state.get("h2", {})
if not h1.get("trace") and not h2.get("state_run"):
    st.info("Nothing recorded yet. Run hands-on 1 or 2.")
    st.stop()

if h1.get("trace"):
    st.markdown("### Hands-on 1 · compile and evaluate")
    tr = h1["trace"]
    st.markdown(f"Skill {', '.join(a['ref'] + ' (' + a['digest'] + ')' for a in tr['skill']['artifacts'] if a['kind'] == 'skill')} · "
                f"surface `{tr['compiled_surface']['digest']}` · writer `{tr['model_bindings']['writer']}` · judge `{tr['model_bindings']['judge']}` · "
                f"accepted **{tr['accepted']}**")
    st.json(tr, expanded=1)

if h2.get("state_run"):
    st.markdown("### Hands-on 2 · state and repair")
    rows = []
    for name, run in {"state": h2["state_run"], **(h2.get("live_trackers") or {})}.items():
        rows.append({"harness": name, "tracker calls": run["usage"]["calls"], "prompt tokens": run["usage"]["prompt_tokens"],
                     "rejected patches": run.get("rejected_patches", 0), "wrote at": ", ".join(run["wrote_at"]),
                     "cost $": round(run["usage"]["cost_usd"], 5)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if h2.get("deliverables"):
        for name, d in h2["deliverables"].items():
            st.markdown(f"**{name}** · surface `{d['surface_digest']}`" + (f" · state `{d['state_digest']}`" if d.get("state_digest") else "")
                        + f" · score {d['grade']['score']}")
    if h2.get("repair"):
        st.markdown("**Repair** · " + json.dumps(h2["repair"].get("gates", []))[:400])
    with st.expander("Full hands-on 2 record (JSON)"):
        st.json({k: v for k, v in h2.items() if k in ("state_run", "live_trackers", "deliverables", "repair", "regen")}, expanded=1)

st.download_button("Download this trace (JSON)", json.dumps({"h1": h1.get("trace"), "h2": {k: h2.get(k) for k in ("state_run", "live_trackers", "deliverables", "repair", "regen")}},
                                                             indent=1, default=str), file_name="skill-harness-trace.json")
