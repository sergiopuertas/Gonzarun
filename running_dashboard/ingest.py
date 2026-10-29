from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select, delete, update, insert
from dotenv import load_dotenv

from .db import (
    PROJECT_ROOT, activities, activity_points, import_state, get_engine, init_db,
)
from .strava_zip import prepare_strava_zip

load_dotenv(PROJECT_ROOT / ".env")


def norm_header(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")


def read_csv_flexible(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No se encuentra el CSV: {path}\nIndica la ruta con --activities o --points, o configúrala en .env.")
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig", sep=None, engine="python", on_bad_lines="warn")
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="latin-1", sep=None, engine="python", on_bad_lines="warn")
    df.columns = [norm_header(c) for c in df.columns]
    return df


def raw_json(row: dict[str, Any]) -> str:
    return json.dumps({str(k): (None if pd.isna(v) else str(v)) for k, v in row.items()}, ensure_ascii=False)


def first(row: dict[str, Any], *keys: str) -> tuple[Any, str | None]:
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip() != "":
            return row[key], key
    return None, None


def number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not s or s.lower() in {"nan", "none", "null", "--"}:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_seconds(value: Any) -> float | None:
    n = number(value)
    if n is not None:
        return n
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except ValueError:
        return None
    return None


def parse_date(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    month_names = {
        "janv": "01", "janvier": "01",
        "févr": "02", "fevr": "02", "février": "02", "fevrier": "02",
        "mars": "03",
        "avr": "04", "avril": "04",
        "mai": "05",
        "juin": "06",
        "juil": "07", "juillet": "07",
        "août": "08", "aout": "08",
        "sept": "09", "septembre": "09",
        "oct": "10", "octobre": "10",
        "nov": "11", "novembre": "11",
        "déc": "12", "dec": "12", "décembre": "12", "decembre": "12",
    }
    localized = re.sub(
        r"\b([A-Za-zÀ-ÿ]+)\.?(?=\s+\d{4}\b)",
        lambda match: month_names.get(match.group(1).casefold(), match.group(1)),
        text,
    )
    match = re.match(
        r"^\s*(\d{1,2})\s+(\d{1,2})\s+(\d{4})(?:,\s*(\d{1,2}:\d{2}:\d{2}))?\s*$",
        localized,
    )
    if match:
        date_text = f"{match.group(1)} {match.group(2)} {match.group(3)}"
        if match.group(4):
            date_text += f" {match.group(4)}"
        dt = pd.to_datetime(date_text, format="%d %m %Y %H:%M:%S" if match.group(4) else "%d %m %Y", errors="coerce", utc=True)
    else:
        dt = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(dt):
        return text
    return dt.isoformat()


def _activity_record(row: dict[str, Any]) -> dict[str, Any] | None:
    activity_id, _ = first(row, "activity_id", "id", "activityid", "id_de_l_activite", "id_de_activite")
    if activity_id is None:
        return None
    activity_id = str(activity_id).strip()
    if activity_id.endswith(".0"):
        activity_id = activity_id[:-2]
    name, _ = first(row, "activity_name", "name", "activity", "nom_de_l_activite")
    kind, _ = first(row, "activity_type", "type", "sport", "activity_sport", "type_d_activite")
    date, _ = first(
        row,
        "activity_date",
        "start_date",
        "start_date_local",
        "start_time",
        "date",
        "datetime",
        "date_de_l_activite",
        "heure_de_debut",
    )

    # Strava's activities.csv normally stores distance in kilometres and time in seconds.
    dist, dist_key = first(
        row,
        "distance_km",
        "distance_kilometers",
        "distance_in_kilometers",
        "distance_meters",
        "distance_m",
        "distance",
    )
    distance_km = number(dist)
    if dist_key and ("meter" in dist_key or dist_key.endswith("_m")) and "kilometer" not in dist_key and not dist_key.endswith("_km"):
        distance_km = distance_km / 1000 if distance_km is not None else None

    moving, _ = first(row, "moving_time_s", "moving_time_seconds", "moving_time", "moving_duration", "duree_de_deplacement")
    elapsed, _ = first(row, "elapsed_time_s", "elapsed_time_seconds", "elapsed_time", "elapsed_duration", "duration", "temps_ecoule")
    elevation, _ = first(row, "elevation_gain_m", "elevation_gain_meters", "elevation_gain", "total_elevation_gain", "denivele_positif")
    avg_hr, _ = first(row, "average_heart_rate", "avg_hr", "average_hr", "heart_rate_avg", "frequence_cardiaque_moyenne")
    max_hr, _ = first(row, "max_heart_rate", "max_hr", "heart_rate_max", "frequence_cardiaque_max")
    avg_speed, avg_speed_key = first(
        row,
        "average_speed_m_s",
        "avg_speed_mps",
        "average_speed",
        "avg_speed",
        "average_speed_m_s",
        "vitesse_moyenne",
    )
    max_speed, max_speed_key = first(row, "max_speed_m_s", "max_speed_mps", "max_speed", "maximum_speed", "vitesse_max")
    avg_cadence, _ = first(row, "average_cadence", "avg_cadence", "cadence", "cadence_moyenne")
    calories, _ = first(row, "calories", "kcal")
    effort, _ = first(row, "relative_effort", "relative_effort_score", "effort_relatif")
    avg_power, _ = first(row, "average_power", "avg_power", "average_power_w", "puissance_moyenne")
    max_power, _ = first(row, "max_power", "maximum_power", "max_power_w", "puissance_max")
    suffer, _ = first(row, "suffer_score", "training_load")
    avg_speed_num, max_speed_num = number(avg_speed), number(max_speed)
    if avg_speed_key and ("km_h" in avg_speed_key or "kmh" in avg_speed_key):
        avg_speed_num = avg_speed_num / 3.6 if avg_speed_num is not None else None
    if max_speed_key and ("km_h" in max_speed_key or "kmh" in max_speed_key):
        max_speed_num = max_speed_num / 3.6 if max_speed_num is not None else None

    return {
        "activity_id": activity_id,
        "activity_date": parse_date(date),
        "activity_name": str(name).strip() if name else f"Actividad {activity_id}",
        "activity_type": str(kind).strip() if kind else "Sin tipo",
        "distance_km": distance_km,
        "moving_time_s": parse_seconds(moving),
        "elapsed_time_s": parse_seconds(elapsed),
        "elevation_gain_m": number(elevation),
        "avg_hr": number(avg_hr),
        "max_hr": number(max_hr),
        "avg_speed_mps": avg_speed_num,
        "max_speed_mps": max_speed_num,
        "avg_cadence": number(avg_cadence),
        "calories": number(calories),
        "relative_effort": number(effort),
        "avg_power_w": number(avg_power),
        "max_power_w": number(max_power),
        "suffer_score": number(suffer),
        "raw_json": json.dumps(row, ensure_ascii=False),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _semicircle_to_degrees(value: float | None, axis: str) -> float | None:
    if value is None:
        return None
    limit = 90 if axis == "lat" else 180
    if abs(value) > limit and abs(value) <= 2**31:
        value = value * 180.0 / (2**31)
    return value if abs(value) <= limit else None


def _point_rows(path: Path, known_activities: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    df = read_csv_flexible(path)
    activity_by_name_date: dict[tuple[str, str], str] = {}
    for aid, info in known_activities.items():
        name = re.sub(r"\s+", " ", (info.get("activity_name") or "").strip().lower())
        day = (info.get("activity_date") or "")[:10]
        if name and day:
            activity_by_name_date[(name, day)] = aid
    known_ids = set(known_activities)
    counters: dict[str, int] = {}
    output: list[dict[str, Any]] = []
    unmatched = 0

    for row in df.to_dict(orient="records"):
        id_value, _ = first(row, "activity_id", "activityid", "source_file", "source_filename", "filename", "file_name", "fit_file", "activity_file")
        activity_name, _ = first(row, "activity_name", "name", "activity")
        date_value, _ = first(row, "activity_date", "date", "activity_datetime")
        # Some point CSVs use a generic `activity` column for either ID or name.
        generic_activity, _ = first(row, "activity")
        if id_value is None and generic_activity is not None:
            generic_text = str(generic_activity).strip()
            generic_matches_id = generic_text in known_ids or any(candidate in known_ids for candidate in re.findall(r"\d{5,}", generic_text))
            if generic_matches_id:
                id_value = generic_text
        aid = None
        if id_value is not None:
            raw_id = str(id_value).strip()
            if raw_id in known_ids:
                aid = raw_id
            else:
                # The FIT filenames in Strava exports usually begin with the activity ID.
                for candidate in re.findall(r"\d{5,}", raw_id):
                    if candidate in known_ids:
                        aid = candidate
                        break
        if aid is None and activity_name and date_value:
            name_key = re.sub(r"\s+", " ", str(activity_name).strip().lower())
            day_key = (parse_date(date_value) or "")[:10]
            aid = activity_by_name_date.get((name_key, day_key))
        if aid is None:
            unmatched += 1
            continue

        lat_raw, _ = first(row, "latitude", "lat", "position_lat", "latitude_deg", "lat_deg", "latitude_degrees")
        lon_raw, _ = first(row, "longitude", "lon", "lng", "position_long", "longitude_deg", "lon_deg", "lng_deg", "longitude_degrees")
        lat = _semicircle_to_degrees(number(lat_raw), "lat")
        lon = _semicircle_to_degrees(number(lon_raw), "lon")
        if lat is None or lon is None:
            continue

        idx_raw, _ = first(row, "point_index", "record_index", "record_number", "step_index", "index", "idx", "step")
        idx = int(number(idx_raw)) if number(idx_raw) is not None else counters.get(aid, 0)
        counters[aid] = max(counters.get(aid, 0), idx + 1)
        timestamp, _ = first(row, "timestamp", "time", "datetime", "date_time", "record_timestamp")
        altitude, _ = first(row, "altitude_m", "altitude_meters", "altitude", "elevation_m", "elevation", "enhanced_altitude")
        dist_km, dist_km_key = first(row, "distance_km", "cumulative_distance_km")
        dist_m, dist_key = first(row, "distance_m", "distance_meters", "cumulative_distance_m", "total_distance_m", "distance", "dist_m")
        if dist_m is None and dist_km is not None:
            parsed_distance = number(dist_km)
            dist_m = parsed_distance * 1000 if parsed_distance is not None else None
        elif dist_m is not None:
            dist_m = number(dist_m)
            if dist_key and "km" in dist_key:
                dist_m = dist_m * 1000 if dist_m is not None else None
        speed, speed_key = first(row, "speed_mps", "speed_m_s", "enhanced_speed", "speed", "velocity", "speed_kmh", "speed_km_h")
        speed_num = number(speed)
        if speed_key and ("kmh" in speed_key or "km_h" in speed_key):
            speed_num = speed_num / 3.6 if speed_num is not None else None
        hr, _ = first(row, "heart_rate", "heart_rate_bpm", "heartrate", "hr", "bpm")
        cadence, _ = first(row, "cadence", "running_cadence", "step_cadence")
        power, _ = first(row, "power_w", "power", "watts")
        temp, _ = first(row, "temperature_c", "temperature", "temp_c", "temp")
        grade, _ = first(row, "grade_percent", "grade_pct", "grade", "grade_smooth")

        output.append({
            "activity_id": aid, "point_index": idx,
            "timestamp": parse_date(timestamp), "latitude": lat, "longitude": lon,
            "altitude_m": number(altitude), "distance_m": number(dist_m),
            "heart_rate": number(hr), "cadence": number(cadence),
            "speed_mps": speed_num, "power_w": number(power), "temperature_c": number(temp),
            "grade_percent": number(grade), "raw_json": json.dumps(row, ensure_ascii=False),
        })

    # FIT/CSV exports can occasionally duplicate an index. Renumber deterministically per activity.
    if output:
        output.sort(key=lambda r: (r["activity_id"], r["point_index"]))
        last_activity = None
        next_index = 0
        for rec in output:
            if rec["activity_id"] != last_activity:
                last_activity, next_index = rec["activity_id"], 0
            rec["point_index"] = next_index
            next_index += 1
    return output, unmatched


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_value(conn, key: str) -> str | None:
    return conn.execute(select(import_state.c.value).where(import_state.c.key == key)).scalar_one_or_none()


def set_state(conn, key: str, value: str) -> None:
    if conn.execute(select(import_state.c.key).where(import_state.c.key == key)).first():
        conn.execute(update(import_state).where(import_state.c.key == key).values(value=value))
    else:
        conn.execute(insert(import_state).values(key=key, value=value))


def run_import(activities_path: Path, points_path: Path, force: bool = False) -> dict[str, Any]:
    init_db()
    if not activities_path.exists():
        raise FileNotFoundError(f"No se encuentra activities.csv: {activities_path}")
    activities_hash = file_hash(activities_path)
    points_hash = file_hash(points_path) if points_path.exists() else None
    engine = get_engine()
    stats: dict[str, Any] = {"activities_csv": str(activities_path), "points_csv": str(points_path), "activities_changed": False, "points_changed": False, "activities_imported": 0, "points_imported": 0, "unmatched_point_rows": 0}

    if force or points_hash is not None:
        points_should_change = force or points_hash != _read_state(engine, "points_sha256")
    else:
        points_should_change = False

    activities_should_change = force or activities_hash != _read_state(engine, "activities_sha256")
    activities_records: list[dict[str, Any]] = []
    known: dict[str, dict[str, Any]] = {}

    # Parse the activity file if needed, but also read existing activities to resolve GPS rows.
    if activities_should_change:
        df = read_csv_flexible(activities_path)
        for row in df.to_dict(orient="records"):
            rec = _activity_record(row)
            if rec:
                activities_records.append(rec)
                known[rec["activity_id"]] = rec
        if not activities_records:
            raise ValueError("No se han encontrado filas de actividades con una columna de ID reconocible. Revisa la cabecera de activities.csv.")
    else:
        with engine.connect() as conn:
            existing = conn.execute(select(activities)).mappings().all()
        known = {str(row["activity_id"]): dict(row) for row in existing}

    if activities_should_change:
        ids_now = set(known)
        with engine.begin() as conn:
            # Upsert generically so both SQLite and PostgreSQL work.
            existing_ids = {str(x) for x in conn.execute(select(activities.c.activity_id)).scalars().all()}
            new_ids = ids_now - existing_ids
            old_ids = existing_ids - ids_now
            for rec in activities_records:
                if rec["activity_id"] in existing_ids:
                    conn.execute(update(activities).where(activities.c.activity_id == rec["activity_id"]).values(**rec))
                else:
                    conn.execute(insert(activities).values(**rec))
            if old_ids:
                conn.execute(delete(activity_points).where(activity_points.c.activity_id.in_(old_ids)))
                conn.execute(delete(activities).where(activities.c.activity_id.in_(old_ids)))
            set_state(conn, "activities_sha256", activities_hash)
        stats["activities_changed"] = True
        stats["activities_imported"] = len(activities_records)

    if points_should_change:
        if not points_path.exists():
            stats["points_message"] = "No se ha encontrado activity_points.csv; se conservan los puntos GPS existentes."
        else:
            points_records, unmatched = _point_rows(points_path, known)
            stats["unmatched_point_rows"] = unmatched
            with engine.begin() as conn:
                conn.execute(delete(activity_points))
                batch_size = 5000
                for start in range(0, len(points_records), batch_size):
                    conn.execute(insert(activity_points), points_records[start:start + batch_size])
                set_state(conn, "points_sha256", points_hash or "")
            stats["points_changed"] = True
            stats["points_imported"] = len(points_records)
    elif points_path.exists():
        stats["points_message"] = "El CSV de puntos no ha cambiado; no se ha vuelto a importar."
    else:
        stats["points_message"] = "No hay CSV de puntos. Puedes cargar las estadísticas generales sin mapas GPS."

    return stats


def _read_state(engine, key: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(select(import_state.c.value).where(import_state.c.key == key)).scalar_one_or_none()


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa un ZIP de Strava o CSV normalizados a la base de datos de Gonzarun.")
    parser.add_argument("--zip", dest="zip_path", default=os.getenv("STRAVA_ZIP_PATH", str(PROJECT_ROOT / "data" / "strava_export.zip")), help="ZIP completo descargado de Strava")
    parser.add_argument("--activities", default=os.getenv("ACTIVITIES_CSV", str(PROJECT_ROOT / "data" / "processed" / "activities.csv")), help="Ruta de activities.csv ya extraído/normalizado")
    parser.add_argument("--points", default=os.getenv("POINTS_CSV", str(PROJECT_ROOT / "data" / "processed" / "activity_points.csv")), help="Ruta de puntos GPS ya generada")
    parser.add_argument("--csv-only", action="store_true", help="No procesar ZIP; importar los CSV indicados")
    parser.add_argument("--force", action="store_true", help="Fuerza la extracción del ZIP y la reimportación de los CSV")
    args = parser.parse_args()
    try:
        if not args.csv_only and args.zip_path and Path(args.zip_path).expanduser().exists():
            prep = prepare_strava_zip(Path(args.zip_path).expanduser().resolve(), force=args.force)
            print("=== Preparación del ZIP de Strava ===")
            for key, value in prep.items():
                print(f"{key}: {value}")
            activities_path = Path(prep["activities_csv"])
            points_path = Path(prep["points_csv"])
        else:
            activities_path = Path(args.activities).expanduser().resolve()
            points_path = Path(args.points).expanduser().resolve()
            if not args.csv_only and args.zip_path:
                print(f"No se encuentra el ZIP configurado ({args.zip_path}); se intentará la importación CSV.")
        result = run_import(activities_path, points_path, args.force)
    except Exception as exc:
        print(f"ERROR de importación: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("\n=== Importación Gonzarun ===")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
