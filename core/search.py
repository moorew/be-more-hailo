import logging
try:
    from ddgs import DDGS  # new package name (pip install ddgs)
except ImportError:
    from duckduckgo_search import DDGS  # fallback for older installs

logger = logging.getLogger(__name__)

DEFAULT_WEATHER_LOCATION = "Brantford"
# "in the morning", "in an hour"... are times, not places.
_NOT_PLACES = ("the ", "a ", "an ", "my ", "this ", "next ", "today", "tomorrow", "tonight",
               "morning", "afternoon", "evening", "here", "outside")


def _weather_location(query_lower: str) -> str:
    if " in " not in f" {query_lower}":
        return DEFAULT_WEATHER_LOCATION
    place = f" {query_lower}".split(" in ", 1)[1]
    place = place.split(",")[0].split("?")[0].split(" today")[0].split(" tomorrow")[0].strip(" .!")
    if not place or place.startswith(_NOT_PLACES) or len(place.split()) > 3:
        return DEFAULT_WEATHER_LOCATION
    return place


def _day_stats(day: dict) -> dict:
    """One day from wttr.in j1 JSON: daytime condition, high/low (int °C), rain chance."""
    daytime = [h for h in day["hourly"] if 900 <= int(h["time"]) <= 1800] or day["hourly"]
    descs = [h["weatherDesc"][0]["value"].strip() for h in daytime]
    codes = {h["weatherDesc"][0]["value"].strip(): h.get("weatherCode") for h in daytime}
    desc = max(set(descs), key=descs.count)
    return {"date": day["date"], "desc": desc, "code": codes.get(desc),
            "high": int(day["maxtempC"]), "low": int(day["mintempC"]),
            "rain": max(int(h.get("chanceofrain", 0)) for h in daytime)}


def _day_summary(day: dict) -> str:
    d = _day_stats(day)
    return f"{d['desc']}, high {d['high']}°C, low {d['low']}°C, {d['rain']}% chance of rain"


def fetch_j1(location: str, timeout: float = 5):
    """Raw wttr.in j1 JSON (metric) for `location`, or None on any failure."""
    import requests
    try:
        resp = requests.get(f"https://wttr.in/{location.replace(' ', '+')}?format=j1&m", timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        logger.warning(f"wttr.in Weather Error: {e}")
        return None


def get_weather(query: str):
    """Current conditions + 3-day forecast as ONE short line, or None on failure.

    Kept to ~300 chars on purpose: the old wttr.in v2 table was ~18k chars of
    ASCII art that a 1.7B model can't read and that overflows hailo-ollama's
    ~2k-token context (the request is silently dropped).  Includes tomorrow so
    "what's it doing tomorrow?" gets real data instead of an invented answer."""
    import datetime
    location = _weather_location(query.lower())
    data = fetch_j1(location)
    if data is None:
        return None
    try:
        now = data["current_condition"][0]
        days = data["weather"]
        parts = [f"Weather in {location.title()}: now {now['weatherDesc'][0]['value'].strip()}, "
                 f"{now['temp_C']}°C (feels like {now['FeelsLikeC']}°C)"]
        labels = ["Today", "Tomorrow"]
        for i, day in enumerate(days[:3]):
            label = labels[i] if i < 2 else datetime.date.fromisoformat(day["date"]).strftime("%A")
            parts.append(f"{label}: {_day_summary(day)}")
        logger.info(f"Weather fetched from wttr.in: {location}")
        return ". ".join(parts) + "."
    except Exception as e:
        logger.warning(f"wttr.in Weather Error: {e}")
        return None


def search_web(query: str) -> str:
    """
    Searches DuckDuckGo for the given query and returns a summary of the top result.
    Special cases: Weather uses wttr.in for better accuracy.
    """
    logger.info(f"Searching web for: {query}")
    query_lower = query.lower()
    
    # 0. Special Case: Weather
    if "weather" in query_lower:
        weather = get_weather(query)
        if weather:
            return weather
        # Fall through to DDG if wttr.in fails

    try:
        with DDGS(timeout=10) as ddgs:
            results = []
            
            # Use Canadian region if Ontario is mentioned or if it's a general request in this fork
            # This makes BMO feel more local to the user's setup.
            region = 'ca-en' if any(k in query_lower for k in ['ontario', 'canada', 'brantford', 'toronto']) else 'wt-wt'
            
            # 1. Try News search first for current events (skip for weather)
            if any(k in query_lower for k in ["news", "latest", "today", "happening", "current"]):
                try:
                    logger.info(f"Searching News (region={region})...")
                    results = list(ddgs.news(query, region=region, max_results=5))
                    if results:
                        logger.info(f"Found {len(results)} news items.")
                except Exception as e:
                    logger.warning(f"News Search Error: {e}")
            
            # 2. Fallback to Text search
            if not results:
                logger.info(f"Trying text search (region={region})...")
                try:
                    results = list(ddgs.text(query, region=region, max_results=3))
                    if results:
                        logger.info(f"Found Text: {results[0].get('title')}")
                except Exception as e:
                    logger.warning(f"Text Search Error: {e}")

            if results:
                # Combine up to 3 results for richer context
                parts = []
                for r in results[:3]:
                    title = r.get('title', 'No Title')
                    body = r.get('body', r.get('snippet', 'No Body'))
                    parts.append(f"Title: {title}\nSnippet: {body[:400]}")
                return f"SEARCH RESULTS for '{query}':\n" + "\n---\n".join(parts)
            else:
                logger.info("Search returned 0 results.")
                return "SEARCH_EMPTY"
                
    except Exception as e:
        logger.error(f"Connection/Library Error during search: {e}")
        return "SEARCH_ERROR"

def search_images(query: str) -> str:
    """
    Searches DuckDuckGo for the given query and returns the first image URL.
    """
    logger.info(f"Searching images for: {query}")
    try:
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.images(query, max_results=1))
            if results:
                image_url = results[0].get('image')
                logger.info(f"Found Image: {image_url}")
                return image_url
            else:
                logger.info("Image search returned 0 results.")
                return ""
    except Exception as e:
        logger.error(f"Image Search Error: {e}")
        return ""
