"""Cuaca dan kualitas udara waktu nyata dari Open-Meteo (tanpa API key).

* Prakiraan/cuaca saat ini : https://api.open-meteo.com/v1/forecast
* Kualitas udara           : https://air-quality-api.open-meteo.com/v1/air-quality
Data diambil di sisi server dan di-cache; dashboard hanya membaca dari server ini.
"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

from .config import Config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WMO weather code -> (teks Indonesia, kunci ikon)
WMO = {
    0: ("Cerah", "clear"), 1: ("Cerah berawan", "partly"), 2: ("Berawan sebagian", "partly"), 3: ("Berawan", "cloudy"),
    45: ("Berkabut", "fog"), 48: ("Kabut rime", "fog"),
    51: ("Gerimis ringan", "drizzle"), 53: ("Gerimis", "drizzle"), 55: ("Gerimis lebat", "drizzle"),
    56: ("Gerimis beku", "drizzle"), 57: ("Gerimis beku lebat", "drizzle"),
    61: ("Hujan ringan", "rain"), 63: ("Hujan sedang", "rain"), 65: ("Hujan lebat", "rain"),
    66: ("Hujan beku", "rain"), 67: ("Hujan beku lebat", "rain"),
    71: ("Salju ringan", "snow"), 73: ("Salju", "snow"), 75: ("Salju lebat", "snow"), 77: ("Butir salju", "snow"),
    80: ("Hujan lokal ringan", "rain"), 81: ("Hujan lokal", "rain"), 82: ("Hujan lokal lebat", "rain"),
    85: ("Hujan salju", "snow"), 86: ("Hujan salju lebat", "snow"),
    95: ("Badai petir", "storm"), 96: ("Badai petir, hujan es", "storm"), 99: ("Badai petir lebat, hujan es", "storm"),
}

CURRENT_VARS = ("temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,"
                "cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,is_day")
HOURLY_VARS = "temperature_2m,precipitation_probability,precipitation,weather_code"
AIR_VARS = "us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone"


def _get_json(url: str, params: dict, timeout: float = 10.0) -> dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full, headers={"User-Agent": "EmisiSenseVision/1.0 (Lab AQHI UB)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def describe(code, is_day=1) -> dict:
    text, icon = WMO.get(int(code) if code is not None else -1, ("Tidak diketahui", "cloudy"))
    if icon in ("clear", "partly") and not is_day:
        icon += "_night"
    return {"text": text, "icon": icon}


def parse_forecast(js: dict) -> dict:
    cur = dict(js.get("current") or {})
    cur["desc"] = describe(cur.get("weather_code"), cur.get("is_day", 1))
    h = js.get("hourly") or {}
    times = h.get("time") or []
    now_iso = (cur.get("time") or "")[:13]
    start = next((i for i, t in enumerate(times) if t[:13] >= now_iso), 0) if times else 0
    hourly = []
    for i in range(start, min(start + 13, len(times))):
        hourly.append({"time": times[i], "temp": (h.get("temperature_2m") or [None] * len(times))[i],
                       "pop": (h.get("precipitation_probability") or [None] * len(times))[i],
                       "rain": (h.get("precipitation") or [None] * len(times))[i],
                       "desc": describe((h.get("weather_code") or [None] * len(times))[i], 1)})
    return {"current": cur, "units": js.get("current_units") or {}, "hourly": hourly,
            "timezone": js.get("timezone"), "elevation": js.get("elevation")}


class WeatherService:
    def __init__(self, cfg: Config, interval: float = 60.0, demo: bool = False, on_data=None, on_wind=None):
        self.on_data = on_data
        self.on_wind = on_wind          # callback(rows, loc): riwayat angin per jam untuk mawar angin
        self.cfg = cfg
        self.interval = interval
        self.demo = demo
        self._lock = threading.Lock()
        self._data: dict = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_loc = None
        self._thread = threading.Thread(target=self._loop, daemon=True, name="weather")

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set(); self._wake.set()

    def refresh(self):
        self._wake.set()

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)

    def _wind_history(self, loc: dict, demo: bool):
        """Ambil riwayat angin 30 hari terakhir (per jam) agar mawar angin langsung terisi."""
        if not self.on_wind:
            return
        try:
            if demo:
                from .wind import demo_history
                rows = demo_history()
            else:
                js = _get_json(FORECAST_URL, {"latitude": loc["lat"], "longitude": loc["lon"], "timezone": "GMT", "timeformat": "unixtime",
                                              "past_days": 30, "forecast_days": 1,
                                              "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
                h, now = js.get("hourly") or {}, time.time()
                rows = [(t, s_, d_, g_) for t, s_, d_, g_ in zip(h.get("time", []), h.get("wind_speed_10m", []), h.get("wind_direction_10m", []),
                                                                 h.get("wind_gusts_10m", [])) if t <= now and s_ is not None and d_ is not None]
            self.on_wind(rows, loc)
            self._wind_t, self._wind_loc = time.time(), (loc["lat"], loc["lon"])
        except Exception:
            pass

    def _loop(self):
        last_air = 0.0
        self._wind_t, self._wind_loc = 0.0, None
        while not self._stop.is_set():
            loc = self.cfg["location"]
            if self._wind_loc != (loc["lat"], loc["lon"]) or time.time() - self._wind_t > 6 * 3600:
                self._wind_history(loc, self.demo)
            try:
                if self.demo:
                    data = demo_weather(loc)
                else:
                    data = self._fetch(loc, fetch_air=(time.time() - last_air > 240 or self._last_loc != (loc["lat"], loc["lon"])))
                    last_air = time.time() if data.get("air_quality") else last_air
                with self._lock:
                    prev = self._data
                    if not data.get("air_quality") and prev.get("air_quality") and not self.demo:
                        data["air_quality"], data["air_units"] = prev["air_quality"], prev.get("air_units", {})
                    data.update(location=loc, updated=datetime.now().astimezone().isoformat(timespec="seconds"),
                                error=None, source="demo" if self.demo else "Open-Meteo")
                    self._data = data
                if self.on_data:
                    try:
                        self.on_data(dict(data))
                    except Exception:
                        pass
                self._last_loc = (loc["lat"], loc["lon"])
            except Exception as exc:
                with self._lock:
                    self._data = {**self._data, "error": f"{type(exc).__name__}: {exc}", "location": loc}
            self._wake.wait(self.interval)
            self._wake.clear()

    def _fetch(self, loc: dict, fetch_air: bool) -> dict:
        base = {"latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto"}
        out = parse_forecast(_get_json(FORECAST_URL, {**base, "current": CURRENT_VARS, "hourly": HOURLY_VARS, "forecast_hours": 13}))
        if fetch_air:
            try:
                aq = _get_json(AIR_URL, {**base, "current": AIR_VARS})
                out["air_quality"] = aq.get("current") or {}
                out["air_units"] = aq.get("current_units") or {}
            except Exception:
                out["air_quality"] = {}
        return out


def demo_weather(loc: dict) -> dict:
    """Data contoh (bentuk sama dengan Open-Meteo) untuk mode --demo atau saat offline."""
    now = datetime.now().astimezone()
    cur = {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 28.4, "relative_humidity_2m": 71, "apparent_temperature": 31.2,
           "precipitation": 0.0, "weather_code": 2, "cloud_cover": 46, "pressure_msl": 1010.2,
           "wind_speed_10m": round(9.4 + 3 * math.sin(now.timestamp() / 900), 1),
           "wind_direction_10m": round((135 + 50 * math.sin(now.timestamp() / 1800)) % 360), "wind_gusts_10m": 18.0, "is_day": 1}
    cur["desc"] = describe(2, 1)
    hourly = []
    for i in range(13):
        hr = (now.hour + i) % 24
        temp = round(24 + 6 * max(0.0, 1 - abs(hr - 13) / 7), 1)
        pop = 10 + (45 if 15 <= hr <= 18 else 0)
        hourly.append({"time": f"{hr:02d}:00", "temp": temp, "pop": pop, "rain": 0.6 if pop > 40 else 0.0,
                       "desc": describe(61 if pop > 40 else 2, 1)})
    return {"current": cur, "units": {"temperature_2m": "°C", "relative_humidity_2m": "%", "wind_speed_10m": "km/h", "pressure_msl": "hPa",
                                      "precipitation": "mm", "apparent_temperature": "°C", "cloud_cover": "%"},
            "hourly": hourly, "air_quality": {"us_aqi": 62, "pm2_5": 17.8, "pm10": 31.5, "carbon_monoxide": 310.0, "nitrogen_dioxide": 21.4,
                                              "sulphur_dioxide": 6.2, "ozone": 48.0},
            "air_units": {"pm2_5": "μg/m³", "pm10": "μg/m³", "carbon_monoxide": "μg/m³", "nitrogen_dioxide": "μg/m³",
                          "sulphur_dioxide": "μg/m³", "ozone": "μg/m³", "us_aqi": "USAQI"}}
