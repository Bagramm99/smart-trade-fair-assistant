# ── Robot IPs ──
PEPPER_IP = "172.30.36.42" # from professor's test file
TEMI_IP   = "172.30.36.32" # your machine's IP on the same network
LOCAL_IP  = "0.0.0.0" # replace once you have Temi's IP

# ── LLM ──
LLM_MODEL = "gpt-4o-mini"
OPENAI_API_KEY  = ""   # or set env var OPENAI_API_KEY
LLM_TEMPERATURE = 0.3

# TODO: I am actually unsure if we do have an API KEY for OPEN AI, do you guys remember what the professor said?
# TODO: Add the key to a secret key file

# ── Knowledge base ─────────────────────────────────────────────────────────────
KB_DIR          = "knowledge/raw_texts"
KB_INDEX_DIR    = "knowledge/kb_index"
EMBED_MODEL     = "all-MiniLM-L6-v2"
KB_TOP_K        = 3   # how many chunks to retrieve per query

# ── Temi assets ────────────────────────────────────────────────────────────────
TEMI_ASSETS_DIR = "assets/temi_screens"

# ── Pepper behaviour ──────────────────────────────────────────────────────────
PEPPER_LANGUAGE         = "English"
PEPPER_VOLUME           = 0.9
SPEECH_TIMEOUT          = 12     # seconds to wait for visitor to speak
QR_SCAN_TIMEOUT         = 20     # seconds for QR scan at stand entrance
FACE_DETECT_TIMEOUT     = 8      # seconds to detect a face
SESSION_IDLE_TIMEOUT    = 180    # 3 min of silence → close session

# ── Debug ──────────────────────────────────────────────────────────────────────
DEBUG = True

