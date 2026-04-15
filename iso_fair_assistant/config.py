# config.py — Smart ISO Fair Assistant
#
# Central configuration. Import this module everywhere instead of
# hardcoding IPs or paths in individual agent files.

# ── Robot IPs ──────────────────────────────────────────────────────────────────
PEPPER_IP = "172.30.36.41"   # from professor's test file (try .42 as fallback)
TEMI_IP   = "172.30.36.31"   # try .32 as fallback
LOCAL_IP  = "172.30.36.107"  # Windows IP 

# ── LLM ────────────────────────────────────────────────────────────────────────
LLM_MODEL       = "gpt-4o-mini"
OPENAI_API_KEY  = ""   # set via .env — do NOT commit the key!
LLM_TEMPERATURE = 0.3

# ── Knowledge base ─────────────────────────────────────────────────────────────
KB_DIR       = "knowledge/raw_texts"
KB_INDEX_DIR = "knowledge/kb_index"
EMBED_MODEL  = "all-MiniLM-L6-v2"
KB_TOP_K     = 3   # how many chunks to retrieve per query

# ── Temi assets ────────────────────────────────────────────────────────────────
# TEMI_ASSETS_DIR is only used locally (e.g. to check if a file exists).
# Temi itself receives an HTTP URL built from LOCAL_IP + TABLET_SERVER_PORT.
TEMI_ASSETS_DIR    = "assets/temi_screens"
TABLET_SERVER_PORT = 8082   # Python HTTP server running on Windows (not WSL!)

# ── Pepper behaviour ──────────────────────────────────────────────────────────
PEPPER_LANGUAGE      = "English"
PEPPER_VOLUME        = 0.9
SPEECH_TIMEOUT       = 12    # seconds to wait for visitor to speak
QR_SCAN_TIMEOUT      = 20    # seconds for QR scan at stand entrance
FACE_DETECT_TIMEOUT  = 8     # seconds to detect a face
SESSION_IDLE_TIMEOUT = 180   # 3 min of silence → close session

# ── Debug ──────────────────────────────────────────────────────────────────────
DEBUG = True