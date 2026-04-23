# config.py — Smart ISO Fair Assistant
#
# Central configuration. Import this module everywhere instead of
# hardcoding IPs or paths in individual agent files.
import os
from pathlib import Path

try:
	# Prefer python-dotenv when available.
	from dotenv import load_dotenv  # type: ignore
except ImportError:
	load_dotenv = None

def _load_local_env() -> None:
	"""Load .env next to this file so values work regardless of current cwd."""
	env_path = Path(__file__).with_name(".env")
	if not env_path.exists():
		return

	if load_dotenv is not None:
		load_dotenv(dotenv_path=env_path, override=False)
		return

	# Minimal fallback parser for KEY=VALUE lines if python-dotenv is missing.
	for raw_line in env_path.read_text(encoding="utf-8").splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip().strip('"').strip("'")
		os.environ.setdefault(key, value)


_load_local_env()

# ── Robot IPs ──────────────────────────────────────────────────────────────────
# PEPPER_IP = "172.30.36.41"   # PEPPER from professor's test file (try .42 as fallback)
PEPPER_IP = "172.30.36.42" # SALT
TEMI_IP   = "172.30.36.32"   # try .32 as fallback
LOCAL_IP  = "172.30.36.206" # LINUX PC
# LOCAL_IP  = "172.30.36.107"  # Windows IP 

# Allow runtime overrides without editing source files.
PEPPER_IP = os.getenv("PEPPER_IP", PEPPER_IP).strip()
TEMI_IP   = os.getenv("TEMI_IP", TEMI_IP).strip()
LOCAL_IP  = os.getenv("LOCAL_IP", LOCAL_IP).strip()

# ── LLM ────────────────────────────────────────────────────────────────────────
LLM_MODEL       = "gpt-4o-mini"
OPENAI_API_KEY  = (os.getenv("OPENAI_API_KEY") or "").strip()   # loaded from .env
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
TABLET_SERVER_PORT = int(os.getenv("TABLET_SERVER_PORT", str(TABLET_SERVER_PORT)).strip())
AUTO_START_TABLET_SERVER = os.getenv("AUTO_START_TABLET_SERVER", "true").strip().lower() == "true"
# Path part after http://LOCAL_IP:TABLET_SERVER_PORT used by Temi /img endpoint.
TEMI_ASSETS_URL_PREFIX = os.getenv("TEMI_ASSETS_URL_PREFIX", "/assets/temi_screens").strip()
TEMI_START_LOCATION = os.getenv("TEMI_START_LOCATION", "bakery").strip()
TEMI_FLYER_WAIT_TIMEOUT = int(os.getenv("TEMI_FLYER_WAIT_TIMEOUT", "45").strip())
TEMI_FLYER_PROMPT_TIMEOUT = int(os.getenv("TEMI_FLYER_PROMPT_TIMEOUT", "20").strip())

# ── Pepper behaviour ──────────────────────────────────────────────────────────
PEPPER_LANGUAGE      = "English"
PEPPER_VOLUME        = 0.5   # 0-100
SPEECH_TIMEOUT       = 12    # seconds to wait for visitor to speak
QR_SCAN_TIMEOUT      = 20    # seconds for QR scan at stand entrance
FACE_DETECT_TIMEOUT  = 8     # seconds to detect a face
SESSION_IDLE_TIMEOUT = 180   # 3 min of silence → close session
AUTO_ACCEPT_FLYER    = os.getenv("AUTO_ACCEPT_FLYER", "false").strip().lower() == "true"
ENABLE_TYPED_FALLBACK = os.getenv("ENABLE_TYPED_FALLBACK", "true").strip().lower() == "true"
ENABLE_SPEECH_FALLBACK = os.getenv("ENABLE_SPEECH_FALLBACK", "true").strip().lower() == "true"
SPEECH_KEYWORD_TIMEOUT = int(os.getenv("SPEECH_KEYWORD_TIMEOUT", "10").strip())
SPEECH_KEYWORD_THRESHOLD = float(os.getenv("SPEECH_KEYWORD_THRESHOLD", "0.30").strip())

# ── Debug ──────────────────────────────────────────────────────────────────────
DEBUG = True