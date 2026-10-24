"""Presentation helpers: step-by-step navigation, code snippets, takeaways."""

import folium
import streamlit as st
import xyzservices.providers as xyz
from folium.plugins import Fullscreen

# Light gray basemap that needs no API key (CARTO basemaps now require one).
BASEMAP = xyz.Esri.WorldGrayCanvas


def with_fullscreen(m: folium.Map) -> folium.Map:
    """Add a full-screen toggle to a folium map (Streamlit's component iframe allows it)."""
    Fullscreen(position="topleft", title="Pełny ekran", title_cancel="Zamknij pełny ekran").add_to(m)
    return m


def _move(key: str, steps: list[str], offset: int) -> None:
    i = steps.index(st.session_state[key])
    st.session_state[key] = steps[min(max(i + offset, 0), len(steps) - 1)]


def stepper(key: str, steps: list[str]) -> int:
    """Step picker in the sidebar + progress bar. Returns the current step index."""
    st.sidebar.radio("Krok", steps, key=key)
    i = steps.index(st.session_state[key])
    st.progress((i + 1) / len(steps), text=f"Krok {i + 1} z {len(steps)}")
    return i


def step_buttons(key: str, steps: list[str]) -> None:
    """Back/Next buttons at the bottom of the page — handy while presenting."""
    i = steps.index(st.session_state[key])
    st.divider()
    left, _, right = st.columns([1, 4, 1])
    left.button("← Wstecz", on_click=_move, args=(key, steps, -1),
                disabled=i == 0, width="stretch")
    right.button("Dalej →", on_click=_move, args=(key, steps, 1),
                 disabled=i == len(steps) - 1, width="stretch", type="primary")


def code(snippet: str) -> None:
    """Code shown to students — mirrors what the app actually runs."""
    st.code(snippet.strip("\n"), language="python")


def takeaway(text: str) -> None:
    st.info(text, icon="💡")
