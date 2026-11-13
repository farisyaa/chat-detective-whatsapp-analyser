import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import streamlit as st
import streamlit.components.v1 as components
from detective_backend import parse_chat, scrub_messages

st.set_page_config(page_title="Chat Detective", page_icon="🕵️", layout="centered")
import html as _html

FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Instrument+Serif:ital@1'
         '&family=Bricolage+Grotesque:wght@400;500;600&family=Courier+Prime:wght@400;700&family=Caveat:wght@500;700&display=swap" rel="stylesheet">')

# All texture is inline SVG data URIs. No images, no external assets, works in Colab display(HTML) and Streamlit st.markdown.
def _svg(s):
    return "url(\"data:image/svg+xml;utf8," + s.replace("#", "%23").replace("\n", "") + "\")"

# paper grain (visible this time)
GRAIN = _svg("<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>"
             "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='3' stitchTiles='stitch'/>"
             "<feColorMatrix values='0 0 0 0 0.2 0 0 0 0 0.14 0 0 0 0 0.08 0 0 0 0.16 0'/></filter>"
             "<rect width='100%' height='100%' filter='url(#n)'/></svg>")
# ink wear mask for stamps: blotchy, so letters print unevenly
INK = _svg("<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>"
           "<filter id='m'><feTurbulence type='fractalNoise' baseFrequency='0.45' numOctaves='2' seed='7'/>"
           "<feColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 1.3 0.1'/></filter>"
           "<rect width='100%' height='100%' fill='white' filter='url(#m)'/></svg>")
# a coffee ring, because every real case file has one
RING = _svg("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200'>"
            "<circle cx='100' cy='100' r='78' fill='none' stroke='#7a4a1e' stroke-width='9' opacity='.16'/>"
            "<circle cx='100' cy='100' r='78' fill='none' stroke='#5a3312' stroke-width='2' opacity='.22' stroke-dasharray='40 11 6 23 90 14'/>"
            "<circle cx='100' cy='100' r='70' fill='none' stroke='#7a4a1e' stroke-width='1.5' opacity='.12'/></svg>")
# three different scribble underlines so the names don't look stamped out by a machine
SCRIBBLES = [
    "<path d='M1 5 Q 14 1 27 5 T 53 4 T 79 6 T 99 3' fill='none' stroke='#d92b2b' stroke-width='2.6' stroke-linecap='round'/>",
    "<path d='M2 4 C 20 8, 40 0, 60 5 S 90 2, 99 6 M4 7 C 30 4, 60 9, 96 5' fill='none' stroke='#d92b2b' stroke-width='1.9' stroke-linecap='round'/>",
    "<path d='M0 6 Q 25 2 50 6 T 100 5' fill='none' stroke='#d92b2b' stroke-width='3' stroke-linecap='round'/>",
]
def _scribble(i):
    return _svg("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 10' preserveAspectRatio='none'>" + SCRIBBLES[i % 3] + "</svg>")

