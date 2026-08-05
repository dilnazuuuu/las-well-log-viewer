from __future__ import annotations

import math
import os
import re
import copy
import hashlib
import io
import urllib.request
from collections import OrderedDict
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


app = FastAPI(title="LAS Well Log API", version="0.1.0")
DEFAULT_NULL_VALUES = {-999.25, -999.0, -9999.0, 999.25, 999.0, 9999.0}
PARSE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
PARSE_CACHE_LIMIT = int(os.getenv("PARSE_CACHE_LIMIT", "16"))
PUBLIC_SAMPLE_LIMIT_BYTES = int(os.getenv("PUBLIC_SAMPLE_LIMIT_BYTES", str(12 * 1024 * 1024)))
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "koi8-r", "cp866", "latin1")
BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR.parent / "samples"
VSH_CLEAN_CUTOFF = 0.35
ALLOWED_PUBLIC_SAMPLE_HOSTS = {"pubs.usgs.gov"}
PUBLIC_DATASETS = [
    {
        "name": "Kansas Geological Survey LAS Database",
        "source": "KGS",
        "url": "https://www.kgs.ku.edu/Magellan/Logs/",
        "data_type": "Searchable LAS files and bulk downloads",
        "best_for": "Expanding the sample gallery with many public wells",
        "description": "Public Kansas well logs that are useful for testing metadata parsing, curve availability, and batch quality checks.",
        "tags": ["LAS", "Kansas", "bulk"],
    },
    {
        "name": "USGS Drew Point 1 Well Log",
        "source": "USGS",
        "url": "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/DrewPt1/LAS/DP1LAS.htm",
        "data_type": "Single public LAS well",
        "best_for": "Testing a richer file with GR, resistivity, sonic, density, and neutron curves",
        "description": "A public LAS example with several common petrophysical curves, helpful for validating multi-track visualization.",
        "tags": ["LAS", "Alaska", "petrophysics"],
    },
    {
        "name": "USGS Appalachian Basin LAS Files",
        "source": "USGS",
        "url": "https://pubs.usgs.gov/of/2007/1142/",
        "data_type": "LAS files from multiple wells",
        "best_for": "Comparing wells across one public geology collection",
        "description": "A public collection of well log LAS files that can be used to test curve naming differences and interval analysis.",
        "tags": ["LAS", "basin", "multi-well"],
    },
    {
        "name": "Equinor Volve Data Village",
        "source": "Equinor",
        "url": "https://www.equinor.com/energy/volve-data-sharing",
        "data_type": "Large open field dataset",
        "best_for": "A future full workflow with public subsurface data",
        "description": "A large open dataset from the Volve field, useful as a next step for realistic public-data workflows.",
        "tags": ["open data", "field data", "workflow"],
    },
]
PUBLIC_SAMPLE_FILES = [
    {
        "id": "usgs-drew-point-1",
        "name": "Drew Point 1",
        "filename": "DP1.LAS",
        "source": "USGS NPRA",
        "dataset": "USGS Drew Point 1 Well Log",
        "url": "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/DrewPt1/LAS/DP1.LAS",
        "size_note": "2.2 MB",
        "curves_note": "GR, resistivity, sonic, density, neutron",
    },
    {
        "id": "usgs-east-simpson-1",
        "name": "East Simpson 1",
        "filename": "ES1.LAS",
        "source": "USGS NPRA",
        "dataset": "USGS Alaska Wildcat Wells",
        "url": "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/ESimp1/LAS/ES1.LAS",
        "size_note": "2.1 MB",
        "curves_note": "GR, resistivity, sonic, density, neutron",
    },
    {
        "id": "usgs-ikpikpuk-1",
        "name": "Ikpikpuk 1",
        "filename": "IK1.LAS",
        "source": "USGS NPRA",
        "dataset": "USGS Alaska Wildcat Wells",
        "url": "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/Ikpik1/LAS/IK1.LAS",
        "size_note": "4.3 MB",
        "curves_note": "GR, resistivity, sonic, density, neutron",
    },
    {
        "id": "usgs-inigok-1",
        "name": "Inigok 1",
        "filename": "IN1.LAS",
        "source": "USGS NPRA",
        "dataset": "USGS Alaska Wildcat Wells",
        "url": "https://pubs.usgs.gov/of/1999/ofr-99-0015/Wells/Inigok1/LAS/IN1.LAS",
        "size_note": "7.0 MB",
        "curves_note": "GR, resistivity, sonic, density, neutron",
    },
]
KEY_CURVE_GROUPS = {
    "gamma_ray": {
        "label": "Gamma ray",
        "aliases": ("GR", "GRC", "CGR", "SGR", "GAMMA", "GAMMARAY"),
    },
    "resistivity": {
        "label": "Resistivity",
        "aliases": ("RESD", "RES", "RT", "ILD", "LLD", "RDEP", "RD"),
    },
    "sonic": {
        "label": "Sonic",
        "aliases": ("DT", "DTC", "AC", "SONIC"),
    },
    "density": {
        "label": "Bulk density",
        "aliases": ("RHOB", "RHOZ", "DEN", "DENS"),
    },
    "neutron_porosity": {
        "label": "Neutron porosity",
        "aliases": ("NPHI", "NPOR", "PHIN", "NEUT"),
    },
    "sp": {
        "label": "Spontaneous potential",
        "aliases": ("SP",),
    },
}


