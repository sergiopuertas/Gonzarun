from __future__ import annotations

import math
from typing import Iterable

import pandas as pd


def seconds_to_hms(value: float | int | None) -> str:
    if value is None or pd.isna(value) or value < 0:
        return "—"
    seconds = int(round(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def pace_min_km(distance_km: float | None, time_s: float | None) -> float | None:
    if distance_km is None or time_s is None or pd.isna(distance_km) or pd.isna(time_s) or distance_km <= 0 or time_s <= 0:
        return None
    return float(time_s) / 60.0 / float(distance_km)


def format_pace(value: float | None) -> str:
    if value is None or pd.isna(value) or value <= 0 or not math.isfinite(float(value)):
        return "—"
    minutes = int(value)
    seconds = int(round((value - minutes) * 60))
    if seconds >= 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d} /km"


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def ensure_activity_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for col in ["distance_km", "moving_time_s", "elapsed_time_s", "elevation_gain_m", "avg_hr", "max_hr", "avg_speed_mps", "max_speed_mps", "avg_cadence", "calories", "relative_effort", "avg_power_w", "max_power_w", "suffer_score"]:
        if col not in result.columns:
            result[col] = None
        result[col] = pd.to_numeric(result[col], errors="coerce")
    if "activity_date" not in result:
        result["activity_date"] = pd.NaT
    result["activity_date"] = pd.to_datetime(result["activity_date"], errors="coerce", utc=True)
    if "activity_name" not in result:
        result["activity_name"] = "Actividad"
    if "activity_type" not in result:
        result["activity_type"] = "Sin tipo"
    result["activity_name"] = result["activity_name"].fillna("Actividad")
    result["activity_type"] = result["activity_type"].fillna("Sin tipo")
    result["activity_family"] = result["activity_type"].map(activity_family)
    swim_mask = result["activity_family"] == "Natación"
    result.loc[swim_mask, "distance_km"] = result.loc[swim_mask, "distance_km"] / 1000
    for col in ["avg_hr", "max_hr"]:
        result.loc[~result[col].between(30, 240), col] = float("nan")
    if "moving_time_s" in result:
        result["duration_s"] = result["moving_time_s"].fillna(result["elapsed_time_s"])
    else:
        result["duration_s"] = result["elapsed_time_s"]
    result["pace_min_km"] = result.apply(lambda r: pace_min_km(r.get("distance_km"), r.get("duration_s")), axis=1)
    result["month"] = result["activity_date"].dt.tz_convert(None).dt.to_period("M").astype(str)
    result["year"] = result["activity_date"].dt.year
    result["weekday"] = result["activity_date"].dt.day_name()
    result["hour"] = result["activity_date"].dt.hour
    result["day"] = result["activity_date"].dt.date
    return result


def is_running_type(value: object) -> bool:
    text = str(value).lower().replace(" ", "")
    return any(token in text for token in ("run", "running", "carrera", "correr", "course", "trailrun", "treadmill"))


def activity_family(value: object) -> str:
    text = str(value).casefold()
    if any(token in text for token in ("swim", "natation", "natación", "nadar", "water")):
        return "Natación"
    if any(token in text for token in ("bike", "cycling", "vélo", "ciclismo", "bici")):
        return "Bici"
    if any(token in text for token in ("walk", "walking", "marche", "andar", "hike", "randonnée", "senderismo")):
        return "Andar"
    if is_running_type(value):
        return "Correr"
    return "Otros"


def prepare_points(points: pd.DataFrame) -> pd.DataFrame:
    df = points.copy()
    if df.empty:
        return df
    for col in ["point_index", "latitude", "longitude", "altitude_m", "distance_m", "heart_rate", "cadence", "speed_mps", "power_w", "temperature_c"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp_parsed"] = pd.to_datetime(df.get("timestamp"), errors="coerce", utc=True)
    df = df.sort_values(["activity_id", "point_index"], kind="stable").reset_index(drop=True)
    if "distance_m" not in df:
        df["distance_m"] = float("nan")
    # Fill unavailable cumulative distance from GPS. For partially populated distances, use GPS deltas where possible.
    for aid, indices in df.groupby("activity_id", sort=False).groups.items():
        index_list = list(indices)
        segment = df.loc[index_list]
        d = segment["distance_m"].copy()
        if d.notna().sum() < max(3, int(len(segment) * 0.25)):
            vals = [0.0]
            for j in range(1, len(segment)):
                a, b = segment.iloc[j - 1], segment.iloc[j]
                if pd.notna(a["latitude"]) and pd.notna(a["longitude"]) and pd.notna(b["latitude"]) and pd.notna(b["longitude"]):
                    vals.append(vals[-1] + haversine_m(float(a["latitude"]), float(a["longitude"]), float(b["latitude"]), float(b["longitude"])))
                else:
                    vals.append(vals[-1])
            df.loc[index_list, "distance_m"] = vals
        else:
            d = d.interpolate(limit_direction="both")
            # Distances in FIT are cumulative; guard against accidental reset/noisy backwards jumps.
            if d.notna().all():
                d = d.cummax()
            df.loc[index_list, "distance_m"] = d.values
    return df


def compute_segment_records(points: pd.DataFrame, activity_lookup: pd.DataFrame | None = None) -> pd.DataFrame:
    """Find best GPS-derived rolling segments. Needs point timestamps and cumulative distance."""
    if points.empty:
        return pd.DataFrame(columns=["distancia", "mejor_tiempo_s", "ritmo_min_km", "actividad", "fecha", "inicio", "fin"])
    df = prepare_points(points)
    targets = [(1000.0, "1 km"), (5000.0, "5 km"), (10000.0, "10 km"), (21097.5, "Media maratón"), (42195.0, "Maratón")]
    lookup = {}
    if activity_lookup is not None and not activity_lookup.empty:
        for _, row in activity_lookup.iterrows():
            lookup[str(row["activity_id"])] = row
    best: dict[str, dict] = {}
    for aid, group in df.groupby("activity_id", sort=False):
        group = group.sort_values("point_index", kind="stable")
        dist = pd.to_numeric(group["distance_m"], errors="coerce").to_numpy()
        times = group["timestamp_parsed"].map(lambda x: x.timestamp() if pd.notna(x) else float("nan")).to_numpy()
        if len(group) < 2 or pd.isna(times).sum() > len(times) * 0.2:
            continue
        # Consecutive points with missing time cannot establish an elapsed segment.
        for target, label in targets:
            left = 0
            record = best.get(label)
            for right in range(1, len(group)):
                if not math.isfinite(dist[right]) or not math.isfinite(times[right]):
                    continue
                while left < right and dist[right] - dist[left] >= target:
                    if math.isfinite(times[left]):
                        duration = times[right] - times[left]
                        if duration > 0:
                            if record is None or duration < record["mejor_tiempo_s"]:
                                act = lookup.get(str(aid))
                                record = {
                                    "distancia": label,
                                    "distancia_objetivo_km": target / 1000,
                                    "mejor_tiempo_s": duration,
                                    "ritmo_min_km": duration / 60 / (target / 1000),
                                    "activity_id": str(aid),
                                    "actividad": str(act["activity_name"]) if act is not None else str(aid),
                                    "fecha": act["activity_date"] if act is not None else None,
                                    "inicio": group.iloc[left].get("timestamp"),
                                    "fin": group.iloc[right].get("timestamp"),
                                }
                    left += 1
            if record is not None:
                best[label] = record
    return pd.DataFrame([best[k] for _, k in targets if k in best])


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["month", "distance_km", "runs", "duration_h", "elevation_m", "avg_pace"])
    grouped = df.groupby("month", dropna=False).agg(
        distance_km=("distance_km", "sum"),
        runs=("activity_id", "count"),
        duration_h=("duration_s", lambda s: s.sum(min_count=1) / 3600),
        elevation_m=("elevation_gain_m", "sum"),
        avg_pace=("pace_min_km", "mean"),
    ).reset_index()
    return grouped.sort_values("month")
