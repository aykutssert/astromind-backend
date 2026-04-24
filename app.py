import os
import json
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify
import swisseph as swe
from google import genai
from google.genai import types
from timezonefinder import TimezoneFinder
import pytz
import firebase_admin
from firebase_admin import credentials, auth, firestore
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")

client     = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

# ─────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
You are **Astra**, an AI astrology guide. Analyze the astrological data and provide daily insights in JSON format.

---

## OUTPUT FORMAT (MANDATORY)
Respond exclusively in **JSON format**. No markdown, no extra text.

{
  "summary": "2-3 sentence general daily vibe",
  "highlights": [
    {
      "tag": "health",
      "status": "positive|neutral|negative",
      "score": 0-100,
      "title": "short title",
      "description": "1-2 sentence explanation",
      "action": "specific action the user should take for this category"
    }
  ],
  "suggestions": ["action 1", "action 2", "action 3"]
}

**Tags (all 6 required):**
- health
- love
- career
- money
- beauty
- mind

---

## SCORING RULES
- **Score 0-100** based on planetary strength and aspects for each category
- **Status:** score > 70 = positive, score < 30 = negative, else neutral
- Use astrological data to determine scores (Venus for beauty/love, Mars for career, etc.)
- All 6 tags must be present every day
- Even low influence days should have a score (e.g., 30-50 for quiet days)

---

