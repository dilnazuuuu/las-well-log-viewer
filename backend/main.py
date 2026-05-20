from __future__ import annotations

import math
import os
import re
import tempfile
import copy
import hashlib
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


app = FastAPI(title="LAS Well Log API", version="0.1.0")
DEFAULT_NULL_VALUES = {-999.25, -9999.0, 999.25, 9999.0}
PARSE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
PARSE_CACHE_LIMIT = int(os.getenv("PARSE_CACHE_LIMIT", "16"))


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
    return {
        "min": min(valid) if valid else None,
        "max": max(valid) if valid else None,
        "null_count": len(values) - len(valid),
    }


def parse_with_lasio(file_bytes: bytes, filename: str) -> dict[str, Any]:
    try:
        import lasio  # type: ignore
    except Exception as exc:
        raise RuntimeError("lasio is not installed") from exc

    with tempfile.NamedTemporaryFile(suffix=".las", delete=False) as handle:
        handle.write(file_bytes)
        temp_path = Path(handle.name)

    try:
        las = lasio.read(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)

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
    r"^\s*(?P<mnemonic>[A-Za-z0-9_]+)\s*\.(?P<unit>[^\s]*)\s*"
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
    text = file_bytes.decode("utf-8", errors="replace")
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

    parsed = parse_las(file_bytes, filename)
    PARSE_CACHE[file_hash] = copy.deepcopy(parsed)
    PARSE_CACHE.move_to_end(file_hash)
    while len(PARSE_CACHE) > PARSE_CACHE_LIMIT:
        PARSE_CACHE.popitem(last=False)
    return parsed


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
