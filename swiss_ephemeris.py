import swisseph as swe
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────
# Constants & Metadata
# ─────────────────────────────────────────────

ZODIAC_METADATA = {
    "Aries":     {"element": "Fire",  "ruler": "Mars"},
    "Taurus":    {"element": "Earth", "ruler": "Venus"},
    "Gemini":    {"element": "Air",   "ruler": "Mercury"},
    "Cancer":    {"element": "Water", "ruler": "Moon"},
    "Leo":       {"element": "Fire",  "ruler": "Sun"},
    "Virgo":     {"element": "Earth", "ruler": "Mercury"},
    "Libra":     {"element": "Air",   "ruler": "Venus"},
    "Scorpio":   {"element": "Water", "ruler": "Pluto"},
    "Sagittarius": {"element": "Fire",  "ruler": "Jupiter"},
    "Capricorn": {"element": "Earth", "ruler": "Saturn"},
    "Aquarius":  {"element": "Air",   "ruler": "Uranus"},
    "Pisces":    {"element": "Water", "ruler": "Neptune"},
}

PLANET_METADATA = {
    "Sun":     {"color": 0xFFFFD700, "symbol": "☉"},
    "Moon":    {"color": 0xFFC0C0C0, "symbol": "☽"},
    "Mercury": {"color": 0xFFADD8E6, "symbol": "☿"},
    "Venus":   {"color": 0xFFE6E6FA, "symbol": "♀"},
    "Mars":    {"color": 0xFFFF4500, "symbol": "♂"},
    "Jupiter": {"color": 0xFFDAA520, "symbol": "♃"},
    "Saturn":  {"color": 0xFF808080, "symbol": "♄"},
    "Uranus":  {"color": 0xFF40E0D0, "symbol": "♅"},
    "Neptune": {"color": 0xFF4169E1, "symbol": "♆"},
    "Pluto":   {"color": 0xFF8B0000, "symbol": "♇"},
    "Lilith":  {"color": 0xFF800080, "symbol": "☋"},
}

PLANETS_CONFIG = {
    "Sun":     swe.SUN,
    "Moon":    swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus":   swe.VENUS,
    "Mars":    swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn":  swe.SATURN,
    "Uranus":  swe.URANUS,
    "Neptune": swe.NEPTUNE,
    "Pluto":   swe.PLUTO,
    "Lilith":  swe.MEAN_APOG,
}

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

ASPECTS = {
    "Conjunction":      (0,   10),
    "Semi-Sextile":    (30,  3),
    "Sextile":         (60,  6),
    "Square":          (90,  8),
    "Trine":           (120, 8),
    "Sesquiquadrate":  (135, 3),
    "Quincunx":        (150, 3),
    "Opposition":      (180, 10),
}

MAJOR_ASPECTS = {"Conjunction", "Square", "Trine", "Opposition"}

DIGNITY_TABLE = {
    "Sun":     {"Domicile": [0], "Exaltation": [4], "Detriment": [6], "Fall": [10]},
    "Moon":    {"Domicile": [3], "Exaltation": [1], "Detriment": [9], "Fall": [7]},
    "Mercury": {"Domicile": [1, 4], "Exaltation": [5], "Detriment": [7, 10], "Fall": [11]},
    "Venus":   {"Domicile": [1, 11], "Exaltation": [1], "Detriment": [5, 7], "Fall": [7]},
    "Mars":    {"Domicile": [0], "Exaltation": [9], "Detriment": [6], "Fall": [3]},
    "Jupiter": {"Domicile": [8], "Exaltation": [3], "Detriment": [2], "Fall": [9]},
    "Saturn":  {"Domicile": [9], "Exaltation": [10], "Detriment": [3], "Fall": [4]},
}

FIXED_STARS = {
    "Algol":         "malefic",
    "Sirius":        "benefic",
    "Regulus":       "royal",
    "Antares":       "royal",
    "Spica":         "benefic",
    "Vega":          "benefic",
}

PARALLEL_ORB = 1.0
FIXED_STAR_ORB = 2.0
EQUATORIAL_FLAG = swe.FLG_EQUATORIAL

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

    for p_name, p_data in natal_planets.items():
        if p_name in weights:
            sign_name = p_data["sign"]
            elem = ZODIAC_METADATA[sign_name]["element"]
            scores[elem] += weights[p_name]
    
    total = sum(scores.values())
    balance = {k: round((v / total) * 100) if total > 0 else 0 for k, v in scores.items()}

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
            pass
    return results


def calculate_declinations(julian_day: float) -> dict:
    """Equatorial declinations for all bodies (for parallel aspects)."""
    results = {}
    for name, planet_id in PLANETS_CONFIG.items():
        try:
            xx, _ = swe.calc_ut(julian_day, planet_id, EQUATORIAL_FLAG)
            results[name] = round(xx[1], 4)
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
            cpar_orb = abs(t_decl + n_decl)

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
        recent_jd = swe.solcross_ut(natal_sun_lon, today_jd - 366, 0)
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
        candidate_jd = swe.mooncross_ut(natal_moon_lon, today_jd - 30, 0)
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