## CONTENT RULES
1. **No Jargon:** Don't mention planet names or aspect names in descriptions
2. **Be Human:** Speak naturally, not like a textbook
3. **Brief:** Keep descriptions 1-2 sentences
4. **Personal:** Address user by name if available
"""

CHAT_SYSTEM_PROMPT = """
You are **Astra**, an AI astrology guide. Answer the user's follow-up question in text format.
Be brief, warm, and personal. Address the user by name if available.
Use the technical data to back up your answer, but speak naturally, not like a textbook.
"""

# ─────────────────────────────────────────────
# Auth & Rate Limiting
# ─────────────────────────────────────────────

# Firebase Initialization
db = None
try:
    # 1. Try to load from Environment Variable (for Railway/Production)
    import base64
    service_account_b64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

    if service_account_b64:
        decoded = base64.b64decode(service_account_b64).decode('utf-8')
        service_account_info = json.loads(decoded)
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✓ Firebase Admin & Firestore initialized from ENVIRONMENT VARIABLE (base64).")
    elif service_account_json:
        service_account_info = json.loads(service_account_json)
        cred = credentials.Certificate(service_account_info)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✓ Firebase Admin & Firestore initialized from ENVIRONMENT VARIABLE.")
    else:
        # 2. Fallback to local file (for Local Development)
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            print("✓ Firebase Admin & Firestore initialized from LOCAL FILE.")
        else:
            print("⚠ Firebase not initialized: No variable or file found.")

except Exception as e:
    print(f"⚠ Firebase Admin NOT initialized: {e}")
    print("  (Authentication will be skipped for testing if no key is present)")

# Rate Limiter setup
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Check for Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            # If Firebase isn't initialized yet, we allow it for your local tests
            if not firebase_admin._apps:
                return f(*args, **kwargs)
            return jsonify({"status": "error", "message": "Missing or invalid token"}), 401

        # 2. Extract and verify token
        id_token = auth_header.split("Bearer ")[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            request.user = decoded_token  # Put user data into request object
        except Exception as e:
            return jsonify({"status": "error", "message": f"Token verification failed: {e}"}), 401

        return f(*args, **kwargs)
    return decorated_function

# ─────────────────────────────────────────────
# UI Metadata (Symbols, Elements, Colors)
# ─────────────────────────────────────────────

ZODIAC_METADATA = {
    "Aries":       {"symbol": "♈", "element": "Fire",  "quality": "Cardinal"},
    "Taurus":      {"symbol": "♉", "element": "Earth", "quality": "Fixed"},
    "Gemini":      {"symbol": "♊", "element": "Air",   "quality": "Mutable"},
    "Cancer":      {"symbol": "♋", "element": "Water", "quality": "Cardinal"},
    "Leo":         {"symbol": "♌", "element": "Fire",  "quality": "Fixed"},
    "Virgo":       {"symbol": "♍", "element": "Earth", "quality": "Mutable"},
    "Libra":       {"symbol": "♎", "element": "Air",   "quality": "Cardinal"},
    "Scorpio":     {"symbol": "♏", "element": "Water", "quality": "Fixed"},
    "Sagittarius": {"symbol": "♐", "element": "Fire",  "quality": "Mutable"},
    "Capricorn":   {"symbol": "♑", "element": "Earth", "quality": "Cardinal"},
    "Aquarius":    {"symbol": "♒", "element": "Air",   "quality": "Fixed"},
    "Pisces":      {"symbol": "♓", "element": "Water", "quality": "Mutable"}
}

PLANET_METADATA = {
    "Sun":        {"symbol": "☉", "color": "#FFCC00"}, # Gold
    "Moon":       {"symbol": "☽", "color": "#E6E6FA"}, # Lavender
    "Mercury":    {"symbol": "☿", "color": "#FFEB3B"}, # Yellow
    "Venus":      {"symbol": "♀", "color": "#4CAF50"}, # Emerald
    "Mars":       {"symbol": "♂", "color": "#F44336"}, # Red
    "Jupiter":    {"symbol": "♃", "color": "#9C27B0"}, # Purple
    "Saturn":     {"symbol": "♄", "color": "#455A64"}, # Dark Gray
    "Uranus":     {"symbol": "♅", "color": "#00BCD4"}, # Electric Blue
    "Neptune":    {"symbol": "♆", "color": "#3F51B5"}, # Indigo/Deep Blue
    "Pluto":      {"symbol": "♇", "color": "#880E4F"}, # Burgundy
    "True Node":  {"symbol": "☊", "color": "#FF9800"}, 
    "Lilith":     {"symbol": "⚸", "color": "#000000"},
    "Chiron":     {"symbol": "⚷", "color": "#795548"},
    "Ceres":      {"symbol": "⚳", "color": "#A5D6A7"}
}

ZODIAC_SIGNS = list(ZODIAC_METADATA.keys())

HOUSE_NAMES = [
    "1st House", "2nd House", "3rd House", "4th House",
    "5th House", "6th House", "7th House", "8th House",
    "9th House", "10th House", "11th House", "12th House"
]

# All 14 celestial bodies
PLANETS_CONFIG = {
    "Sun":        swe.SUN,
    "Moon":       swe.MOON,
    "Mercury":    swe.MERCURY,
    "Venus":      swe.VENUS,
    "Mars":       swe.MARS,
    "Jupiter":    swe.JUPITER,
    "Saturn":     swe.SATURN,
    "Uranus":     swe.URANUS,
    "Neptune":    swe.NEPTUNE,
    "Pluto":      swe.PLUTO,
    "True Node":  swe.TRUE_NODE,   # North Node (Kuzey Ay Düğümü)
    "Lilith":     swe.MEAN_APOG,   # Black Moon Lilith (Mean)
    "Chiron":     swe.CHIRON,
    "Ceres":      getattr(swe, "CERES", 17),
}

# Major + minor aspects
ASPECTS = {
    "Conjunction":    (0,   8.0),
    "Sextile":        (60,  5.0),
    "Square":         (90,  6.0),
    "Trine":          (120, 6.0),
    "Opposition":     (180, 8.0),
    "Semi-Sextile":   (30,  2.0),
    "Semi-Square":    (45,  2.5),
    "Sesquiquadrate": (135, 2.5),
    "Quincunx":       (150, 2.5),
}

MAJOR_ASPECTS = {"Conjunction", "Sextile", "Square", "Trine", "Opposition"}

# Dignity table: sign indices (0=Aries … 11=Pisces)
DIGNITY_TABLE = {
    "Sun":     {"Domicile": [4],      "Exaltation": [0],  "Detriment": [10],    "Fall": [6]},
    "Moon":    {"Domicile": [3],      "Exaltation": [1],  "Detriment": [9],     "Fall": [7]},
    "Mercury": {"Domicile": [2, 5],   "Exaltation": [5],  "Detriment": [8, 11], "Fall": [11]},
    "Venus":   {"Domicile": [1, 6],   "Exaltation": [11], "Detriment": [7, 0],  "Fall": [5]},
    "Mars":    {"Domicile": [0, 7],   "Exaltation": [9],  "Detriment": [6, 1],  "Fall": [3]},
    "Jupiter": {"Domicile": [8, 11],  "Exaltation": [3],  "Detriment": [2, 5],  "Fall": [9]},
    "Saturn":  {"Domicile": [9, 10],  "Exaltation": [6],  "Detriment": [3, 4],  "Fall": [0]},
    "Uranus":  {"Domicile": [10],     "Exaltation": [7],  "Detriment": [4],     "Fall": [1]},
    "Neptune": {"Domicile": [11],     "Exaltation": [3],  "Detriment": [5],     "Fall": [9]},
    "Pluto":   {"Domicile": [7],      "Exaltation": [0],  "Detriment": [1],     "Fall": [6]},
}

# Fixed stars with their archetypal nature (for AI context)
FIXED_STARS = {
    "Algol":     "malefic — intense, transformative, danger",
    "Alcyone":   "Pleiades — mystical grief, visionary",
    "Aldebaran": "royal star — integrity, success through honour",
    "Rigel":     "ambition, education, mechanical skill",
    "Betelgeuse": "success, fame, military honours",
    "Sirius":    "royal — ambition, passion, immortality",
    "Castor":    "intellect, creativity, sudden fame or fall",
    "Pollux":    "daring, audacious, cruelty or courage",
    "Regulus":   "royal star — success if revenge avoided",
    "Spica":     "benefic — gifts, talent, protection",
    "Arcturus":  "success through navigation and self-reliance",
    "Antares":   "royal star — obsession, recklessness, success",
    "Vega":      "charisma, idealism, artistic talent",
    "Fomalhaut": "royal star — idealism, spirituality, fame",
}

FIXED_STAR_ORB   = 1.5   # degrees
PARALLEL_ORB     = 1.0   # degrees

# Swiss Ephemeris equatorial flag (SEFLG_SPEED | SEFLG_EQUATORIAL)
EQUATORIAL_FLAG = 256 | 2048

# ─────────────────────────────────────────────
# Timezone
# ─────────────────────────────────────────────

_tf = TimezoneFinder()


def local_to_utc_hour(year: int, month: int, day: int,
                       local_hour: float, lat: float, lng: float) -> tuple:
    """
    Convert local birth time to UTC decimal hour using historical timezone data.
    Handles DST and all historical timezone changes automatically.
    Returns (utc_hour, tz_name).
    """
    tz_name  = _tf.timezone_at(lat=lat, lng=lng)
    if not tz_name:
        raise ValueError(f"Cannot determine timezone for ({lat}, {lng})")

    local_tz = pytz.timezone(tz_name)
    h = int(local_hour)
    m = int(round((local_hour - h) * 60))

    local_dt = local_tz.localize(datetime(year, month, day, h, m, 0), is_dst=None)
    utc_dt   = local_dt.astimezone(pytz.utc)

    return utc_dt.hour + utc_dt.minute / 60.0, tz_name


# ─────────────────────────────────────────────
# Planetary Calculations
# ─────────────────────────────────────────────

def calculate_elements_and_vibe(natal_planets, transit_aspects):
    """Calculates element balance and chooses a dominant color/vibe."""
    scores = {"Fire": 0, "Earth": 0, "Air": 0, "Water": 0}
    weights = {
        "Sun": 4, "Moon": 4, "Ascendant": 4, 
        "Mars": 2, "Venus": 2, "Mercury": 2, 
        "Jupiter": 1, "Saturn": 1, "Uranus": 1, "Neptune": 1, "Pluto": 1
    }

    # 1. Element Balance
    for p_name, p_data in natal_planets.items():
        if p_name in weights:
            # Get sign from name string (e.g. "Aries")
            sign_name = p_data["sign"]
            elem = ZODIAC_METADATA[sign_name]["element"]
            scores[elem] += weights[p_name]
    
    total = sum(scores.values())
    balance = {k: round((v / total) * 100) if total > 0 else 0 for k, v in scores.items()}

    # 2. Vibe Color (Dominant Planet Based on tightest Transit)
    dominant_planet = "Sun"
    if transit_aspects:
        sorted_aspects = sorted(transit_aspects, key=lambda x: x["orb"])
        dominant_planet = sorted_aspects[0]["transit_planet"]

    vibe_color = PLANET_METADATA.get(dominant_planet, PLANET_METADATA["Sun"])["color"]

    return balance, vibe_color, dominant_planet


def get_full_zodiac(deg):
    """Returns sign_name, deg_in_sign, and absolute_deg (0-360)."""
    deg = deg % 360
    sign_idx = int(deg // 30)
    sign_name = ZODIAC_SIGNS[sign_idx]
    deg_in_sign = deg % 30
    return sign_name, deg_in_sign, deg


def calculate_planetary_positions(julian_day: float) -> dict:
    """Ecliptic positions for all 14 bodies."""
    results = {}
    for name, planet_id in PLANETS_CONFIG.items():
        try:
            xx, _ = swe.calc_ut(julian_day, planet_id)
            lon   = xx[0]
            results[name] = {
                "longitude":     round(lon, 4),
                "sign":          ZODIAC_SIGNS[int(lon // 30)],
                "degree":        round(lon % 30, 2),
                "is_retrograde": xx[3] < 0,
            }
        except Exception:
            pass  # Body unavailable — skip gracefully
    return results


def calculate_declinations(julian_day: float) -> dict:
    """Equatorial declinations for all bodies (for parallel aspects)."""
    results = {}
    for name, planet_id in PLANETS_CONFIG.items():
        try:
            xx, _ = swe.calc_ut(julian_day, planet_id, EQUATORIAL_FLAG)
            results[name] = round(xx[1], 4)  # index 1 = declination
        except Exception:
            pass
    return results


def calculate_houses(julian_day: float, lat: float, lng: float) -> dict:
    """Placidus house cusps + ASC and MC."""
    cusps, ascmc = swe.houses(julian_day, lat, lng, b"P")
    return {
        "cusps": [round(c, 4) for c in cusps],
        "asc":   round(ascmc[0], 4),
        "mc":    round(ascmc[1], 4),
    }


def assign_house(planet_longitude: float, cusps: list) -> int:
    """Determine house number (1–12) for a given ecliptic longitude."""
    for i in range(12):
        start = cusps[i]
        end   = cusps[(i + 1) % 12]
        if start <= end:
            if start <= planet_longitude < end:
                return i + 1
        else:
            if planet_longitude >= start or planet_longitude < end:
                return i + 1
    return 12


from typing import Optional

def get_dignity(planet_name: str, sign_index: int) -> Optional[str]:
    """Return dignity string or None."""
    table = DIGNITY_TABLE.get(planet_name)
    if not table:
        return None
    for dignity, signs in table.items():
        if sign_index in signs:
            return dignity
    return None


# ─────────────────────────────────────────────
# Aspect Calculations
# ─────────────────────────────────────────────

def angular_difference(lon_a: float, lon_b: float) -> float:
    """Shortest arc between two longitudes (0–180°)."""
    diff = abs(lon_a - lon_b) % 360
    return diff if diff <= 180 else 360 - diff


def calculate_aspects(natal: dict, transit: dict) -> list:
    """All active major + minor aspects between two planet sets."""
    active = []
    for t_name, t_data in transit.items():
        for n_name, n_data in natal.items():
            diff = angular_difference(t_data["longitude"], n_data["longitude"])
            for asp_name, (exact, orb_limit) in ASPECTS.items():
                orb = abs(diff - exact)
                if orb <= orb_limit:
                    active.append({
                        "transit_planet": t_name,
                        "natal_planet":   n_name,
                        "aspect":         asp_name,
                        "orb":            round(orb, 2),
                        "is_major":       asp_name in MAJOR_ASPECTS,
                    })
    active.sort(key=lambda x: x["orb"])
    return active


def calculate_parallel_aspects(natal_decl: dict, transit_decl: dict) -> list:
    """
    Parallel: same declination (both N or both S) → like a conjunction.
    Contra-Parallel: equal but opposite declinations → like an opposition.
    """
    parallels = []
    for t_name, t_decl in transit_decl.items():
        for n_name, n_decl in natal_decl.items():
            par_orb  = abs(t_decl - n_decl)
            cpar_orb = abs(t_decl + n_decl)  # near 0 when values are equal & opposite

            if par_orb <= PARALLEL_ORB:
                parallels.append({
                    "transit_planet": t_name,
                    "natal_planet":   n_name,
                    "type":           "Parallel",
                    "orb":            round(par_orb, 2),
                })
            elif cpar_orb <= PARALLEL_ORB:
                parallels.append({
                    "transit_planet": t_name,
                    "natal_planet":   n_name,
                    "type":           "Contra-Parallel",
                    "orb":            round(cpar_orb, 2),
                })

    parallels.sort(key=lambda x: x["orb"])
    return parallels


# ─────────────────────────────────────────────
# Fixed Stars
# ─────────────────────────────────────────────

def calculate_fixed_star_conjunctions(natal_planets: dict, julian_day: float) -> list:
    """Find fixed stars conjunct natal planets within FIXED_STAR_ORB."""
    conjunctions = []
    for star_name, star_nature in FIXED_STARS.items():
        try:
            xx, _ = swe.fixstar_ut(star_name, julian_day)
            star_lon = xx[0]
            for planet_name, planet_data in natal_planets.items():
                diff = angular_difference(star_lon, planet_data["longitude"])
                if diff <= FIXED_STAR_ORB:
                    conjunctions.append({
                        "star":        star_name,
                        "nature":      star_nature,
                        "planet":      planet_name,
                        "orb":         round(diff, 2),
                    })
        except Exception:
            pass

    conjunctions.sort(key=lambda x: x["orb"])
    return conjunctions


# ─────────────────────────────────────────────
# Secondary Progressions
# ─────────────────────────────────────────────

def calculate_progressions(birth_jd: float, today_jd: float) -> dict:
    """
    Secondary progressions — day-for-a-year method.
    Age in years ≈ (today_jd - birth_jd) / 365.25
    Progressed JD = birth_jd + age_in_years (1 sidereal day per year)
    """
    age_years     = (today_jd - birth_jd) / 365.25
    progressed_jd = birth_jd + age_years
    return calculate_planetary_positions(progressed_jd)


# ─────────────────────────────────────────────
# Return Charts
# ─────────────────────────────────────────────

def find_solar_return(natal_sun_lon: float, today_jd: float) -> dict:
    """
    Solar Return: find the most recent and next time the Sun
    returns to its natal longitude.
    """
    try:
        # Search ~1 year back to find current year's solar return
        recent_jd = swe.solcross_ut(natal_sun_lon, today_jd - 366, 0)
        # Next solar return
        next_jd   = swe.solcross_ut(natal_sun_lon, today_jd + 1, 0)

        def jd_to_datestr(jd):
            y, mo, d, _ = swe.revjul(jd)
            return datetime(int(y), int(mo), int(d)).strftime("%B %d, %Y")

        return {
            "most_recent": jd_to_datestr(recent_jd),
            "next":        jd_to_datestr(next_jd),
        }
    except Exception as e:
        return {"error": str(e)}


def find_lunar_return(natal_moon_lon: float, today_jd: float) -> dict:
    """
    Lunar Return: find the next time the Moon returns to its natal longitude.
    Moon completes a cycle in ~29.5 days.
    """
    try:
        # Search from 30 days ago to catch a return that already started
        candidate_jd = swe.mooncross_ut(natal_moon_lon, today_jd - 30, 0)
        # If it's in the past, find the next one
        if candidate_jd < today_jd:
            candidate_jd = swe.mooncross_ut(natal_moon_lon, today_jd, 0)

        y, mo, d, _ = swe.revjul(candidate_jd)
        date_str     = datetime(int(y), int(mo), int(d)).strftime("%B %d, %Y")
        return {"next": date_str}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def longitude_to_label(lon: float) -> str:
    return f"{ZODIAC_SIGNS[int(lon // 30)]} {round(lon % 30, 2)}°"


# ─────────────────────────────────────────────
# AI Prompt Builder
# ─────────────────────────────────────────────

def build_ai_prompt(
    today_str:       str,
    natal_planets:   dict,
    natal_houses:    dict,
    transit_planets: dict,
    active_aspects:  list,
    parallel_aspects: list,
    fixed_star_conj: list,
    prog_planets:    dict,
    solar_return:    dict,
    lunar_return:    dict,
    resolved_city:   str,
    user_name:       str = "User",
    time_accuracy:   str = "known"
) -> str:
    cusps = natal_houses["cusps"]

    # ── Natal chart ────────────────────────────────────────────────────
    natal_lines = []
    for name, data in natal_planets.items():
        house_num   = assign_house(data["longitude"], cusps)
        sign_index  = int(data["longitude"] // 30)
        dignity     = get_dignity(name, sign_index)
        retro_tag   = " ℞" if data["is_retrograde"] else ""
        dignity_tag = f" [{dignity}]" if dignity else ""
        natal_lines.append(
            f"  {name}: {data['sign']} {data['degree']}° — "
            f"{HOUSE_NAMES[house_num - 1]}{retro_tag}{dignity_tag}"
        )
    natal_lines.append(f"  Ascendant: {longitude_to_label(natal_houses['asc'])}")
    natal_lines.append(f"  Midheaven: {longitude_to_label(natal_houses['mc'])}")

    # ── Transit chart ──────────────────────────────────────────────────
    transit_lines = []
    for name, data in transit_planets.items():
        retro_tag = " ℞" if data["is_retrograde"] else ""
        transit_lines.append(f"  {name}: {data['sign']} {data['degree']}°{retro_tag}")

    # ── Aspects (major first, then minor — top 12 total) ───────────────
    major = [a for a in active_aspects if a["is_major"]][:7]
    minor = [a for a in active_aspects if not a["is_major"]][:4]
    shown_aspects = major + minor

    if shown_aspects:
        aspect_lines = [
            f"  {'★' if a['is_major'] else '·'} "
            f"Transit {a['transit_planet']} {a['aspect']} "
            f"Natal {a['natal_planet']} (orb: {a['orb']}°)"
            for a in shown_aspects
        ]
    else:
        aspect_lines = ["  No aspects active. Energy is quiet and steady."]

    # ── Parallels ──────────────────────────────────────────────────────
    par_lines = [
        f"  Transit {p['transit_planet']} {p['type']} Natal {p['natal_planet']} (orb: {p['orb']}°)"
        for p in parallel_aspects[:5]
    ] or ["  None active."]

    # ── Fixed stars ────────────────────────────────────────────────────
    star_lines = [
        f"  {c['star']} ({c['nature']}) conjunct natal {c['planet']} (orb: {c['orb']}°)"
        for c in fixed_star_conj[:4]
    ] or ["  None within orb."]

    # ── Secondary progressions (inner 5) ──────────────────────────────
    inner = ["Sun", "Moon", "Mercury", "Venus", "Mars"]
    prog_lines = [
        f"  Progressed {name}: {prog_planets[name]['sign']} {prog_planets[name]['degree']}°"
        + (" ℞" if prog_planets[name]["is_retrograde"] else "")
        for name in inner if name in prog_planets
    ] or ["  Not available."]

    # ── Return charts ──────────────────────────────────────────────────
    sr_text = (
        f"Most recent: {solar_return.get('most_recent', 'N/A')} | "
        f"Next: {solar_return.get('next', 'N/A')}"
    )
    lr_text = lunar_return.get("next", "N/A")

    accuracy_note = ""
    if time_accuracy == "unknown":
        accuracy_note = "\n[CRITICAL NOTE]: The user DOES NOT KNOW their exact birth time. The time was defaulted to 12:00 PM. Do NOT make highly specific claims based on the Ascendant, Midheaven, or exact Moon degrees, as they may be inaccurate. Focus on the core Sun sign, major planets, and general aspects.\n"
    elif time_accuracy == "approx":
        accuracy_note = "\n[NOTE]: The user's birth time is APPROXIMATE. Ascendant and Moon degrees might be slightly off. Avoid over-interpreting exact house cusps.\n"

    return f"""Today's Date: {today_str}
