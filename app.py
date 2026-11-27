"""
Streamlit frontend for the AI Video & Meeting Assistant.

Run:  streamlit run app.py
"""
import html
import os
import tempfile

import streamlit as st

from main import run_pipeline
from core.rag_engine import ask_question

# ------------------------------------------------------------------ #
# Page config
# ------------------------------------------------------------------ #
st.set_page_config(
    page_title="AI Video & Meeting Assistant",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

SUPPORTED_TYPES = ["mp4", "mkv", "mov", "webm", "avi", "mp3", "wav", "m4a"]
LANGUAGES = ["english", "hinglish"]
SUGGESTED_QUESTIONS = [
    "Summarize this in 3 bullet points",
    "What were the main decisions?",
    "Who owns which action items?",
    "What is still unresolved?",
]
WORDS_PER_MINUTE = 150  # average speaking rate, used for a duration estimate

# ------------------------------------------------------------------ #
# Styles — dev-tool look: monospace labels, badges, compact header
# ------------------------------------------------------------------ #
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap');

.block-container { padding-top: 2rem; padding-bottom: 7rem; max-width: 1500px; }

.crumb { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; color: #7D8590; }
.app-title { font-size: 1.9rem; font-weight: 700; margin: 0.2rem 0 0.6rem 0; line-height: 1.25; }

.badges { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1.2rem; }
.badge {
    font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
    padding: 0.2rem 0.6rem; border-radius: 6px;
    background: #161B22; border: 1px solid #30363D; color: #C9D1D9;
}
.badge.ok { border-color: #238636; color: #3FB950; }

.panel-title {
    font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;
    text-transform: uppercase; letter-spacing: 0.08em; color: #7D8590;
    margin-bottom: 0.5rem;
}

.empty { text-align: center; padding: 2.5rem 1rem 1.5rem 1rem; }
.empty-icon { font-size: 2rem; }
.empty-title { font-size: 1.05rem; font-weight: 600; margin-top: 0.5rem; }
.empty-sub { font-size: 0.85rem; color: #7D8590; margin-top: 0.3rem; }

.step { font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; color: #C9D1D9; line-height: 2; }
.step b { color: #7C5CFF; }
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #
def init_state() -> None:
    # Streamlit re-runs the script on every interaction, so the pipeline
    # result (incl. rag_chain) and chat history must live in session_state.
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("meta", {})


def save_upload_to_temp(uploaded_file) -> str:
    """Persist an uploaded file to disk so process_input() can read it by path."""
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        return tmp.name


def render_items(items) -> None:
    """Render extractor output whether it comes back as a list or a string."""
    if not items:
        st.info("Nothing found in this recording.")
    elif isinstance(items, (list, tuple)):
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.markdown(items)


def as_text(items) -> str:
    if isinstance(items, (list, tuple)):
        return "\n".join(f"- {i}" for i in items)
    return str(items or "")


def build_report(result: dict) -> str:
    return (
        f"# {result['title']}\n\n"
        f"## Summary\n{result['summary']}\n\n"
        f"## Action Items\n{as_text(result['action_items'])}\n\n"
        f"## Key Decisions\n{as_text(result['key_decisions'])}\n\n"
        f"## Open Questions\n{as_text(result['open_questions'])}\n"
    )


init_state()

# ------------------------------------------------------------------ #
# Sidebar
# ------------------------------------------------------------------ #
with st.sidebar:
    st.markdown('<div class="panel-title">▸ input</div>', unsafe_allow_html=True)

    input_mode = st.segmented_control(
        "Source", ["YouTube URL", "Upload file"], default="YouTube URL", label_visibility="collapsed"
    ) or "YouTube URL"

    source = None
    uploaded_file = None
    if input_mode == "YouTube URL":
        source = st.text_input("Video / meeting link", placeholder="https://www.youtube.com/watch?v=...")
    else:
        uploaded_file = st.file_uploader("Video or audio file", type=SUPPORTED_TYPES)

    language = st.selectbox("Language", LANGUAGES, format_func=str.capitalize)
    analyze = st.button("▶ Analyze", type="primary", use_container_width=True)

    if st.session_state.result:
        st.divider()
        st.markdown('<div class="panel-title">▸ session</div>', unsafe_allow_html=True)
        st.caption(f"Chat turns: {len(st.session_state.messages) // 2}")
        st.download_button(
            "⬇ Export report (.md)",
            data=build_report(st.session_state.result),
            file_name="meeting_report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        if st.button("🗑 Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

# ------------------------------------------------------------------ #
# Run pipeline
# ------------------------------------------------------------------ #
if analyze:
    tmp_path = None

    if input_mode == "YouTube URL":
        source = (source or "").strip()
        if not source.startswith(("http://", "https://")):
            st.sidebar.error("Please enter a valid URL.")
            st.stop()
        source_label = "youtube"
    else:
        if uploaded_file is None:
            st.sidebar.error("Please upload a file.")
            st.stop()
        tmp_path = save_upload_to_temp(uploaded_file)
        source = tmp_path
        source_label = "upload"

    with st.status("Transcribing and analyzing… long videos can take a few minutes.") as status:
        try:
            result = run_pipeline(source, language)
            st.session_state.result = result
            st.session_state.messages = []  # new recording → fresh chat
            st.session_state.meta = {"language": language, "source": source_label}
            status.update(label="Analysis complete ✅", state="complete")
        except Exception as exc:
            status.update(label="Processing failed ❌", state="error")
            st.error(f"Something went wrong while processing: {exc}")
            st.stop()
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

result = st.session_state.result

# ------------------------------------------------------------------ #
# Landing state
# ------------------------------------------------------------------ #
if result is None:
    st.markdown('<div class="crumb">~/ai-video-assistant</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-title">AI Video &amp; Meeting Assistant</div>', unsafe_allow_html=True)
    st.markdown(
        """
<div class="step"><b>01</b> &nbsp;Paste a YouTube link or upload a recording in the sidebar</div>
<div class="step"><b>02</b> &nbsp;Pick the language and hit <b>Analyze</b></div>
<div class="step"><b>03</b> &nbsp;Review summary, action items, decisions and open questions</div>
<div class="step"><b>04</b> &nbsp;Ask follow-up questions — answers come from the vector DB</div>
""",
        unsafe_allow_html=True,
    )
    st.stop()

# ------------------------------------------------------------------ #
# Header with run metadata
# ------------------------------------------------------------------ #
meta = st.session_state.meta
word_count = len(result["transcript"].split())
est_minutes = max(1, round(word_count / WORDS_PER_MINUTE))

st.markdown(
    f"""
<div class="crumb">~/ai-video-assistant / analysis</div>
<div class="app-title">{html.escape(result['title'])}</div>
<div class="badges">
  <span class="badge">source: {meta.get('source', '-')}</span>
  <span class="badge">lang: {meta.get('language', '-')}</span>
  <span class="badge">words: {word_count:,}</span>
  <span class="badge">~{est_minutes} min audio</span>
  <span class="badge ok">● vector store ready</span>
</div>
""",
    unsafe_allow_html=True,
)

# Top-level chat_input is pinned to the bottom of the page, so it is
# always visible no matter how long the content above is.
prompt = st.chat_input("Ask anything about this recording…")
prompt = prompt or st.session_state.pop("pending_prompt", None)

insights_col, chat_col = st.columns([3, 2], gap="large")

# ---------------- Insights ---------------- #
with insights_col:
    st.markdown('<div class="panel-title">▸ insights</div>', unsafe_allow_html=True)
    tab_summary, tab_actions, tab_decisions, tab_questions, tab_transcript = st.tabs(
        ["Summary", "Action Items", "Key Decisions", "Open Questions", "Transcript"]
    )

    with tab_summary:
        with st.container(height=560, border=False):
            st.markdown(result["summary"])

    with tab_actions:
        with st.container(height=560, border=False):
            render_items(result["action_items"])

    with tab_decisions:
        with st.container(height=560, border=False):
            render_items(result["key_decisions"])

    with tab_questions:
        with st.container(height=560, border=False):
            render_items(result["open_questions"])

    with tab_transcript:
        st.download_button(
            "⬇ transcript.txt",
            data=result["transcript"],
            file_name="transcript.txt",
            mime="text/plain",
        )
        with st.container(height=510, border=False):
            st.code(result["transcript"], language=None, wrap_lines=True)

# ---------------- RAG chat ---------------- #
with chat_col:
    st.markdown('<div class="panel-title">▸ rag chat</div>', unsafe_allow_html=True)
    history = st.container(height=600, border=True)

    with history:
        if not st.session_state.messages and not prompt:
            st.markdown(
                """
<div class="empty">
  <div class="empty-icon">💬</div>
  <div class="empty-title">Ask your recording anything</div>
  <div class="empty-sub">Answers are retrieved from the transcript in the vector DB.<br>
  Type below or start with a suggestion.</div>
</div>
""",
                unsafe_allow_html=True,
            )
            for i, q in enumerate(SUGGESTED_QUESTIONS):
                if st.button(q, key=f"suggest_{i}", use_container_width=True):
                    st.session_state.pending_prompt = q
                    st.rerun()

        for msg in st.session_state.messages:
            avatar = "🧑‍💻" if msg["role"] == "user" else "🤖"
            st.chat_message(msg["role"], avatar=avatar).markdown(msg["content"])

        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.chat_message("user", avatar="🧑‍💻").markdown(prompt)

            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Retrieving context…"):
                    try:
                        answer = ask_question(result["rag_chain"], prompt)
                    except Exception as exc:
                        answer = f"⚠️ Couldn't answer that: {exc}"
                st.markdown(answer)

            st.session_state.messages.append({"role": "assistant", "content": answer})