CSS = f"""
<style>
.cd{{--ink:#1b1713;--paper:#f3ecdc;--paper2:#faf5ea;--red:#cf2a26;--mute:#7b7267;--green:#79c66e;--tape:#efd98a;
     font-family:'Bricolage Grotesque','Space Grotesk',system-ui,sans-serif;color:var(--ink);max-width:560px;
     background:var(--paper);background-image:{GRAIN},radial-gradient(120% 90% at 50% 40%,rgba(255,255,255,.25),rgba(120,90,50,.18));
     border:2px solid var(--ink);border-radius:4px 4px 14px 4px;box-shadow:7px 8px 0 var(--ink);padding:30px 28px 24px;position:relative;line-height:1.35;overflow:hidden}}
.cd *{{box-sizing:border-box}}
.cd .ring{{position:absolute;left:-52px;bottom:62px;width:180px;height:180px;background:{RING} no-repeat center/contain;pointer-events:none;transform:rotate(-14deg)}}
.cd .holes{{position:absolute;left:0;right:0;top:12px;display:flex;justify-content:space-between;padding:0 92px;pointer-events:none}}
.cd .holes i{{width:12px;height:12px;border-radius:50%;background:#e8e2d4;box-shadow:inset 1px 1.5px 2px rgba(0,0,0,.45),0 1px 0 rgba(255,255,255,.6)}}
.cd .file{{font-family:'Courier Prime','Courier New',monospace;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-top:6px}}
.cd .file s{{color:var(--ink);text-decoration-color:var(--red);text-decoration-thickness:2px}}
.cd .file .hand{{font-family:'Caveat',cursive;font-size:17px;color:var(--red);text-transform:none;letter-spacing:0;margin-left:4px;display:inline-block;transform:rotate(-4deg)}}
.cd h1{{font-family:'Archivo Black',Impact,sans-serif;font-size:36px;line-height:.98;letter-spacing:-.015em;margin:16px 0 12px;text-transform:uppercase;text-shadow:2px 2px 0 var(--paper),3px 3px 0 var(--ink)}}
.cd .pill{{display:inline-block;font-family:'Instrument Serif',Georgia,serif;font-style:italic;font-weight:400;font-size:31px;text-transform:none;letter-spacing:0;text-shadow:none;
     background:var(--paper2);border:2px solid var(--ink);border-radius:999px;padding:0 15px 3px;box-shadow:3px 3px 0 var(--ink);transform:rotate(-2.5deg) translateY(-2px);margin-left:6px}}
.cd .verdict{{font-size:17.5px;font-weight:500;margin:0 0 10px;max-width:92%}}
.cd .verdict em{{font-family:'Instrument Serif',serif;font-style:italic;font-size:1.12em}}
.cd .stats{{font-family:'Courier Prime',monospace;font-size:12.5px;color:var(--ink);margin:0 0 22px;padding:6px 0;border-top:1px solid rgba(27,23,19,.35);border-bottom:1px solid rgba(27,23,19,.35)}}
.cd .stats span{{white-space:nowrap}}
.cd .stats span + span:before{{content:'  //  ';color:var(--mute)}}
.cd .person{{background:var(--paper2);background-image:{GRAIN};border:2px solid var(--ink);border-radius:3px 10px 3px 8px;box-shadow:4px 5px 0 var(--ink);padding:18px 16px 14px;margin:0 0 24px;position:relative}}
.cd .person:nth-child(odd){{transform:rotate(-.45deg)}}
.cd .person:nth-child(even){{transform:rotate(.35deg);margin-left:6px;margin-right:-6px}}
.cd .person:nth-child(3n){{transform:rotate(-.2deg);margin-left:-4px;margin-right:4px}}
.cd .tape{{position:absolute;left:50%;top:-12px;width:92px;height:22px;margin-left:-46px;background:var(--tape);background-image:{GRAIN};opacity:.85;
     transform:rotate(-3deg);box-shadow:0 1px 2px rgba(0,0,0,.18);
     clip-path:polygon(0 0,97% 2%,100% 20%,98% 100%,2% 96%,0 80%)}}
.cd .person:nth-child(even) .tape{{transform:rotate(2.5deg);left:74%}}
.cd .person:nth-child(3n) .tape{{transform:rotate(-1.5deg);left:58%}}
.cd .emo{{position:absolute;left:-13px;top:-13px;width:40px;height:40px;border:2px solid var(--ink);border-radius:9px 11px 8px 12px;background:var(--acc);display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:2px 2px 0 var(--ink);transform:rotate(-3deg)}}
.cd .stamp{{position:absolute;right:12px;top:-16px;color:var(--red);border:3px double var(--red);border-radius:4px;padding:5px 10px 4px;line-height:1;
     font-family:'Archivo Black',Impact,sans-serif;font-size:12px;letter-spacing:.1em;text-transform:uppercase;transform:rotate(6deg);
     background:var(--paper2);-webkit-mask-image:{INK};mask-image:{INK};-webkit-mask-size:70px 70px;mask-size:70px 70px;opacity:.95}}
.cd .person:nth-child(even) .stamp{{transform:rotate(-4deg);right:auto;left:150px;top:-14px}}
.cd .person:nth-child(3n) .stamp{{transform:rotate(3deg);right:26px;top:-18px}}
.cd .name{{font-family:'Archivo Black',Impact,sans-serif;font-size:23px;text-transform:uppercase;display:inline-block;position:relative;margin:2px 0 6px 28px;letter-spacing:.01em}}
.cd .name:after{{content:'';position:absolute;left:-3px;right:-6px;bottom:-4px;height:9px;background-repeat:no-repeat;background-size:100% 100%}}
.cd .s0 .name:after{{background-image:{_scribble(0)}}}
.cd .s1 .name:after{{background-image:{_scribble(1)}}}
.cd .s2 .name:after{{background-image:{_scribble(2)}}}
.cd .chips{{margin:4px 0 10px;display:flex;flex-wrap:wrap;gap:7px;align-items:center}}
.cd .chips .note{{margin-left:auto;font-family:'Caveat',cursive;font-weight:700;font-size:21px;color:var(--red);transform:rotate(-6deg);line-height:1;white-space:nowrap;padding-right:4px}}
.cd .person:nth-child(even) .chips .note{{transform:rotate(4deg)}}
.cd .chip{{font-family:'Courier Prime',monospace;font-size:12px;font-weight:700;border:1.5px solid var(--ink);border-radius:999px;padding:3px 10px 2px;background:var(--paper);box-shadow:2px 2px 0 var(--ink)}}
.cd .chip.mbti{{background:var(--acc);transform:rotate(-1.5deg)}}
.cd .chip.twin{{border-radius:3px;transform:rotate(.6deg);box-shadow:1.5px 1.5px 0 var(--ink)}}
.cd .roast{{font-size:15.5px;margin:0 0 12px}}
.cd .receipt{{font-family:'Courier Prime',monospace;font-size:12px;color:var(--ink);background:#fffdf6;padding:7px 10px 10px;position:relative;margin:0 0 0 -2px;max-width:fit-content;
     box-shadow:1px 2px 3px rgba(0,0,0,.12);
     clip-path:polygon(0 0,100% 0,100% calc(100% - 4px),97% 100%,94% calc(100% - 4px),91% 100%,88% calc(100% - 4px),85% 100%,82% calc(100% - 4px),79% 100%,76% calc(100% - 4px),73% 100%,70% calc(100% - 4px),67% 100%,64% calc(100% - 4px),61% 100%,58% calc(100% - 4px),55% 100%,52% calc(100% - 4px),49% 100%,46% calc(100% - 4px),43% 100%,40% calc(100% - 4px),37% 100%,34% calc(100% - 4px),31% 100%,28% calc(100% - 4px),25% 100%,22% calc(100% - 4px),19% 100%,16% calc(100% - 4px),13% 100%,10% calc(100% - 4px),7% 100%,4% calc(100% - 4px),1% 100%,0 calc(100% - 4px))}}
.cd .receipt b{{color:var(--red);font-weight:700;letter-spacing:.08em;display:block;font-size:10.5px;margin-bottom:2px}}
.cd .foot{{font-family:'Caveat',cursive;font-size:19px;color:var(--ink);display:flex;justify-content:space-between;align-items:flex-end;margin-top:10px;position:relative}}
.cd .foot .sig{{transform:rotate(-2deg);display:inline-block;max-width:100%;line-height:1.05;font-size:18px}}

@media(max-width:480px){{
.cd{{padding:28px 20px 20px}}
.cd .file{{flex-wrap:wrap;gap:4px}}
.cd h1{{font-size:30px}}
.cd .stats span{{white-space:normal}}
.cd .stamp,.cd .person:nth-child(even) .stamp,.cd .person:nth-child(3n) .stamp{{left:auto;right:6px;max-width:calc(100% - 40px);font-size:10px}}
.cd .chip{{max-width:100%;overflow-wrap:anywhere}}
.cd .chips .note{{white-space:normal}}
}}
</style>
"""