User's Name: {user_name}
Birth Location: {resolved_city}{accuracy_note}

═══ NATAL CHART ═══
{chr(10).join(natal_lines)}

═══ TODAY'S SKY (Transits) ═══
{chr(10).join(transit_lines)}

═══ ACTIVE ASPECTS  (★ major  · minor) ═══
{chr(10).join(aspect_lines)}

═══ DECLINATION PARALLELS ═══
{chr(10).join(par_lines)}

═══ FIXED STAR CONJUNCTIONS ═══
{chr(10).join(star_lines)}

═══ SECONDARY PROGRESSIONS ═══
{chr(10).join(prog_lines)}

═══ RETURN CHARTS ═══
  Solar Return — {sr_text}
  Lunar Return (next) — {lr_text}

Please provide the daily astrological reading based solely on the data above.
"""


# ─────────────────────────────────────────────
# Input Validation
# ─────────────────────────────────────────────

def validate_birth_data(data: dict) -> tuple:
    int_fields = {"year": (1800, 2100), "month": (1, 12), "day": (1, 31)}
    for field, (lo, hi) in int_fields.items():
        if field not in data:
            return False, f"Missing required field: '{field}'"
        val = data[field]
        if not isinstance(val, (int, float)):
            return False, f"Field '{field}' must be a number."
        if not (lo <= val <= hi):
            return False, f"Field '{field}' value {val} is out of range ({lo}–{hi})."

    if "hour" not in data:
        return False, "Missing required field: 'hour'"
    hour = data["hour"]
    if not isinstance(hour, (int, float)) or not (0.0 <= hour <= 23.999):
        return False, "Field 'hour' must be a decimal between 0.0 and 23.999."

    if not data.get("city", "").strip():
        return False, "Missing required field: 'city'"

    return True, ""


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.route("/ask-astra", methods=["POST"])
@require_auth
def ask_astra():
    """
    Follow-up chat about a specific reading.
    Expected JSON: { reading_id, question }
    """
    if not db:
        return jsonify({"status": "error", "message": "Database not initialized"}), 500

    data     = request.get_json(silent=True)
    reading_id = data.get("reading_id")
    question   = data.get("question")

    if not reading_id or not question:
        return jsonify({"status": "error", "message": "Missing reading_id or question"}), 422

    uid = request.user["uid"]

    try:
        # 1. Fetch the context from Firestore
        reading_ref = db.collection("users").document(uid).collection("readings").document(reading_id)
        reading_doc = reading_ref.get()

        if not reading_doc.exists:
            return jsonify({"status": "error", "message": "Reading not found"}), 404

        reading_data = reading_doc.to_dict()
        prev_interpretation = reading_data.get("interpretation", "")
        astrology_snapshot  = reading_data.get("astrology_snapshot", {})

        # 2. Fetch user name for personalization
        user_name = "User"
        user_profile = db.collection("users").document(uid).get()
        if user_profile.exists:
            user_name = user_profile.to_dict().get("profile", {}).get("name", "User")

        # 3. Construct the chat prompt
        chat_prompt = f"""
