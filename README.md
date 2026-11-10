# Harness Engineering for Long-Running Agent Skills

The two hands-on exercises of the course, as a Streamlit app, on one production workload: a parcel carrier's
**shipment exception desk**. The agent writes delivery notices to recipients while scans, corrections and requests keep
arriving. Everything runs on real model calls through OpenRouter; the harness is plain Python shown on every page.

| Page | Hands-on |
| --- | --- |
| 1 · Compile and evaluate | Compile a skill for a predefined task, generate several candidate outputs, and compare deterministic validation with relative model-based judging; inspect how the selected skill version, compiled rules, model bindings, and evaluation results are captured in the execution trace. |
| 2 · State and repair | Process a stream containing updates and delayed corrections, evaluate the resulting deliverable, and repair one failed section without regenerating the complete output; compare context growth, retained information, evaluation results, retry scope, and cost. |

## Demo notebooks

`notebooks/demo1_runtime_compiler.ipynb` and `notebooks/demo2_explicit_state.ipynb` are the two session demos, built from the course notebooks' own code and docs-desk material (artifacts downloaded from Drive as in `explicit_execution_state.ipynb`):
discovery → selection → compilation → record, and the three harnesses over one shift with a judge-verifier and a focused retry of one part. They run in Colab; the app does not depend on them.

## Run locally

```bash
cd course_app
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo "OPENROUTER_API_KEY=..." > .env
ALLOW_NO_PASSWORD=1 .venv/bin/streamlit run app.py
```

Models (in `course_app/harness/models.py`): writer `openai/gpt-6-luna`, judges `anthropic/claude-haiku-5.5`. A full
playthrough makes about 25 live calls (6 in hands-on 1; in hands-on 2 the 8-step state tracker, three writers, three
verifications, and the repair pair) for about a cent. The transcript and window prompts in hands-on 2 are built
from the same observations and only measured, not sent, unless you opt into running those trackers live too.

The stream follows the paper's setup: 8 observations about one UPS shipment (US), each with background telemetry appended, so a transcript grows with every step and a state does not. `data/reference_long.json` holds one live run of all three trackers over the same shift stretched to 60 steps, for the paper-scale curve.

## Layout

```
course_app/
  app.py                navigation and the password gate
  core/                 auth (password + ACCESS_UNTIL), llm (OpenRouter client, call budgets), ui (task cards, code panels)
  skills/               the skill artifacts as files: identity, project (US conventions), delivery-notice 2.1.0 and 1.4.0, two unrelated skills, a persona
  harness/
    artifacts.py        parse, catalogue, load_for_task, slice_section, compile_surface, everything_surface
    evaluate.py         deterministic checks (limits read from the surface), writer, relative judge, judge pool, verifier, trace record
    stream.py           the event stream, Σ schema and checks, the three harnesses (skill_state for state), graders, provenance, repair gates
    models.py           model bindings, measured usage and cost
    session.py          per-browser-session state and budgeted live calls
  views/                home, h1_compile_evaluate, h2_state_repair, trace
  data/reference_runs.json   one recorded live run of the state tracker (fallback)
  data/reference_long.json   the 60-step shift, all three trackers, recorded once
tools/record_reference_runs.py
```

## Deploy

`.do/app.yaml` deploys `course_app/` to DigitalOcean App Platform; set the secrets with `course_app/deploy.sh`
(`COURSE_PASSWORD`, `ACCESS_UNTIL`, `OPENROUTER_API_KEY`). Each browser session has its own runs; shared caches hold
only read-only data.