ACCENTS = ["var(--green)", "var(--tape)", "#f0a9c0", "#9fcbff", "#ffb36b"]
NOTES = ["guilty.", "no further questions", "we all saw it", "noted.", "lol"]

def _e(s):
    return _html.escape(str(s or ""))

def render_card_html(v, case_no="0001"):
    """Verdict JSON -> self-contained HTML (works in Colab display(HTML) and Streamlit st.markdown)."""
    people = ""
    for i, p in enumerate(v.get("people", [])):
        acc = ACCENTS[i % len(ACCENTS)]
        note = p.get("note") or NOTES[i % len(NOTES)]
        people += f"""
        <div class="person s{i % 3}" style="--acc:{acc}">
          <div class="tape"></div>
          <div class="emo">{_e(p.get('emoji'))}</div>
          <div class="stamp">{_e(p.get('label'))}</div>
          <div class="name">{_e(p.get('name'))}</div>
          <div class="chips">
            <span class="chip mbti">{_e(p.get('mbti'))}</span>
            <span class="chip twin">twin: {_e(p.get('celebrity'))}</span>
            <span class="note">{_e(note)}</span>
          </div>
          <p class="roast">{_e(p.get('roast'))}</p>
          <div class="receipt"><b>RECEIPT</b>{_e(p.get('receipt'))}</div>
        </div>"""
    stats = "".join(f'<span>{_e(s.strip())}</span>' for s in str(v.get("group_subtitle", "")).replace("|", "·").split("·") if s.strip())
    n = len(v.get("people", []))
    return f"""{FONTS}{CSS}
    <div class="cd">
      <div class="holes"><i></i><i></i></div>
      <div class="ring"></div>
      <div class="file"><span>Case file No. {_e(case_no)} &nbsp;·&nbsp; <s>confidential</s><span class="hand">lol no</span></span><span>{n} suspects · 0 innocent</span></div>
      <h1>{_e(v.get('group_name'))} <span class="pill">exposed.</span></h1>
      <p class="verdict">{_e(v.get('group_verdict'))}</p>
      <div class="stats">{stats}</div>
      {people}
      <div class="foot"><span class="sig">read in full by 4 agents, so you don't have to</span></div>
    </div>"""


