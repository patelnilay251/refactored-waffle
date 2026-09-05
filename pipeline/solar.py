"""Where the sun actually is.

The site knows its own latitude and longitude, so the sun can be placed from a
date and a clock time rather than dialled in until it looks nice. That matters
for a street running roughly north-south: whether light rakes down it or skims
across the roofline is decided by the calendar, and guessing produces shadows
that quietly contradict each other.

NOAA's solar position approximation, good to about a minute of arc — far
tighter than anything that reads in a render.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SunPosition:
    """Elevation above the horizon and compass azimuth, both in degrees.

    Azimuth is measured clockwise from north, the surveying convention: 90 is
    due east, 180 due south.
    """

    elevation: float
    azimuth: float

    @property
    def is_up(self) -> bool:
        return self.elevation > 0

    def describe(self) -> str:
        compass = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        point = compass[int((self.azimuth % 360) / 22.5 + 0.5) % 16]
        return f"{self.elevation:.1f} deg above horizon, {self.azimuth:.0f} deg ({point})"


def sun_position(latitude: float, longitude: float, when: datetime,
                 utc_offset_hours: float = 0.0) -> SunPosition:
    """Solar elevation and azimuth for a place and a local time."""
    day_of_year = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600

    # Fractional year, radians.
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)

    # Equation of time, minutes: the offset between clock noon and solar noon.
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )

    declination = (
        0.006918
        - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.001480 * math.sin(3 * gamma)
    )

    # True solar time, minutes past local midnight.
    offset = eqtime + 4 * longitude - 60 * utc_offset_hours
    true_solar = (hour * 60 + offset) % 1440

    # Hour angle: zero at solar noon, negative before it.
    hour_angle = math.radians(true_solar / 4 - 180)

    lat = math.radians(latitude)
    cos_zenith = (math.sin(lat) * math.sin(declination)
                  + math.cos(lat) * math.cos(declination) * math.cos(hour_angle))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)

    # Azimuth from north, clockwise. Note the order of the numerator: with it
    # the other way round the whole result is mirrored through the east-west
    # line, which puts the midday sun due north and is only obvious if you
    # check a solar noon rather than an evening.
    sin_zenith = math.sin(zenith)
    if abs(sin_zenith) < 1e-6:
        azimuth = 180.0
    else:
        cos_azimuth = ((math.sin(declination) - math.sin(lat) * cos_zenith)
                       / (math.cos(lat) * sin_zenith))
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
        azimuth = math.degrees(math.acos(cos_azimuth))
        # acos loses the sign; after solar noon the sun is west of south.
        if hour_angle > 0:
            azimuth = 360.0 - azimuth

    return SunPosition(elevation=90.0 - math.degrees(zenith),
                       azimuth=azimuth % 360.0)


def direction(sun: SunPosition) -> tuple[float, float, float]:
    """Unit vector toward the sun in the site's local frame (+X east, +Y north)."""
    elevation = math.radians(sun.elevation)
    azimuth = math.radians(sun.azimuth)
    return (math.sin(azimuth) * math.cos(elevation),
            math.cos(azimuth) * math.cos(elevation),
            math.sin(elevation))


def sky_rotation(sun: SunPosition) -> float:
    """Blender sky-texture rotation, radians.

    The sky texture measures its sun anticlockwise from +X, while a compass
    azimuth runs clockwise from +Y, so the two differ by a quarter turn and a
    change of sign.
    """
    return math.radians(90.0 - sun.azimuth)