def get_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


def clean_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def round_number(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def normalize_mnemonic(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def finite_numbers(values: list[Any]) -> list[float]:
    numbers = []
    for value in values:
        number = clean_number(value)
        if number is not None:
            numbers.append(number)
    return numbers


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def estimate_depth_step(depth_values: list[Any]) -> float | None:
    depths = finite_numbers(depth_values)
    if len(depths) < 2:
        return None
    diffs = [
        abs(depths[index] - depths[index - 1])
        for index in range(1, len(depths))
        if not math.isclose(depths[index], depths[index - 1])
    ]
    if not diffs:
        return None
    return median(diffs)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return str(value)


def score_decoded_text(text: str) -> int:
    cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04ff")
    replacement_count = text.count("\ufffd")
    mojibake_count = sum(text.count(marker) for marker in ("Ð", "Ñ", "Â", "Ã", "�"))
    control_count = sum(1 for char in text if ord(char) < 32 and char not in "\r\n\t")
    las_marker_count = sum(text.upper().count(marker) for marker in ("~V", "~W", "~C", "~A", "STRT", "STOP", "NULL"))
    return (cyrillic_count * 4) + (las_marker_count * 10) - (replacement_count * 50) - (mojibake_count * 10) - (control_count * 20)


def decode_las_bytes(file_bytes: bytes) -> tuple[str, str]:
    best_text = file_bytes.decode("utf-8", errors="replace")
    best_encoding = "utf-8"
    best_score = score_decoded_text(best_text)

    for encoding in TEXT_ENCODINGS:
        try:
            text = file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
        score = score_decoded_text(text)
        if score > best_score:
            best_text = text
            best_encoding = encoding
            best_score = score

    return best_text, best_encoding


def is_null_value(value: float | None, null_values: set[float]) -> bool:
    if value is None:
        return True
    return any(math.isclose(value, null_value, rel_tol=0.0, abs_tol=1e-9) for null_value in null_values)


def clean_series(values: list[Any], null_values: set[float] | None = None) -> list[float | None]:
    active_nulls = null_values or set()
    cleaned = []
    for value in values:
        number = clean_number(value)
        cleaned.append(None if is_null_value(number, active_nulls) else number)
    return cleaned


def get_null_values(well: dict[str, Any]) -> set[float]:
    values = set(DEFAULT_NULL_VALUES)
    header_null = clean_number(well.get("NULL", {}).get("value"))
    if header_null is not None:
        values.add(header_null)
    return values


def section_items_to_dict(section: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in section:
        key = str(getattr(item, "mnemonic", "")).strip()
        if not key:
            continue
        result[key] = {
            "value": getattr(item, "value", None),
            "unit": str(getattr(item, "unit", "") or ""),
            "description": str(getattr(item, "descr", "") or ""),
        }
    return result


def build_curve_stats(values: list[float | None]) -> dict[str, Any]:
    valid = [value for value in values if value is not None]
    sample_count = len(values)
    null_count = sample_count - len(valid)
    return {
        "min": round_number(min(valid)) if valid else None,
        "max": round_number(max(valid)) if valid else None,
        "average": round_number(sum(valid) / len(valid)) if valid else None,
        "valid_count": len(valid),
        "null_count": null_count,
        "null_percent": round_number((null_count / sample_count) * 100, 1) if sample_count else 0.0,
    }


def identify_key_curves(curves: list[dict[str, Any]]) -> dict[str, str]:
    curve_lookup = {
        normalize_mnemonic(str(curve.get("mnemonic", ""))): str(curve.get("mnemonic", ""))
        for curve in curves
        if not curve.get("synthetic")
    }
    detected: dict[str, str] = {}
    for group, config in KEY_CURVE_GROUPS.items():
        for alias in config["aliases"]:
            mnemonic = curve_lookup.get(normalize_mnemonic(alias))
            if mnemonic:
                detected[group] = mnemonic
                break
    return detected


def build_curve_quality_rows(
    curves: list[dict[str, Any]], detected: dict[str, str]
) -> list[dict[str, Any]]:
    group_by_mnemonic = {mnemonic: group for group, mnemonic in detected.items()}
    rows = []
    for curve in curves:
        if curve.get("synthetic"):
            continue
        valid_count = int(curve.get("valid_count") or 0)
        null_percent = float(curve.get("null_percent") or 0)
        if valid_count == 0:
            status = "No data"
        elif null_percent >= 50:
            status = "High nulls"
        elif null_percent >= 20:
            status = "Review"
        else:
            status = "Good"
        group = group_by_mnemonic.get(str(curve.get("mnemonic", "")))
        rows.append(
            {
                "mnemonic": curve.get("mnemonic"),
                "unit": curve.get("unit"),
                "description": curve.get("description"),
                "category": KEY_CURVE_GROUPS[group]["label"] if group else None,
                "min": curve.get("min"),
                "max": curve.get("max"),
                "average": curve.get("average"),
                "valid_count": valid_count,
                "null_count": curve.get("null_count"),
                "null_percent": null_percent,
                "status": status,
            }
        )
    return sorted(rows, key=lambda row: (row["status"] != "Good", row["mnemonic"] or ""))


def build_quality_summary(parsed: dict[str, Any], detected: dict[str, str]) -> dict[str, Any]:
    curves = parsed.get("curves", [])
    depth = parsed.get("depth", {})
    depth_values = depth.get("values", [])
    original_curves = [curve for curve in curves if not curve.get("synthetic")]
    depth_numbers = finite_numbers(depth_values)
    warnings = []

    if len(depth_numbers) < 2:
        warnings.append("Depth track has too few valid samples.")
    if "gamma_ray" not in detected:
        warnings.append("Gamma ray curve was not found, so Vshale cannot be computed.")
    if "resistivity" not in detected:
        warnings.append("Resistivity curve was not found; fluid/reservoir screening is limited.")

    high_null_curves = [
        str(curve.get("mnemonic"))
        for curve in original_curves
        if float(curve.get("null_percent") or 0) >= 50
    ]
    if high_null_curves:
        warnings.append(f"High-null curves: {', '.join(high_null_curves[:6])}.")

    key_curve_rows = [
        {
            "key": key,
            "label": config["label"],
            "mnemonic": detected.get(key),
            "present": key in detected,
        }
        for key, config in KEY_CURVE_GROUPS.items()
    ]
    return {
        "curve_count": len(original_curves),
        "row_count": parsed.get("row_count"),
        "depth_start": round_number(min(depth_numbers)) if depth_numbers else depth.get("start"),
        "depth_stop": round_number(max(depth_numbers)) if depth_numbers else depth.get("stop"),
        "depth_step": round_number(estimate_depth_step(depth_values)),
        "depth_unit": depth.get("unit"),
        "key_curves": key_curve_rows,
        "detected_key_curve_count": sum(1 for row in key_curve_rows if row["present"]),
        "warnings": warnings,
        "curves": build_curve_quality_rows(original_curves, detected),
    }


def interval_thickness(start: float, end: float, sample_count: int, step: float | None) -> float | None:
    if step is not None:
        return round_number(max(sample_count, 1) * step)
    return round_number(abs(end - start))


def build_vshale_summary(
    depth_values: list[Any],
    gr_values: list[Any],
    source_curve: str,
    depth_unit: str,
) -> dict[str, Any]:
    valid_gr = finite_numbers(gr_values)
    if len(valid_gr) < 5:
        return {
            "available": False,
            "reason": "Gamma ray curve has too few valid samples.",
        }

    gr_clean = percentile(valid_gr, 0.05)
    gr_shale = percentile(valid_gr, 0.95)
    if gr_clean is None or gr_shale is None or math.isclose(gr_clean, gr_shale):
        return {
            "available": False,
            "reason": "Gamma ray range is not wide enough for Vshale estimation.",
        }

    vshale_series: list[float | None] = []
    valid_pairs: list[tuple[float, float]] = []
    for index, raw_gr in enumerate(gr_values):
        gr = clean_number(raw_gr)
        if gr is None:
            vshale_series.append(None)
            continue
        vshale = max(0.0, min(1.0, (gr - gr_clean) / (gr_shale - gr_clean)))
        vshale = round(vshale, 4)
        vshale_series.append(vshale)
        if index < len(depth_values):
            depth = clean_number(depth_values[index])
            if depth is not None:
                valid_pairs.append((depth, vshale))

    step = estimate_depth_step(depth_values)
    clean_intervals = []
    active: dict[str, Any] | None = None
    clean_count = 0

    def close_active() -> None:
        nonlocal active
        if not active:
            return
        active["thickness"] = interval_thickness(
            active["from"], active["to"], active["sample_count"], step
        )
        clean_intervals.append(active)
        active = None

    for depth, vshale in valid_pairs:
        if vshale <= VSH_CLEAN_CUTOFF:
            clean_count += 1
            if not active:
                active = {"from": round_number(depth), "to": round_number(depth), "sample_count": 1}
            else:
                active["to"] = round_number(depth)
                active["sample_count"] += 1
        else:
            close_active()
    close_active()

    gross_thickness = None
    net_thickness = None
    if step is not None:
        gross_thickness = round_number(len(valid_pairs) * step)
        net_thickness = round_number(clean_count * step)
    elif valid_pairs:
        depths = [depth for depth, _value in valid_pairs]
        gross_thickness = round_number(max(depths) - min(depths))
        net_thickness = round_number(
            sum(float(interval.get("thickness") or 0) for interval in clean_intervals)
        )

    net_to_gross = None
    if gross_thickness and gross_thickness > 0 and net_thickness is not None:
        net_to_gross = round_number(net_thickness / gross_thickness, 3)

    valid_vshale = [value for value in vshale_series if value is not None]
    return {
        "available": True,
        "curve_mnemonic": "VSH",
        "source_curve": source_curve,
        "depth_unit": depth_unit,
        "gr_clean": round_number(gr_clean),
        "gr_shale": round_number(gr_shale),
        "clean_cutoff": VSH_CLEAN_CUTOFF,
        "average": round_number(sum(valid_vshale) / len(valid_vshale)) if valid_vshale else None,
        "net_thickness": net_thickness,
        "gross_thickness": gross_thickness,
        "net_to_gross": net_to_gross,
        "clean_interval_count": len(clean_intervals),
        "clean_intervals": clean_intervals[:12],
        "_series": vshale_series,
    }


def add_interpretation(parsed: dict[str, Any]) -> dict[str, Any]:
    curves = parsed.get("curves", [])
    series = parsed.get("series", {})
    depth = parsed.get("depth", {})
    depth_values = depth.get("values", [])
    detected = identify_key_curves(curves)
    gr_curve = detected.get("gamma_ray")
    if gr_curve and gr_curve in series:
        vshale = build_vshale_summary(
            depth_values,
            series[gr_curve],
            gr_curve,
            str(depth.get("unit") or ""),
        )
        vshale_series = vshale.pop("_series", None)
        if vshale.get("available") and vshale_series:
            series["VSH"] = vshale_series
            if not any(curve.get("mnemonic") == "VSH" for curve in curves):
                curves.append(
                    {
                        "mnemonic": "VSH",
                        "unit": "fraction",
                        "description": f"Computed shale volume from {gr_curve}",
                        "synthetic": True,
                        **build_curve_stats(vshale_series),
                    }
                )
    else:
        vshale = {
            "available": False,
            "reason": "Gamma ray curve was not found.",
        }

    parsed["quality_summary"] = build_quality_summary(parsed, detected)
    parsed["petrophysics"] = {"vshale": vshale}
    return parsed


def parse_with_lasio(file_bytes: bytes, filename: str) -> dict[str, Any]:
    try:
        import lasio  # type: ignore
    except Exception as exc:
        raise RuntimeError("lasio is not installed") from exc

    text, encoding = decode_las_bytes(file_bytes)
    las = lasio.read(io.StringIO(text))

    well = section_items_to_dict(las.well)
    params = section_items_to_dict(las.params)
    null_values = get_null_values(well)
    frame = las.df().replace(list(null_values), float("nan"))
    depth_values = clean_series(list(frame.index))

    curve_metadata = []
    series: dict[str, list[float | None]] = {}
    depth_unit = ""
    depth_name = "DEPT"

    for index, curve in enumerate(las.curves):
        mnemonic = str(curve.mnemonic).strip()
        unit = str(curve.unit or "")
        description = str(curve.descr or "")
        if index == 0:
            depth_name = mnemonic or depth_name
            depth_unit = unit
            continue
        if mnemonic not in frame.columns:
            continue
        values = clean_series(list(frame[mnemonic]), null_values)
        series[mnemonic] = values
        curve_metadata.append(
            {
                "mnemonic": mnemonic,
                "unit": unit,
                "description": description,
                **build_curve_stats(values),
            }
        )

    return {
        "filename": filename,
        "parser": "lasio",
        "encoding": encoding,
        "well": well,
        "parameters": params,
        "depth": {
            "mnemonic": depth_name,
            "unit": depth_unit,
            "values": depth_values,
            "start": clean_number(well.get("STRT", {}).get("value")),
            "stop": clean_number(well.get("STOP", {}).get("value")),
            "step": clean_number(well.get("STEP", {}).get("value")),
        },
        "curves": curve_metadata,
        "series": series,
        "row_count": len(depth_values),
    }


HEADER_RE = re.compile(
    r"^\s*(?P<mnemonic>[^.\s]+)\s*\.(?P<unit>[^\s]*)\s*"
    r"(?P<value>.*?)\s*(?::(?P<description>.*))?$"
)


def parse_header_line(line: str) -> tuple[str, dict[str, Any]] | None:
    match = HEADER_RE.match(line)
    if not match:
        return None
    mnemonic = match.group("mnemonic").strip()
    if not mnemonic:
        return None
    raw_value = (match.group("value") or "").strip()
    number_value = clean_number(raw_value)
    return mnemonic, {
        "value": number_value if number_value is not None else raw_value,
        "unit": (match.group("unit") or "").strip(),
        "description": (match.group("description") or "").strip(),
    }


def parse_without_lasio(file_bytes: bytes, filename: str) -> dict[str, Any]:
    text, encoding = decode_las_bytes(file_bytes)
    lines = text.splitlines()
    section = ""
    well: dict[str, Any] = {}
    params: dict[str, Any] = {}
    curves: list[dict[str, Any]] = []
    data_rows: list[list[float | None]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("~"):
            section = stripped[:2].upper()
            if stripped.upper().startswith("~A"):
                section = "~A"
            continue
        if section.startswith("~W"):
            parsed = parse_header_line(line)
            if parsed:
                key, value = parsed
                well[key] = value
        elif section.startswith("~P"):
            parsed = parse_header_line(line)
            if parsed:
                key, value = parsed
                params[key] = value
        elif section.startswith("~C"):
            parsed = parse_header_line(line)
            if parsed:
                key, value = parsed
                curves.append(
                    {
                        "mnemonic": key,
                        "unit": value["unit"],
                        "description": value["description"],
                    }
                )
        elif section == "~A":
            numbers = [clean_number(part) for part in stripped.split()]
            if numbers and all(value is not None for value in numbers):
                data_rows.append(numbers)

    if not curves or not data_rows:
        raise ValueError("Could not parse LAS curve/data sections")

    column_count = min(len(curves), min(len(row) for row in data_rows))
    curves = curves[:column_count]
    data_rows = [row[:column_count] for row in data_rows]
    depth_values = [row[0] for row in data_rows]

    null_values = get_null_values(well)
    curve_metadata = []
    series: dict[str, list[float | None]] = {}

    for column_index, curve in enumerate(curves[1:], 1):
        mnemonic = curve["mnemonic"]
        values = []
        for row in data_rows:
            value = row[column_index]
            if is_null_value(value, null_values):
                value = None
            values.append(value)
        series[mnemonic] = values
        curve_metadata.append({**curve, **build_curve_stats(values)})

    return {
        "filename": filename,
        "parser": "fallback",
        "encoding": encoding,
        "well": well,
        "parameters": params,
        "depth": {
            "mnemonic": curves[0]["mnemonic"],
            "unit": curves[0]["unit"],
            "values": depth_values,
            "start": clean_number(well.get("STRT", {}).get("value")),
            "stop": clean_number(well.get("STOP", {}).get("value")),
            "step": clean_number(well.get("STEP", {}).get("value")),
        },
        "curves": curve_metadata,
        "series": series,
        "row_count": len(depth_values),
    }


def parse_las(file_bytes: bytes, filename: str) -> dict[str, Any]:
    try:
        return parse_with_lasio(file_bytes, filename)
    except Exception:
        return parse_without_lasio(file_bytes, filename)


def cached_parse_las(file_bytes: bytes, filename: str) -> dict[str, Any]:
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if file_hash in PARSE_CACHE:
        cached = copy.deepcopy(PARSE_CACHE[file_hash])
        cached["filename"] = filename
        PARSE_CACHE.move_to_end(file_hash)
        return cached

    parsed = add_interpretation(parse_las(file_bytes, filename))
    parsed = json_safe(parsed)
    PARSE_CACHE[file_hash] = copy.deepcopy(parsed)
    PARSE_CACHE.move_to_end(file_hash)
    while len(PARSE_CACHE) > PARSE_CACHE_LIMIT:
        PARSE_CACHE.popitem(last=False)
    return parsed


def sample_files() -> list[Path]:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(path for path in SAMPLES_DIR.glob("*.las") if path.is_file())


def resolve_sample_path(sample_name: str) -> Path:
    safe_name = Path(sample_name).name
    sample_path = SAMPLES_DIR / safe_name
    if sample_path not in sample_files():
        raise HTTPException(status_code=404, detail="Sample LAS file not found")
    return sample_path


def public_sample_by_id(sample_id: str) -> dict[str, Any]:
    for sample in PUBLIC_SAMPLE_FILES:
        if sample["id"] == sample_id:
            return sample
    raise HTTPException(status_code=404, detail="Public LAS sample not found")


def validate_public_sample_url(url: str) -> None:
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.hostname not in ALLOWED_PUBLIC_SAMPLE_HOSTS:
        raise HTTPException(status_code=400, detail="Public sample URL is not allowed")


def download_public_sample(url: str) -> bytes:
    validate_public_sample_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "LAS Well Log Viewer/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > PUBLIC_SAMPLE_LIMIT_BYTES:
                raise HTTPException(status_code=413, detail="Public LAS file is larger than the configured limit")

            chunks = []
            total_size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > PUBLIC_SAMPLE_LIMIT_BYTES:
                    raise HTTPException(status_code=413, detail="Public LAS file is larger than the configured limit")
                chunks.append(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not download public LAS file: {exc}") from exc

    file_bytes = b"".join(chunks)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Downloaded public LAS file is empty")
    return file_bytes


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "LAS Well Log API",
        "status": "ok",
        "endpoints": [
            "/health",
            "/api/parse-las",
            "/api/samples",
            "/api/public-datasets",
            "/api/public-samples",
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/samples")
def list_samples() -> dict[str, list[dict[str, Any]]]:
    return {
        "samples": [
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
            }
            for path in sample_files()
        ]
    }


@app.get("/api/public-datasets")
def list_public_datasets() -> dict[str, list[dict[str, Any]]]:
    return {"datasets": PUBLIC_DATASETS}


@app.get("/api/public-samples")
def list_public_samples() -> dict[str, list[dict[str, Any]]]:
    return {
        "samples": [
            {key: value for key, value in sample.items() if key != "url"}
            for sample in PUBLIC_SAMPLE_FILES
        ]
    }


@app.get("/api/public-samples/{sample_id}/parse")
def parse_public_sample_las(sample_id: str) -> dict[str, Any]:
    sample = public_sample_by_id(sample_id)
    file_bytes = download_public_sample(sample["url"])
    try:
        parsed = cached_parse_las(file_bytes, sample["filename"])
        parsed["public_sample"] = {
            key: value for key, value in sample.items() if key != "url"
        }
        return parsed
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse public LAS file: {exc}") from exc


@app.get("/api/samples/{sample_name}/parse")
def parse_sample_las(sample_name: str) -> dict[str, Any]:
    sample_path = resolve_sample_path(sample_name)
    try:
        return cached_parse_las(sample_path.read_bytes(), sample_path.name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse sample LAS file: {exc}") from exc


@app.post("/api/parse-las")
async def parse_las_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = file.filename or "upload.las"
    if not filename.lower().endswith(".las"):
        raise HTTPException(status_code=400, detail="Only .las files are supported")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")

    try:
        return cached_parse_las(file_bytes, filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse LAS file: {exc}") from exc
