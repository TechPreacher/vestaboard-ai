from pathlib import Path

import streamlit as st

from vboard import config as cfgmod


def render_credentials(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Credentials")

    st.subheader("Vestaboard")
    backend = st.selectbox("Backend", ["cloud", "local"],
                           index=0 if cfg.vestaboard.backend == "cloud" else 1)
    cloud_key = st.text_input("Cloud Read/Write key", value=cfg.vestaboard.cloud_key,
                              type="password")
    local_endpoint = st.text_input("Local endpoint", value=cfg.vestaboard.local_endpoint)
    local_key = st.text_input("Local key", value=cfg.vestaboard.local_key, type="password")

    st.subheader("LLM (OpenAI-compatible)")
    base_url = st.text_input("Base URL", value=cfg.llm.base_url)
    model = st.text_input("Model", value=cfg.llm.model)
    api_key = st.text_input("API key", value=cfg.llm.api_key, type="password")
    timeout_seconds = st.number_input(
        "Request timeout (seconds)",
        min_value=5.0,
        max_value=600.0,
        value=float(cfg.llm.timeout_seconds),
        step=5.0,
        help="How long to wait for the LLM to respond. Raise this if you see read timeouts.",
    )

    if st.button("Save credentials"):
        cfg.vestaboard.backend = backend
        cfg.vestaboard.cloud_key = cloud_key
        cfg.vestaboard.local_endpoint = local_endpoint
        cfg.vestaboard.local_key = local_key
        cfg.llm.base_url = base_url
        cfg.llm.model = model
        cfg.llm.api_key = api_key
        cfg.llm.timeout_seconds = timeout_seconds
        cfgmod.save_config(cfg, path)
        st.success("Saved.")


def render_prompts(cfg: cfgmod.AppConfig, path: Path) -> None:
    st.header("Prompts & Schedules")

    for i, p in enumerate(cfg.prompts):
        with st.expander(f"{p.id}: {p.text[:30]}"):
            p.text = st.text_area("Prompt", value=p.text, key=f"text_{i}")
            p.cron = st.text_input("Cron (m h dom mon dow)", value=p.cron, key=f"cron_{i}")
            p.color_hints_enabled = st.checkbox("Color hints", value=p.color_hints_enabled,
                                                key=f"hints_{i}")
            p.enabled = st.checkbox("Enabled", value=p.enabled, key=f"en_{i}")
            if st.button("Delete", key=f"del_{i}"):
                cfg.prompts.pop(i)
                cfgmod.save_config(cfg, path)
                st.rerun()

    st.subheader("Add prompt")
    new_id = st.text_input("ID", key="new_id")
    new_text = st.text_area("Prompt text", key="new_text")
    new_cron = st.text_input("Cron", value="0 8 * * *", key="new_cron")
    if st.button("Add"):
        if new_id and new_text:
            cfg.prompts.append(cfgmod.PromptEntry(id=new_id, text=new_text, cron=new_cron))
            cfgmod.save_config(cfg, path)
            st.rerun()

    if st.button("Save all"):
        cfgmod.save_config(cfg, path)
        st.success("Saved.")
