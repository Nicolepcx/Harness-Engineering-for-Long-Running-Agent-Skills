"""Per-user state and a small helper for live calls. Everything a player does lives in st.session_state."""

import streamlit as st

from core import llm


def space(name: str) -> dict:
    if name not in st.session_state:
        st.session_state[name] = {}
    return st.session_state[name]


def live(n_calls: int, label: str, fn, *args, **kwargs):
    """
    Run one live step under the session and global call budgets. Returns the result, or None after showing the error.
    The budget is reserved first; unused calls are released if the step fails before making them.
    """
    try:
        llm.reserve_calls(n_calls)
    except llm.BudgetExceeded as e:
        st.error(str(e))
        return None
    if not llm.is_configured():
        st.error("No OpenRouter key is configured on the server.")
        llm.release_calls(n_calls)
        return None
    try:
        with st.spinner(label):
            return fn(*args, **kwargs)
    except Exception as e:  # provider errors, timeouts, unparseable JSON
        llm.release_calls(n_calls)
        st.error(f"The model call failed ({type(e).__name__}: {str(e)[:200]}). Try again.")
        return None


def usage_line(u) -> str:
    d = u if isinstance(u, dict) else u.as_dict()
    cost = d.get("cost_usd")
    return (f"{d.get('model', '')} · {d.get('prompt_tokens', 0):,} in / {d.get('completion_tokens', 0):,} out"
            + (f" ({d.get('reasoning_tokens', 0):,} reasoning)" if d.get("reasoning_tokens") else "")
            + (f" · ${cost:.5f}" if cost is not None else ""))
