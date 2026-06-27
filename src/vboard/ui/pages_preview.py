from pathlib import Path

import streamlit as st

from vboard import config as cfgmod
from vboard import pipeline, vbml


def render_preview(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Preview / Test Send")

    if not cfg.prompts:
        st.info("No prompts configured yet.")
        return

    def _label(p: cfgmod.PromptEntry) -> str:
        text = p.text if len(p.text) <= 120 else p.text[:120] + "…"
        return f"{p.id}: {text}"

    labels = [_label(p) for p in cfg.prompts]
    idx = st.selectbox("Prompt", range(len(cfg.prompts)), format_func=lambda i: labels[i])
    prompt = cfg.prompts[idx]

    sample = st.text_area("Sample message to preview (skips LLM)", value="RAIN TODAY")
    if sample:
        result = vbml.compile(sample, prompt.color_hints_enabled)
        st.write(f"Content length: {result.content_len}/45 — valid: {result.valid}")
        if result.reason:
            st.warning(result.reason)
        st.code("\n".join(
            "".join("█" if c else "." for c in row) for row in result.grid
        ))

    st.divider()
    if st.button("Test send now (calls LLM + board)"):
        with st.spinner("Generating and delivering…"):
            r = pipeline.run_once(cfg, prompt)
        if r.delivered:
            st.success(f"Delivered: {r.text!r} (attempts={r.attempts}, truncated={r.truncated})")
        else:
            st.error(f"Failed: {r.error}")
