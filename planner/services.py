from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Iterable

import requests


AVERAGE_SPEED_MPH = 55
MAX_DRIVE_HOURS = 11
MAX_DUTY_WINDOW_HOURS = 14
BREAK_AFTER_DRIVING_HOURS = 8
BREAK_DURATION_HOURS = 0.5
DAILY_RESET_HOURS = 10
CYCLE_LIMIT_HOURS = 70
FUEL_INTERVAL_MILES = 1000
FUEL_STOP_HOURS = 0.5
PICKUP_DROPOFF_HOURS = 1

KNOWN_LOCATIONS = {
    "new york": (40.7128, -74.0060),
    "nyc": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "la": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298),
    "houston": (29.7604, -95.3698),
    "phoenix": (33.4484, -112.0740),
    "philadelphia": (39.9526, -75.1652),
    "san antonio": (29.4241, -98.4936),
    "san diego": (32.7157, -117.1611),
    "dallas": (32.7767, -96.7970),
    "san jose": (37.3382, -121.8863),
    "austin": (30.2672, -97.7431),
    "jacksonville": (30.3322, -81.6557),
    "fort worth": (32.7555, -97.3308),
    "columbus": (39.9612, -82.9988),
    "charlotte": (35.2271, -80.8431),
    "indianapolis": (39.7684, -86.1581),
    "san francisco": (37.7749, -122.4194),
    "seattle": (47.6062, -122.3321),
    "denver": (39.7392, -104.9903),
    "atlanta": (33.7490, -84.3880),
    "miami": (25.7617, -80.1918),
    "boston": (42.3601, -71.0589),
    "detroit": (42.3314, -83.0458),
    "nashville": (36.1627, -86.7816),
    "memphis": (35.1495, -90.0490),
    "kansas city": (39.0997, -94.5786),
    "st louis": (38.6270, -90.1994),
    "salt lake city": (40.7608, -111.8910),
    "las vegas": (36.1699, -115.1398),
    "portland": (45.5152, -122.6784),
}


@dataclass
class Location:
    label: str
    lat: float
    lng: float
    source: str


@dataclass
class Event:
    start: datetime
    end: datetime
    status: str
    label: str
    location: str
    miles: float = 0

    @property
    def duration_hours(self) -> float:
        return round((self.end - self.start).total_seconds() / 3600, 2)


def geocode(label: str) -> Location:
    clean = label.strip()
    if not clean:
        raise ValueError("Location is required.")

    normalized = clean.lower().replace(".", "")
    known = KNOWN_LOCATIONS.get(normalized) or KNOWN_LOCATIONS.get(normalized.split(",")[0].strip())
    if known:
        return Location(clean, known[0], known[1], "known-city")

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": clean, "format": "json", "limit": 1},
            headers={"User-Agent": "spotter-hos-planner/1.0"},
            timeout=6,
        )
        response.raise_for_status()
        data = response.json()
        if data:
            return Location(clean, float(data[0]["lat"]), float(data[0]["lon"]), "nominatim")
    except requests.RequestException:
        pass

    # Stable fallback keeps demos working without network access.
    seed = sum(ord(ch) for ch in clean)
    lat = 25 + (seed % 2200) / 100
    lng = -124 + (seed % 5600) / 100
    return Location(clean, round(lat, 4), round(lng, 4), "fallback")


def haversine_miles(a: Location, b: Location) -> float:
    radius = 3958.8
    dlat = radians(b.lat - a.lat)
    dlng = radians(b.lng - a.lng)
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    root = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return radius * 2 * atan2(sqrt(root), sqrt(1 - root))


