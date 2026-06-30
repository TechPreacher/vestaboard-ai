from pathlib import Path

import streamlit as st

from vboard import config as cfgmod
from vboard import device as devmod
from vboard import history, pipeline, vbml


def render_preview(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Preview / Test Send")

    dev = devmod.get(cfg.vestaboard.device)
    st.caption(
        f"Device: {dev.label} — {dev.lines} lines × {dev.cols} chars ({dev.content_limit} total)"
    )

    if not cfg.prompts:
        st.info("No prompts configured yet.")
        return

    def _label(p: cfgmod.PromptEntry) -> str:
        title = p.display_title
        title = title if len(title) <= 120 else title[:120] + "…"
        return f"{p.id}: {title}"

    labels = [_label(p) for p in cfg.prompts]
    idx = st.selectbox("Prompt", range(len(cfg.prompts)), format_func=lambda i: labels[i])
    prompt = cfg.prompts[idx]

    sample = st.text_area("Sample message to preview (skips LLM)", value="RAIN TODAY")
    if sample:
        result = vbml.compile(sample, prompt.color_hints_enabled, dev)
        st.write(
            f"Content length: {result.content_len}/{dev.content_limit} — valid: {result.valid}"
        )
        if result.reason:
            st.warning(result.reason)
        # Show just the device's content area, with real glyphs and dots for
        # blank cells, at its true size (3×15 for a Note, 6×22 for a Vestaboard).
        st.code(vbml.render_region(vbml.content_region(result.grid, dev)))

    st.divider()
    if st.button("Test send now (calls LLM + board)"):
        with st.spinner("Generating and delivering…"):
            r = pipeline.run_once(cfg, prompt)
        if r.delivered:
            st.success(f"Delivered: {r.text!r} (attempts={r.attempts}, truncated={r.truncated})")
            st.code(vbml.render_region(r.grid))
            try:
                history.append(
                    history.history_path_for(path),
                    history.HistoryEntry(
                        timestamp=history.now_iso(),
                        prompt_id=prompt.id,
                        prompt_title=prompt.display_title,
                        text=r.text,
                        truncated=r.truncated,
                        grid=r.grid,
                        device=r.device,
                    ),
                )
            except Exception as e:  # noqa: BLE001 - history is best-effort
                st.warning(f"Delivered, but could not record history: {e}")
        else:
            st.error(f"Failed: {r.error}")