MAX_BYTES = 5 * 1024 * 1024

def read_upload(upload):
    data = upload.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError("Upload a file under 5 MB.")
    if upload.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = [i for i in z.infolist() if i.filename.lower().endswith(".txt") and not i.is_dir() and not i.filename.startswith("__MACOSX/")]
            if len(entries) != 1:
                raise ValueError("ZIP must contain exactly one WhatsApp .txt export.")
            if entries[0].file_size > MAX_BYTES:
                raise ValueError("The uncompressed text must be under 5 MB.")
            with z.open(entries[0]) as f:
                data = f.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("The uncompressed text must be under 5 MB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Please upload a UTF-8 WhatsApp export.") from None

def run_backend(text):
    env = os.environ.copy()
    try:
        for name in ("GOOGLE_API_KEY", "CHAT_DETECTIVE_MODEL"):
            if name in st.secrets:
                env[name] = str(st.secrets[name])
    except FileNotFoundError:
        pass
    env["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"
    if not env.get("GOOGLE_API_KEY"):
        raise ValueError("Add GOOGLE_API_KEY to Streamlit Settings → Secrets first.")
    proc = subprocess.run([sys.executable, str(Path(__file__).with_name("detective_backend.py"))],
                          input=json.dumps({"text":text}), text=True, capture_output=True,
                          env=env, timeout=300)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ValueError("The backend stopped unexpectedly. Try a smaller export.") from None
    if not payload.get("ok"):
        raise ValueError(payload.get("error", "Investigation failed."))
    return payload["result"]

# ============================================================
# PAGE STYLING
# ============================================================
PAGE_CSS = FONTS + """
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=Instrument+Serif:ital@1&family=Bricolage+Grotesque:wght@400;500;600&family=Courier+Prime:wght@400;700&display=swap');

/* Hide Streamlit chrome */
#MainMenu, footer, header {visibility: hidden;}
[data-testid="stHeader"] {background: transparent !important;}
.block-container {padding-top: 2rem !important; max-width: 720px !important;}

/* Page background */
.stApp {
    background: #faf6f1 !important;
    font-family: 'Bricolage Grotesque', system-ui, sans-serif;
}

/* Custom hero headline */
.hero-title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 48px;
    font-weight: 600;
    color: #1b1713;
    line-height: 1.1;
    margin: 0 0 8px 0;
}
.hero-title .pill {
    display: inline-block;
    font-family: 'Instrument Serif', Georgia, serif;
    font-style: italic;
    font-weight: 400;
    font-size: 46px;
    background: #f5c6d0;
    border-radius: 999px;
    padding: 2px 20px 6px;
    margin-left: 8px;
    transform: rotate(-2deg);
    white-space: nowrap;
}
.hero-tagline {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 18px;
    color: #5a534a;
    margin: 0 0 28px 0;
    line-height: 1.5;
}

/* Upload card */
.upload-card {
    background: #fff;
    border: 1px solid #e0dbd4;
    border-radius: 16px;
    overflow: hidden;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}
.upload-header {
    background: #e8a857;
    color: #1b1713;
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.upload-header-title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-weight: 600;
    font-size: 17px;
}
.upload-header-step {
    font-family: 'Courier Prime', monospace;
    font-size: 13px;
    letter-spacing: 0.05em;
    opacity: 0.85;
}
.upload-body {
    padding: 20px;
}
.upload-hint {
    font-family: 'Courier Prime', monospace;
    font-size: 13px;
    color: #7b7267;
    margin-bottom: 16px;
}
.upload-dropzone {
    background: #f5f9f3;
    border: 2px dashed #c5d4be;
    border-radius: 12px;
    padding: 32px 24px;
    text-align: left;
    position: relative;
}
.upload-dropzone-title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 22px;
    font-weight: 500;
    color: #1b1713;
    margin-bottom: 16px;
}

/* Override Streamlit file uploader */
[data-testid="stFileUploader"] {
    background: transparent !important;
}
[data-testid="stFileUploaderDropzone"] {
    background: transparent !important;
    border: none !important;
}
[data-testid="stFileUploaderDropzoneInstructions"] {
    display: none !important;
}
[data-testid="stFileUploader"] button {
    background: #c8e6b8 !important;
    color: #1b1713 !important;
    border: 1px solid #9fc98f !important;
    border-radius: 8px !important;
    font-family: 'Bricolage Grotesque', sans-serif !important;
    font-weight: 500 !important;
    padding: 8px 20px !important;
}
[data-testid="stFileUploader"] small {
    font-family: 'Courier Prime', monospace !important;
    color: #7b7267 !important;
}

/* Checkbox styling */
[data-testid="stCheckbox"] label span {
    font-family: 'Bricolage Grotesque', sans-serif !important;
    font-size: 14px !important;
    color: #1b1713 !important;
}

/* Primary button - Investigate */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
    background: #d4a59a !important;
    color: #1b1713 !important;
    border: none !important;
    border-radius: 8px !important;
    font-family: 'Bricolage Grotesque', sans-serif !important;
    font-weight: 500 !important;
    font-size: 15px !important;
    padding: 12px 24px !important;
    box-shadow: none !important;
}
.stButton > button[kind="primary"]:hover {
    background: #c9948a !important;
}
.stButton > button[kind="primary"]:disabled {
    background: #d4a59a !important;
    opacity: 0.5 !important;
}

/* Secondary button - Preview */
.stButton > button[kind="secondary"],
.stButton > button:not([kind="primary"]) {
    background: #fff !important;
    color: #1b1713 !important;
    border: 1px solid #1b1713 !important;
    border-radius: 8px !important;
    font-family: 'Bricolage Grotesque', sans-serif !important;
    font-weight: 500 !important;
    font-size: 15px !important;
    padding: 12px 24px !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: #fff !important;
    border: 1px solid #e0dbd4 !important;
    border-radius: 12px !important;
    margin-bottom: 12px !important;
}
[data-testid="stExpander"] summary {
    font-family: 'Bricolage Grotesque', sans-serif !important;
    font-size: 15px !important;
    color: #1b1713 !important;
    padding: 16px 20px !important;
}
[data-testid="stExpander"] svg {
    color: #7b7267 !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #f5f1eb !important;
}
[data-testid="stSidebar"] [data-testid="stMetricValue"] {
    font-family: 'Archivo Black', sans-serif !important;
    color: #1b1713 !important;
}
[data-testid="stSidebar"] [data-testid="stMetricLabel"] {
    font-family: 'Courier Prime', monospace !important;
    color: #7b7267 !important;
    font-size: 12px !important;
}

/* Hide default labels */
[data-testid="stWidgetLabel"] {
    display: none !important;
}

/* Spinner */
.stSpinner > div {
    border-color: #e8a857 transparent transparent transparent !important;
}
</style>
"""

# ============================================================
# UI LAYOUT
# ============================================================
st.markdown(PAGE_CSS, unsafe_allow_html=True)

# Hero
st.markdown("""
<h1 class="hero-title">Your group chat.<br>Under <span class="pill">investigation.</span></h1>
<p class="hero-tagline">Someone's always "otw". Someone only replies "k".<br>Let's see what the receipts say.</p>
""", unsafe_allow_html=True)

# Upload card
st.markdown("""
<div class="upload-card">
  <div class="upload-header">
    <span class="upload-header-title">Submit the evidence</span>
    <span class="upload-header-step">01 / UPLOAD</span>
  </div>
  <div class="upload-body">
    <p class="upload-hint">WhatsApp export · without media · TXT or ZIP · up to 5 MB</p>
    <div class="upload-dropzone">
      <p class="upload-dropzone-title">Drop your chat export here</p>
""", unsafe_allow_html=True)

upload = st.file_uploader("Upload", type=["txt", "zip"], label_visibility="collapsed")

st.markdown("</div></div></div>", unsafe_allow_html=True)

consent = st.checkbox("I have permission to analyze this chat. I understand that scrubbed snippets and stats are sent to Gemini.")

col1, col2 = st.columns([1, 1])
with col1:
    investigate_clicked = st.button("Investigate this chat ↗", disabled=not (upload and consent), type="primary")
with col2:
    preview_clicked = st.button("Preview a sample case")

with st.expander("Before you hand over the receipts"):
    st.markdown("""
    **For entertainment only.** This is not a psychological assessment.

    **Privacy:** Supported PII patterns (phone numbers, emails, URLs) are redacted before analysis. Names and sensitive context may remain in the scrubbed text sent to Gemini.

    **Demo limits:** 20,000 messages and 20 participants max.
    """)

with st.expander("How do I export my chat?"):
    st.markdown("""
    1. Open the WhatsApp chat
    2. Tap the three dots (⋮) → **More** → **Export chat**
    3. Choose **Without media**
    4. Save the .txt or .zip file
    5. Upload it here
    """)

# ============================================================
# LOGIC
# ============================================================
if preview_clicked:
    # Show a hardcoded sample verdict
    sample_verdict = {
        "group_name": "Sample Squad",
        "group_verdict": "A textbook case of chronic lateness, selective hearing, and 'I'll do it tomorrow' energy.",
        "group_subtitle": "847 messages · 1.2 min median reply · 14 months of chaos",
        "people": [
            {"name": "Alex", "emoji": "🦥", "label": "THE GHOST", "mbti": "INFP", "celebrity": "Timothée Chalamet", "roast": "Appears once a month to drop a single 'lol' then vanishes.", "receipt": "Last seen: 3 weeks ago. Messages sent: 12."},
            {"name": "Sam", "emoji": "📱", "label": "THE SCHEDULER", "mbti": "ESTJ", "celebrity": "Monica Geller", "roast": "Will create a poll for literally anything, including what to have for lunch.", "receipt": "Polls created: 47. Polls ignored by group: 46."}
        ]
    }
    st.session_state["result"] = {"verdict": sample_verdict, "summary": {"total": {"usd": 0, "calls": 0}}, "tools": [], "ledger": []}

if investigate_clicked:
    st.session_state.pop("result", None)
    try:
        raw = read_upload(upload)
        clean, report = scrub_messages(parse_chat(raw))
        if not clean:
            raise ValueError("No supported messages found. Check your WhatsApp export format.")
        if len(clean) > 20000 or len({m["sender"] for m in clean}) > 20:
            raise ValueError("Demo limit: 20,000 messages and 20 participants.")
        st.caption(f"Parsed {len(clean):,} messages. Redacted {sum(report.values())} supported PII matches.")
        with st.spinner("Investigator → parallel profilers → Roastmaster..."):
            st.session_state["result"] = run_backend(raw)
        del raw, clean
    except subprocess.TimeoutExpired:
        st.error("The investigation exceeded five minutes. Try a smaller export.")
    except (ValueError, zipfile.BadZipFile, RuntimeError) as e:
        st.error(f"Could not analyze the export: {e}")

result = st.session_state.get("result")
if result:
    v = result["verdict"]
    components.html(render_card_html(v), height=400 + 340 * len(v["people"]), scrolling=True)
    totals = result["summary"]["total"]
    if totals["calls"] > 0:
        with st.sidebar:
            st.metric("Estimated cost (USD)", f"${totals['usd']:.5f}")
            st.metric("Model calls", totals["calls"])
            st.caption("Historical pricing estimates, not a billing quote.")
    with st.expander("Detective log and token usage"):
        if result.get("tools"):
            st.dataframe(result["tools"], use_container_width=True)
        if result.get("ledger"):
            st.dataframe(result["ledger"], use_container_width=True)
    st.download_button("Download verdict JSON", json.dumps(v, ensure_ascii=False, indent=2), "verdict.json", "application/json")