def route_leg(a: Location, b: Location) -> dict:
    try:
        coords = f"{a.lng},{a.lat};{b.lng},{b.lat}"
        response = requests.get(
            f"https://router.project-osrm.org/route/v1/driving/{coords}",
            params={"overview": "full", "geometries": "geojson"},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        route = data["routes"][0]
        distance = route["distance"] / 1609.344
        geometry = [[lat, lng] for lng, lat in route["geometry"]["coordinates"]]
        return {"distance_miles": round(distance, 1), "geometry": geometry, "source": "osrm"}
    except (requests.RequestException, KeyError, IndexError):
        distance = haversine_miles(a, b) * 1.18
        return {
            "distance_miles": round(distance, 1),
            "geometry": [[a.lat, a.lng], [b.lat, b.lng]],
            "source": "estimated",
        }


def simplify_geometry(points: list[list[float]], max_points: int = 500) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    simplified = points[::step]
    if simplified[-1] != points[-1]:
        simplified.append(points[-1])
    return simplified


def interpolate_label(start: Location, end: Location, ratio: float) -> str:
    lat = start.lat + (end.lat - start.lat) * ratio
    lng = start.lng + (end.lng - start.lng) * ratio
    return f"Near {lat:.2f}, {lng:.2f}"


def add_event(events: list[Event], cursor: datetime, hours: float, status: str, label: str, location: str, miles: float = 0) -> datetime:
    end = cursor + timedelta(hours=hours)
    events.append(Event(cursor, end, status, label, location, miles))
    return end


def schedule_drive_leg(
    events: list[Event],
    cursor: datetime,
    start: Location,
    end: Location,
    distance_miles: float,
    cycle_remaining: float,
    leg_label: str,
) -> tuple[datetime, float]:
    miles_left = distance_miles
    driven_since_break = 0.0
    driving_today = 0.0
    duty_today = 0.0
    miles_since_fuel = 0.0
    total_leg_miles = max(distance_miles, 1)

    while miles_left > 0.1:
        if cycle_remaining <= 0.05:
            cursor = add_event(events, cursor, 34, "off", "34-hour cycle restart", "Rest area")
            cycle_remaining = CYCLE_LIMIT_HOURS
            driving_today = 0
            duty_today = 0
            driven_since_break = 0

        if driving_today >= MAX_DRIVE_HOURS or duty_today >= MAX_DUTY_WINDOW_HOURS:
            cursor = add_event(events, cursor, DAILY_RESET_HOURS, "sleeper", "10-hour sleeper berth reset", "Truck stop")
            driving_today = 0
            duty_today = 0
            driven_since_break = 0
            continue

        if driven_since_break >= BREAK_AFTER_DRIVING_HOURS:
            status = "on" if miles_since_fuel >= FUEL_INTERVAL_MILES else "off"
            label = "Fuel and 30-minute break" if status == "on" else "30-minute rest break"
            ratio = 1 - miles_left / total_leg_miles
            cursor = add_event(events, cursor, BREAK_DURATION_HOURS, status, label, interpolate_label(start, end, ratio))
            duty_today += BREAK_DURATION_HOURS if status == "on" else 0
            cycle_remaining -= BREAK_DURATION_HOURS if status == "on" else 0
            driven_since_break = 0
            miles_since_fuel = 0 if status == "on" else miles_since_fuel
            continue

        max_hours = min(
            MAX_DRIVE_HOURS - driving_today,
            BREAK_AFTER_DRIVING_HOURS - driven_since_break,
            max(0, MAX_DUTY_WINDOW_HOURS - duty_today),
            max(0, cycle_remaining),
            miles_left / AVERAGE_SPEED_MPH,
            max(0.25, (FUEL_INTERVAL_MILES - miles_since_fuel) / AVERAGE_SPEED_MPH),
        )

        if max_hours <= 0.05:
            continue

        miles = min(miles_left, max_hours * AVERAGE_SPEED_MPH)
        ratio = 1 - (miles_left - miles) / total_leg_miles
        cursor = add_event(events, cursor, max_hours, "driving", f"Drive {leg_label}", interpolate_label(start, end, ratio), miles)
        miles_left -= miles
        driving_today += max_hours
        duty_today += max_hours
        driven_since_break += max_hours
        cycle_remaining -= max_hours
        miles_since_fuel += miles

        if miles_since_fuel >= FUEL_INTERVAL_MILES - 1 and miles_left > 0.1:
            ratio = 1 - miles_left / total_leg_miles
            cursor = add_event(events, cursor, FUEL_STOP_HOURS, "on", "Fuel stop", interpolate_label(start, end, ratio))
            duty_today += FUEL_STOP_HOURS
            cycle_remaining -= FUEL_STOP_HOURS
            driven_since_break = 0
            miles_since_fuel = 0

    return cursor, cycle_remaining


def split_by_day(events: Iterable[Event]) -> list[dict]:
    days: dict[date, list[Event]] = {}
    for event in events:
        cursor = event.start
        while cursor < event.end:
            day_end = datetime.combine(cursor.date() + timedelta(days=1), time.min)
            chunk_end = min(day_end, event.end)
            split = Event(cursor, chunk_end, event.status, event.label, event.location, event.miles * ((chunk_end - cursor) / (event.end - event.start)))
            days.setdefault(cursor.date(), []).append(split)
            cursor = chunk_end

    log_days = []
    for day, chunks in sorted(days.items()):
        chunks = sorted(chunks, key=lambda item: item.start)
        day_start = datetime.combine(day, time.min)
        day_end = datetime.combine(day + timedelta(days=1), time.min)
        complete_chunks: list[Event] = []
        cursor = day_start
        for chunk in chunks:
            if chunk.start > cursor:
                complete_chunks.append(Event(cursor, chunk.start, "off", "Off duty", ""))
            complete_chunks.append(chunk)
            cursor = max(cursor, chunk.end)
        if cursor < day_end:
            complete_chunks.append(Event(cursor, day_end, "off", "Off duty", ""))

        totals = {"off": 0, "sleeper": 0, "driving": 0, "on": 0}
        miles = 0
        for chunk in complete_chunks:
            totals[chunk.status] += chunk.duration_hours
            miles += chunk.miles
        log_days.append(
            {
                "date": day.isoformat(),
                "totals": {key: round(value, 2) for key, value in totals.items()},
                "miles": round(miles),
                "events": [serialize_event(chunk) for chunk in complete_chunks],
            }
        )
    return log_days


def serialize_event(event: Event) -> dict:
    end_hour = event.end.hour + event.end.minute / 60
    if event.end.time() == time.min and event.end.date() > event.start.date():
        end_hour = 24

    return {
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "startHour": event.start.hour + event.start.minute / 60,
        "endHour": end_hour,
        "status": event.status,
        "label": event.label,
        "location": event.location,
        "miles": round(event.miles, 1),
        "durationHours": event.duration_hours,
    }


def plan_trip(payload: dict) -> dict:
    current = geocode(payload["currentLocation"])
    pickup = geocode(payload["pickupLocation"])
    dropoff = geocode(payload["dropoffLocation"])
    cycle_used = float(payload.get("currentCycleUsed", 0))
    cycle_remaining = max(0, CYCLE_LIMIT_HOURS - cycle_used)
    start_at = datetime.fromisoformat(payload.get("startAt") or f"{date.today().isoformat()}T08:00:00")

    leg_a = route_leg(current, pickup)
    leg_b = route_leg(pickup, dropoff)
    events: list[Event] = []
    cursor = start_at

    cursor, cycle_remaining = schedule_drive_leg(events, cursor, current, pickup, leg_a["distance_miles"], cycle_remaining, "to pickup")
    cursor = add_event(events, cursor, PICKUP_DROPOFF_HOURS, "on", "Pickup loading and paperwork", pickup.label)
    cycle_remaining -= PICKUP_DROPOFF_HOURS
    cursor, cycle_remaining = schedule_drive_leg(events, cursor, pickup, dropoff, leg_b["distance_miles"], cycle_remaining, "to dropoff")
    cursor = add_event(events, cursor, PICKUP_DROPOFF_HOURS, "on", "Dropoff unloading and paperwork", dropoff.label)
    cycle_remaining -= PICKUP_DROPOFF_HOURS

    total_miles = leg_a["distance_miles"] + leg_b["distance_miles"]
    return {
        "locations": {
            "current": current.__dict__,
            "pickup": pickup.__dict__,
            "dropoff": dropoff.__dict__,
        },
        "route": {
            "distanceMiles": round(total_miles, 1),
            "durationDrivingHours": round(total_miles / AVERAGE_SPEED_MPH, 1),
            "geometry": simplify_geometry(leg_a["geometry"] + leg_b["geometry"][1:]),
            "source": "live" if leg_a["source"] == "osrm" and leg_b["source"] == "osrm" else "estimated",
        },
        "summary": {
            "startAt": start_at.isoformat(),
            "finishAt": cursor.isoformat(),
            "totalElapsedHours": round((cursor - start_at).total_seconds() / 3600, 1),
            "cycleUsedAtStart": cycle_used,
            "cycleRemainingAtFinish": round(max(0, cycle_remaining), 1),
            "logSheetCount": len(split_by_day(events)),
        },
        "stops": [serialize_event(event) for event in events if event.status != "driving"],
        "events": [serialize_event(event) for event in events],
        "logs": split_by_day(events),
    }