CONTEXT FOR ASTRA:
User Name: {user_name}
Previous Interpretation: 
{prev_interpretation}

Detailed Technical Data of that moment:
{astrology_snapshot}

USER'S FOLLOW-UP QUESTION:
"{question}"

Astra, please answer the user's question directly, briefly, and warmly. Use the technical data to back up your answer, but keep the tone supportive and punchy. No generic advice; make it personal.
"""

        # 4. Call Gemini
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=chat_prompt,
            config=types.GenerateContentConfig(
                system_instruction=CHAT_SYSTEM_PROMPT,
                max_output_tokens=512,
            ),
        )

        answer = response.text

        # 5. Optional: Save the chat message back to history
        db.collection("users").document(uid).collection("readings").document(reading_id).collection("messages").add({
            "sender": "user",
            "text": question,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        db.collection("users").document(uid).collection("readings").document(reading_id).collection("messages").add({
            "sender": "astra",
            "text": answer,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        return jsonify({
            "status": "success",
            "answer": answer
        })

    except Exception as e:
        print(f"[Ask Astra Error] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/history", methods=["GET"])
@require_auth
def get_history():
    """
    Get user's reading history.
    Query params: limit (default 30)
    """
    if not db:
        return jsonify({"status": "error", "message": "Database not initialized"}), 500

    uid = request.user["uid"]
    limit = int(request.args.get("limit", 30))

    try:
        readings_ref = db.collection("users").document(uid).collection("readings")
        # Order by timestamp descending, limit results
        readings = readings_ref.order_by("timestamp", direction="DESCENDING").limit(limit).get()

        history = []
        for doc in readings:
            data = doc.to_dict()
            history.append({
                "date_id": doc.id,
                "timestamp": data.get("timestamp"),
                "interpretation": data.get("interpretation"),
            })

        return jsonify({
            "status": "success",
            "history": history,
        })

    except Exception as e:
        print(f"[History Error] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":          "ok",
        "server_time_utc": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/save-profile", methods=["POST"])
@require_auth
def save_profile():
    """
    Save user birth data and resolved geocoding to Firestore.
    Expected JSON: { year, month, day, hour, city }
    """
    if not db:
        return jsonify({"status": "error", "message": "Database not initialized"}), 500

    data = request.get_json(silent=True)
    is_valid, err = validate_birth_data(data)
    if not is_valid:
        return jsonify({"status": "error", "message": err}), 422

    uid = request.user["uid"]
    name = data.get("name", "User").strip()
    year, month, day = int(data["year"]), int(data["month"]), int(data["day"])
    local_hour = float(data["hour"])
    city = data.get("city", "Bilinmeyen Konum").strip()
    lat = data.get("lat")
    lng = data.get("lng")

    if lat is None or lng is None:
        return jsonify({"status": "error", "message": "Missing lat/lng"}), 422

    try:
        lat, lng = float(lat), float(lng)
        resolved_city = city
        utc_hour, tz_name = local_to_utc_hour(year, month, day, local_hour, lat, lng)

        profile_data = {
            "name": name,
            "year": year,
            "month": month,
            "day": day,
            "hour_local": local_hour,
            "birth_city": resolved_city,
            "lat": lat,
            "lng": lng,
            "utc_hour": round(utc_hour, 4),
            "timezone": tz_name,
            "time_accuracy": data.get("time_accuracy", "known"),
            "updated_at": firestore.SERVER_TIMESTAMP
        }

        # Save to Firestore
        db.collection("users").document(uid).set({"profile": profile_data}, merge=True)

        return jsonify({
            "status": "success",
            "message": "Profile saved successfully",
            "resolved_city": resolved_city
        })

    except Exception as e:
        print(f"[Save Profile Error] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/birth-chart", methods=["POST"])
@require_auth
@limiter.limit("5 per day")
def get_birth_chart():
    # ── 1. Parse & validate ────────────────────────────────────────────
    if not request.is_json:
        return jsonify({"status": "error", "message": "Request body must be JSON."}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"status": "error", "message": "Invalid JSON body."}), 400

    is_valid, err = validate_birth_data(data)
    if not is_valid:
        return jsonify({"status": "error", "message": err}), 422

    year       = int(data["year"])
    month      = int(data["month"])
    day        = int(data["day"])
    local_hour = float(data["hour"])
    city       = data.get("city", "Bilinmeyen Konum").strip()
    lat        = data.get("lat")
    lng        = data.get("lng")

    if lat is None or lng is None:
        return jsonify({"status": "error", "message": "Missing lat/lng"}), 422

    today_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    print(f"[{today_str}] Request → {year}-{month:02d}-{day:02d} {local_hour:.2f}h local | {city}")

    try:
        lat, lng = float(lat), float(lng)
        resolved_city = city
    except ValueError as e:
        return jsonify({"status": "error", "message": f"Invalid coordinates: {e}"}), 422

    # ── 3. Timezone → UTC ──────────────────────────────────────────────
    try:
        utc_hour, tz_name = local_to_utc_hour(year, month, day, local_hour, lat, lng)
        print(f"  Timezone: {tz_name} | Local {local_hour:.2f}h → UTC {utc_hour:.2f}h")
    except Exception as e:
        print(f"[Timezone Error] {e}")
        return jsonify({"status": "error", "message": f"Timezone resolution failed: {e}"}), 422

    # ── 4. Ephemeris calculations ──────────────────────────────────────
    try:
        birth_jd = swe.julday(year, month, day, utc_hour)

        now_utc    = datetime.now(timezone.utc)
        today_hour = now_utc.hour + now_utc.minute / 60.0
        today_jd   = swe.julday(now_utc.year, now_utc.month, now_utc.day, today_hour)

        # Positions
        natal_planets   = calculate_planetary_positions(birth_jd)
        transit_planets = calculate_planetary_positions(today_jd)

        # Houses (Placidus)
        natal_houses = calculate_houses(birth_jd, lat, lng)

        # Aspects (natal ↔ transit)
        active_aspects = calculate_aspects(natal_planets, transit_planets)

        # Declinations & parallels
        natal_decl    = calculate_declinations(birth_jd)
        transit_decl  = calculate_declinations(today_jd)
        par_aspects   = calculate_parallel_aspects(natal_decl, transit_decl)

        # Fixed star conjunctions
        fixed_star_conj = calculate_fixed_star_conjunctions(natal_planets, birth_jd)

        # Secondary progressions
        prog_planets = calculate_progressions(birth_jd, today_jd)

        # Return charts
        natal_sun_lon  = natal_planets.get("Sun", {}).get("longitude", 0)
        natal_moon_lon = natal_planets.get("Moon", {}).get("longitude", 0)
        solar_return   = find_solar_return(natal_sun_lon, today_jd)
        lunar_return   = find_lunar_return(natal_moon_lon, today_jd)

        print(f"  Aspects: {len(active_aspects)} | Parallels: {len(par_aspects)} | Fixed stars: {len(fixed_star_conj)}")

    except Exception as e:
        print(f"[Ephemeris Error] {e}")
        return jsonify({"status": "error", "message": "Planetary calculation failed."}), 500

    # ── 5. Build prompt & call Gemini ──────────────────────────────────
    user_name = data.get("name", "User")
    time_accuracy = data.get("time_accuracy", "known")
    user_content = build_ai_prompt(
        today_str, natal_planets, natal_houses, transit_planets,
        active_aspects, par_aspects, fixed_star_conj,
        prog_planets, solar_return, lunar_return, resolved_city,
        user_name=user_name, time_accuracy=time_accuracy
    )

    # DEBUG: Save outgoing prompt to a unique folder (disabled in production)
    if os.environ.get("DEBUG_MODE") == "true":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_folder = os.path.join("debug_logs", f"request_{timestamp}")
        os.makedirs(request_folder, exist_ok=True)

        with open(os.path.join(request_folder, "prompt.md"), "w") as f:
            f.write("# OUTGOING PROMPT\n\n")
            f.write(f"## System Instruction\n{SYSTEM_PROMPT}\n\n")
            f.write(f"## User Content\n{user_content}")

    try:
        print("Requesting interpretation from Gemini...")
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=1024,
            ),
        )
        interpretation = response.text

        # DEBUG: Save incoming response inside the same folder (disabled in production)
        if os.environ.get("DEBUG_MODE") == "true":
            with open(os.path.join(request_folder, "response.md"), "w") as f:
                f.write(interpretation)

        # Parse JSON response
        try:
            import json
            interpretation_json = json.loads(interpretation)
            
            # Validate required fields
            required_fields = ["summary", "highlights", "suggestions"]
            for field in required_fields:
                if field not in interpretation_json:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate highlights
            if not isinstance(interpretation_json["highlights"], list):
                raise ValueError("highlights must be a list")
            
            required_tags = {"health", "love", "career", "money", "beauty", "mind"}
            found_tags = {h["tag"] for h in interpretation_json["highlights"]}
            if not required_tags.issubset(found_tags):
                missing = required_tags - found_tags
                raise ValueError(f"Missing tags: {missing}")
            
            interpretation = interpretation_json
            print("  ✓ JSON parsed and validated successfully")
            
        except json.JSONDecodeError as e:
            print(f"[JSON Parse Error] {e}")
            return jsonify({"status": "error", "message": "AI response is not valid JSON"}), 502
        except ValueError as e:
            print(f"[JSON Validation Error] {e}")
            return jsonify({"status": "error", "message": f"Invalid JSON structure: {e}"}), 502
            
    except Exception as e:
        print(f"[Gemini Error] {e}")
        return jsonify({"status": "error", "message": "AI interpretation failed."}), 502

    # ── 6. Serialize response ──────────────────────────────────────────
    cusps = natal_houses["cusps"]

    natal_response = {
        name: {
            "sign":          d["sign"],
            "degree":        d["degree"],
            "house":         assign_house(d["longitude"], cusps),
            "is_retrograde": d["is_retrograde"],
            "dignity":       get_dignity(name, int(d["longitude"] // 30)),
            "declination":   natal_decl.get(name),
        }
        for name, d in natal_planets.items()
    }

    transit_response = {
        name: {
            "sign":          d["sign"],
            "degree":        d["degree"],
            "is_retrograde": d["is_retrograde"],
            "declination":   transit_decl.get(name),
        }
        for name, d in transit_planets.items()
    }

    prog_response = {
        name: {
            "sign":          d["sign"],
            "degree":        d["degree"],
            "is_retrograde": d["is_retrograde"],
        }
        for name, d in prog_planets.items()
        if name in {"Sun", "Moon", "Mercury", "Venus", "Mars"}
    }

    # ── 7. Save to History ───────────────────────────────────────────────
    # Use the current UTC date as the document ID to prevent duplicates for the same day
    date_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reading_id = date_id

    try:
        if db:
            uid = request.user["uid"]
            astrology_snapshot = {
                "natal_chart": natal_response,
                "transit_chart": transit_response,
                "aspects": active_aspects[:10]
            }

            # Use .document(date_id).set() to overwrite/ensure only one reading per day
            db.collection("users").document(uid).collection("readings").document(date_id).set({
                "timestamp": firestore.SERVER_TIMESTAMP,
                "interpretation": interpretation,
                "astrology_snapshot": astrology_snapshot,
                "date_id": date_id
            })
            print(f"  ✓ Reading saved/updated for UID: {uid} with ID: {date_id}")
    except Exception as db_err:
        print(f"  ⚠ Failed to save history: {db_err}")

    return jsonify({
        "status":          "success",
        "reading_id":      reading_id,
        "server_date_utc": today_str,
        "birth_data": {
            "year": year, "month": month, "day": day,
            "hour_local": local_hour, "hour_utc": round(utc_hour, 4),
            "timezone": tz_name, "city": resolved_city,
            "lat": lat, "lng": lng,
        },
        "natal_chart": {
            "planets":   natal_response,
            "ascendant": longitude_to_label(natal_houses["asc"]),
            "midheaven": longitude_to_label(natal_houses["mc"]),
        },
        "transit_chart": {
            "planets": transit_response,
        },
        "progressed_chart": {
            "planets": prog_response,
        },
        "active_aspects":    active_aspects,
        "parallel_aspects":  par_aspects,
        "fixed_star_conjunctions": fixed_star_conj,
        "solar_return":      solar_return,
        "lunar_return":      lunar_return,
        "interpretation":    interpretation,
    })


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print(f"🔮 Astra Birth Chart Server starting on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)