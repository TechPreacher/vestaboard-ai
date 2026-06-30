from datetime import datetime
from pathlib import Path

import streamlit as st

from vboard import device as devmod
from vboard import history, vbml


def _format_when(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return dt.strftime("%Y-%m-%d %H:%M")


def render_history(path: Path) -> None:
    st.header("History")
    st.caption("Messages delivered to the board, newest first.")

    entries = history.load(history.history_path_for(path))
    if not entries:
        st.info("No messages delivered yet.")
        return

    for entry in reversed(entries):
        title = entry.prompt_title or entry.prompt_id
        when = _format_when(entry.timestamp)
        label = devmod.get(entry.device).label
        flag = " · truncated" if entry.truncated else ""
        st.markdown(f"**{when}** — {title}  \n_{label} · prompt id: {entry.prompt_id}{flag}_")
        # Render the stored region at its own size, so each entry shows the right
        # number of characters even if the device setting later changes.
        st.code(vbml.render_region(entry.grid))
