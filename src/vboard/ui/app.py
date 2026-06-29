import os
from pathlib import Path

import bcrypt
import streamlit as st

from vboard import config as cfgmod
from vboard.ui import pages_config, pages_history, pages_preview

# WARNING: _check_password() is the SOLE authentication gate for this entire app.
# Do NOT add a Streamlit pages/ directory — it would route around this gate and
# break security. Add new pages through the main() router instead.

CONFIG_PATH = Path(os.environ.get("VBOARD_CONFIG", "config.json"))

# Repo-root-relative so it resolves regardless of the process working directory.
LOGO_PATH = Path(__file__).resolve().parents[3] / "assets" / "vestaboard.jpg"


def _check_password(cfg: cfgmod.AppConfig) -> bool:
    """Returns True if authenticated. Renders login or first-run setup."""
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False

    if not cfg.password_hash:
        st.warning("First run: set an admin password.")
        new = st.text_input("New password", type="password")
        if st.button("Set password") and new:
            cfg.password_hash = bcrypt.hashpw(new.encode(), bcrypt.gensalt()).decode()
            cfgmod.save_config(cfg, CONFIG_PATH)
            st.success("Password set. Reload the page to log in.")
        st.stop()

    if st.session_state.auth_ok:
        return True

    pw = st.text_input("Password", type="password")
    if st.button("Log in"):
        if bcrypt.checkpw(pw.encode(), cfg.password_hash.encode()):
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()


def main() -> None:
    st.set_page_config(page_title="Vestaboard AI", page_icon="📋")
    cfg = cfgmod.load_config(CONFIG_PATH)
    _check_password(cfg)

    if LOGO_PATH.exists():
        st.sidebar.image(str(LOGO_PATH), use_container_width=True)
    st.sidebar.title("Vestaboard AI")
    page = st.sidebar.radio(
        "Page",
        ["Credentials", "Prompts & Schedules", "Preview / Test", "History"],
    )
    cfg = cfgmod.load_config(CONFIG_PATH)  # reload fresh after auth

    if page == "Credentials":
        pages_config.render_credentials(cfg, CONFIG_PATH)
    elif page == "Prompts & Schedules":
        pages_config.render_prompts(cfg, CONFIG_PATH)
    elif page == "Preview / Test":
        pages_preview.render_preview(cfg, CONFIG_PATH)
    else:
        pages_history.render_history(CONFIG_PATH)


main()
