from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

from .db import PROJECT_ROOT

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ACTIVITIES_OUT = PROCESSED_DIR / "activities.csv"
POINTS_OUT = PROCESSED_DIR / "activity_points.csv"
MANIFEST = PROCESSED_DIR / "strava_zip_manifest.json"


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() and str(value).strip().lower() not in {"nan", "none", "null"}:
            return value
    return None


def _activity_id_from_path(path: str) -> str | None:
    name = PurePosixPath(path).name
    match = re.match(r"(\d{5,})", name)
    return match.group(1) if match else None


def _decode_csv(data: bytes) -> pd.DataFrame:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding=encoding, sep=None, engine="python", on_bad_lines="warn")
            df.columns = [_norm(c) for c in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError("No se ha podido decodificar activities.csv del ZIP de Strava.")


def _get_scalar(value: Any) -> Any:
    if isinstance(value, tuple):
        return value[0] if len(value) == 1 else None
    if isinstance(value, list):
        return value[0] if len(value) == 1 else None
    return value


def _patch_fitdecode_datetime() -> None:
    """Work around malformed tuple-valued date fields seen in some FIT exports."""
    try:
        import fitdecode.processors as processors
    except ImportError as exc:
        raise RuntimeError("Falta fitdecode. Ejecuta: pip install -r requirements.txt") from exc

    names = {"process_type_date_time", "process_type_local_date_time"}
    for cls in vars(processors).values():
        if not isinstance(cls, type):
            continue
        for name in names:
            original = cls.__dict__.get(name)
            if original is None or getattr(original, "_gonzarun_safe", False):
                continue

            def safe_datetime(self, reader, field_data, _original=original):
                value = field_data.value
                if isinstance(value, (tuple, list)):
                    if len(value) == 1:
                        field_data.value = value[0]
                    else:
                        field_data.value = None
                        return
                if field_data.value is None:
                    return
                try:
                    return _original(self, reader, field_data)
                except (TypeError, ValueError, OverflowError):
                    field_data.value = None
                    return

            safe_datetime._gonzarun_safe = True
            setattr(cls, name, safe_datetime)


def _fit_records(data: bytes) -> list[dict[str, Any]]:
    import fitdecode

    _patch_fitdecode_datetime()
    records: list[dict[str, Any]] = []
    with fitdecode.FitReader(io.BytesIO(data)) as fit:
        for frame in fit:
            if getattr(frame, "name", None) != "record":
                continue
            values: dict[str, Any] = {}
            for field in getattr(frame, "fields", []):
                values[_norm(getattr(field, "name", ""))] = _get_scalar(getattr(field, "value", None))
            lat = _get_scalar(values.get("position_lat"))
            lon = _get_scalar(values.get("position_long"))
            if lat is None or lon is None:
                continue
            try:
                lat = float(lat) * 180.0 / (2**31) if abs(float(lat)) > 90 else float(lat)
                lon = float(lon) * 180.0 / (2**31) if abs(float(lon)) > 180 else float(lon)
            except (TypeError, ValueError, OverflowError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            timestamp = values.get("timestamp")
            if isinstance(timestamp, datetime):
                timestamp = timestamp.isoformat()
            elif timestamp is not None:
                timestamp = str(timestamp)
            distance = values.get("distance")
            if distance is not None:
                try:
                    distance = float(distance)
                except (TypeError, ValueError):
                    distance = None
            speed = values.get("enhanced_speed") if values.get("enhanced_speed") is not None else values.get("speed")
            altitude = values.get("enhanced_altitude") if values.get("enhanced_altitude") is not None else values.get("altitude")
            records.append({
                "timestamp": timestamp,
                "latitude": lat,
                "longitude": lon,
                "altitude_m": _get_scalar(altitude),
                "distance_m": distance,
                "heart_rate": _get_scalar(values.get("heart_rate")),
                "cadence": _get_scalar(values.get("cadence")),
                "speed_mps": _get_scalar(speed),
                "power_w": _get_scalar(values.get("power")),
                "temperature_c": _get_scalar(values.get("temperature")),
                "grade_percent": None,
            })
    return records


def _xml_records(data: bytes, suffix: str) -> list[dict[str, Any]]:
    """Basic GPX/TCX support as a fallback for older Strava archive entries."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if suffix.endswith("gpx") and tag == "trkpt":
            lat, lon = node.attrib.get("lat"), node.attrib.get("lon")
            if lat is None or lon is None:
                continue
            values = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in node}
            rows.append({"timestamp": values.get("time"), "latitude": lat, "longitude": lon,
                         "altitude_m": values.get("ele"), "distance_m": None, "heart_rate": None,
                         "cadence": None, "speed_mps": None, "power_w": None,
                         "temperature_c": None, "grade_percent": None})
        elif suffix.endswith("tcx") and tag == "trackpoint":
            values: dict[str, Any] = {}
            for child in node.iter():
                child_tag = child.tag.rsplit("}", 1)[-1].lower()
                if child.text and child.text.strip():
                    values[child_tag] = child.text.strip()
            lat, lon = values.get("latitudedegrees"), values.get("longitudedegrees")
            if lat is None or lon is None:
                # XML namespaces are stripped above; use parent structure for TCX coordinates below.
                for child in node.iter():
                    child_tag = child.tag.rsplit("}", 1)[-1].lower()
                    if child_tag == "position":
                        coords = {c.tag.rsplit("}", 1)[-1].lower(): (c.text or "").strip() for c in child}
                        lat, lon = coords.get("latitudedegrees"), coords.get("longitudedegrees")
                        break
            if lat is None or lon is None:
                continue
            rows.append({"timestamp": values.get("time"), "latitude": lat, "longitude": lon,
                         "altitude_m": values.get("altitudemeters"), "distance_m": values.get("distancemeters"),
                         "heart_rate": values.get("value"), "cadence": values.get("cadence"),
                         "speed_mps": None, "power_w": None, "temperature_c": None, "grade_percent": None})
    return rows


def _activity_id_map(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    filename_to_id: dict[str, str] = {}
    id_col = next((
        c for c in (
            "activity_id",
            "id",
            "id_de_l_activite",
            "id_de_activite",
        )
        if c in df.columns
    ), None)
    filename_col = next((
        c for c in (
            "filename",
            "activity_file",
            "file_name",
            "activity_filename",
            "nom_du_fichier",
        )
        if c in df.columns
    ), None)
    ids: list[str] = []
    for _, row in df.iterrows():
        filename = str(row.get(filename_col, "")).strip() if filename_col else ""
        aid = str(row.get(id_col, "")).strip() if id_col else ""
        if not aid or aid.lower() in {"nan", "none", "null"}:
            aid = _activity_id_from_path(filename) or ""
        if aid.endswith(".0"):
            aid = aid[:-2]
        ids.append(aid)
        if filename and aid:
            filename_to_id[PurePosixPath(filename.replace("\\", "/")).name.lower()] = aid
            filename_to_id[filename.replace("\\", "/").lower()] = aid
    if "activity_id" not in df.columns:
        df["activity_id"] = ids
    else:
        df["activity_id"] = [ids[i] or str(v).strip() for i, v in enumerate(df["activity_id"].tolist())]
    df = df[df["activity_id"].astype(str).str.len() > 0].copy()
    return df, filename_to_id


def _decompress_entry(name: str, data: bytes) -> tuple[str, bytes]:
    lower = name.lower()
    if lower.endswith(".gz"):
        data = gzip.decompress(data)
        lower = lower[:-3]
    suffix = PurePosixPath(lower).suffix.lower()
    return suffix, data


def prepare_strava_zip(zip_path: Path, force: bool = False) -> dict[str, Any]:
    """Read a Strava bulk-export ZIP and build normalized activities/points CSVs."""
    if not zip_path.exists():
        raise FileNotFoundError(f"No se encuentra el ZIP de Strava: {zip_path}")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    digest_obj = hashlib.sha256()
    with zip_path.open("rb") as zip_file:
        for chunk in iter(lambda: zip_file.read(1024 * 1024), b""):
            digest_obj.update(chunk)
    digest = digest_obj.hexdigest()
    if not force and ACTIVITIES_OUT.exists() and POINTS_OUT.exists() and MANIFEST.exists():
        try:
            old = json.loads(MANIFEST.read_text(encoding="utf-8"))
            if old.get("sha256") == digest:
                return {"zip": str(zip_path), "zip_unchanged": True, "activities_csv": str(ACTIVITIES_OUT), "points_csv": str(POINTS_OUT), "gps_points_generated": old.get("gps_points_generated", 0), "files_processed": old.get("files_processed", 0), "errors": old.get("errors", [])}
        except (OSError, json.JSONDecodeError):
            pass

    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        csv_candidates = [n for n in names if PurePosixPath(n).name.lower() == "activities.csv"]
        if not csv_candidates:
            raise ValueError("El ZIP no contiene activities.csv. Asegúrate de usar el archivo ZIP completo descargado de Strava.")
        csv_name = min(csv_candidates, key=lambda n: (len(PurePosixPath(n).parts), len(n)))
        activities_df = _decode_csv(archive.read(csv_name))
        activities_df, filename_to_id = _activity_id_map(activities_df)
        if activities_df.empty:
            raise ValueError("activities.csv no contiene actividades con ID reconocible.")

        # Store a stable UTF-8 CSV with an explicit activity_id column.
        activities_df.to_csv(ACTIVITIES_OUT, index=False, encoding="utf-8")
        points: list[dict[str, Any]] = []
        errors: list[str] = []
        files_processed = 0
        activity_files = []
        for name in names:
            parts = [p.lower() for p in PurePosixPath(name).parts]
            if "activities" not in parts:
                continue
            base = PurePosixPath(name).name.lower()
            # Avoid non-track files in the activities folder.
            if not re.search(r"\.(fit|gpx|tcx)(\.gz)?$", base):
                continue
            aid = filename_to_id.get(base) or filename_to_id.get(name.replace("\\", "/").lower()) or _activity_id_from_path(base)
            if not aid:
                errors.append(f"No se pudo asociar ID a {name}")
                continue
            activity_files.append((name, aid))

        known_ids = set(activities_df["activity_id"].astype(str))
        for name, aid in activity_files:
            if aid not in known_ids:
                # Some Strava archives name the track by the activity ID even if CSV filename variants differ.
                guessed = _activity_id_from_path(name)
                if guessed in known_ids:
                    aid = guessed
                else:
                    errors.append(f"El archivo {name} no coincide con un ID de activities.csv ({aid})")
                    continue
            try:
                suffix, raw = _decompress_entry(name, archive.read(name))
                if suffix == ".fit":
                    rows = _fit_records(raw)
                elif suffix in {".gpx", ".tcx"}:
                    rows = _xml_records(raw, suffix)
                else:
                    rows = []
                for idx, row in enumerate(rows):
                    row["activity_id"] = aid
                    row["point_index"] = idx
                    points.append(row)
                files_processed += 1
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {exc}")

    points_df = pd.DataFrame(points, columns=[
        "activity_id", "point_index", "timestamp", "latitude", "longitude", "altitude_m", "distance_m",
        "heart_rate", "cadence", "speed_mps", "power_w", "temperature_c", "grade_percent",
    ])
    points_df.to_csv(POINTS_OUT, index=False, encoding="utf-8")
    manifest = {
        "sha256": digest, "source_zip": zip_path.name,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "activities_csv_entries": len(activities_df), "activity_files_found": len(activity_files),
        "files_processed": files_processed, "gps_points_generated": len(points_df), "errors": errors,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"zip": str(zip_path), "zip_unchanged": False, "activities_csv": str(ACTIVITIES_OUT), "points_csv": str(POINTS_OUT),
            "activities_csv_entries": len(activities_df), "activity_files_found": len(activity_files),
            "files_processed": files_processed, "gps_points_generated": len(points_df), "errors": errors}
