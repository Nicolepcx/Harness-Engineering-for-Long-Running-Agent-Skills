"""
Record, once and live:
  data/reference_runs.json   the 12-step state tracker run (fallback for hands-on 2 when a live run isn't possible)
  data/reference_long.json   a 60-step shift run by all three trackers (the paper-scale growth curve, shown as recorded)

    cd course_app && .venv/bin/python ../tools/record_reference_runs.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "course_app"))
from harness import stream as S  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "course_app" / "data"
DATA.mkdir(exist_ok=True)

events = S.make_stream()
state = S.run_state(events)
print("short state:", state["usage"]["calls"], "calls,", state["rejected_patches"], "rejected, wrote at", state["wrote_at"])
print(json.dumps(state["final_state"]))
(DATA / "reference_runs.json").write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%d %H:%M"), "tracker_model": S.WRITER,
                                                      "state_run": state}, indent=1, default=str))

long = S.make_stream(horizon=60)
st = S.run_state(long)
print("60-step state:", st["usage"]["calls"], "calls,", st["rejected_patches"], "rejected, wrote at", st["wrote_at"],
      "max prompt", max(st["prompt_chars"]))
tr = S.run_transcript(long)
print("60-step transcript: wrote at", tr["wrote_at"], "max prompt", max(tr["prompt_chars"]))
win = S.run_transcript(long, budget_chars=S.window_budget(st))
print("60-step window: wrote at", win["wrote_at"], "max prompt", max(win["prompt_chars"]))
out = {"recorded_at": time.strftime("%Y-%m-%d %H:%M"), "tracker_model": S.WRITER, "horizon": len(long),
       "runs": {"transcript": tr, "window": win, "state": st}}
for n, r in out["runs"].items():
    inp = S.writer_input(r, long); ret = S.retained(inp)
    r["writer_input_tokens"] = len(inp) // 4
    r["facts"], r["traps"] = sum(ret["facts"].values()), sum(ret["traps"].values())
    print(n, "prompt tokens", r["usage"]["prompt_tokens"], "cost", round(r["usage"]["cost_usd"], 4), "facts", r["facts"], "traps", r["traps"])
(DATA / "reference_long.json").write_text(json.dumps(out, indent=1, default=str))
print("written")
