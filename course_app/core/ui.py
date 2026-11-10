"""Shared building blocks so every session page looks and reads the same."""

import inspect
import textwrap
from typing import Callable, Iterable

import streamlit as st

REPO = "Nicolepcx/Harness-Engineering-for-Long-Running-Agent-Skills"


def colab_url(notebook_path: str) -> str:
    return f"https://colab.research.google.com/github/{REPO}/blob/main/{notebook_path}"


def page_header(session: int, title: str, subtitle: str, minutes: int, notebook_path: str | None,
                kind: str = "HANDS-ON") -> None:
    st.caption(f"SESSION {session} · {kind} · {minutes} MIN")
    st.title(title)
    st.markdown(subtitle)
    if notebook_path:
        st.link_button("Open the full notebook in Colab", colab_url(notebook_path), icon=":material/open_in_new:")


def task(text: str) -> None:
    """The one thing attendees should do on this page."""
    st.markdown(
        f"""<div class="lab-task"><div class="lab-task-label">Your task</div>{text}</div>""",
        unsafe_allow_html=True,
    )


def task_card(task: str, todos: list[str], why: str, remember: str) -> None:
    """
    The hands-on task, as given in the course outline, with what to do on this page
    and why: the learning goal, taken from the notebook's own explanation.
    """
    st.markdown(
        f"""<div class="lab-task"><div class="lab-task-label">Hands-on task</div><b>{task}</b></div>""",
        unsafe_allow_html=True,
    )
    left, right = st.columns([1, 1.15], gap="large")
    with left:
        st.markdown("**Your TODOs**")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(todos, 1)))
    with right:
        st.markdown("**Why you're doing this**")
        st.markdown(why)
    st.markdown(
        f"""<div class="lab-takeaway"><div class="lab-task-label">If you remember one thing</div>{remember}</div>""",
        unsafe_allow_html=True,
    )


def code_panel(title: str, objs: Callable | Iterable[Callable] | str, why: str = "") -> None:
    """
    Collapsible "the code behind this" panel.

    Pass functions/classes rather than strings where possible: the panel then
    shows their real source, so what attendees read is exactly what runs.
    """
    with st.expander(f":material/code: {title}"):
        if why:
            st.markdown(why)
        if isinstance(objs, str):
            source = textwrap.dedent(objs).strip()
        else:
            objs = [objs] if callable(objs) else list(objs)
            source = "\n\n".join(textwrap.dedent(inspect.getsource(o)).strip() for o in objs)
        st.code(source, language="python")


def takeaway(text: str) -> None:
    st.markdown(
        f"""<div class="lab-takeaway"><div class="lab-task-label">Takeaway</div>{text}</div>""",
        unsafe_allow_html=True,
    )


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { max-width: 1150px; padding-top: 2.5rem; }
        .lab-task, .lab-takeaway {
            border-radius: 10px; padding: 0.9rem 1.1rem; margin: 0.8rem 0 1.2rem;
            border: 1px solid rgba(127,127,127,0.25);
        }
        .lab-task { border-left: 5px solid #2f7de1; background: rgba(47,125,225,0.07); }
        .lab-takeaway { border-left: 5px solid #1fa37a; background: rgba(31,163,122,0.07); }
        .lab-task-label {
            font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
            text-transform: uppercase; opacity: 0.7; margin-bottom: 0.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ------------------------------------------------------------------ guided exercises
def highlight(text: str, bad: dict, good: Iterable[str] = ()) -> str:
    """Escape HTML, then mark problem terms in red (with a title saying why) and current facts in green."""
    import html as _html
    out = _html.escape(text)
    for term, why in bad.items():
        out = out.replace(term, f'<mark style="background:#ffd3d3;color:#8a1c1c" title="{_html.escape(why)}">{term}</mark>')
    for term in good:
        out = out.replace(term, f'<mark style="background:#d6f5e3;color:#0f5a36">{term}</mark>')
    return out


def show_text(html_body: str, height: int = 200) -> None:
    """A monospace box for already-highlighted text."""
    st.markdown(f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:.82rem;white-space:pre-wrap;border:1px solid '
                f'rgba(127,127,127,.3);border-radius:8px;padding:.6rem .8rem;max-height:{height}px;overflow:auto">{html_body}</div>',
                unsafe_allow_html=True)


def quiz(store: dict, key: str, question: str, options: list[str], correct: str, hints: list[str], explain: str) -> bool:
    """
    One multiple-choice step of an exercise. `store` is the page's session dict. Hints are revealed one at a time and the
    last one names the answer, so nobody gets stuck. Returns True once answered correctly.
    """
    st.markdown(f"**{question}**")
    choice = st.radio(question, options, index=None, key=f"q_{key}", label_visibility="collapsed", horizontal=len(options) <= 4)
    shown = store.get(f"hint_{key}", 0)
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("Check", key=f"chk_{key}"):
        store[f"ans_{key}"] = choice
    if shown < len(hints) and c2.button("Hint" if shown == 0 else "Another hint", key=f"hint_{key}_{shown}"):
        store[f"hint_{key}"] = shown + 1
        st.rerun()
    for i in range(shown):
        c3.markdown(f"💡 {hints[i]}")
    answered = store.get(f"ans_{key}")
    if answered is None:
        return False
    if answered == correct:
        st.success(f"Right: {correct}. {explain}")
        return True
    st.error(f"Not quite: {answered}. Try again, or take a hint.")
    return False
