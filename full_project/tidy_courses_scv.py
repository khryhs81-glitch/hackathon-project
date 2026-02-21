"""Convert scraper output (normalized CSV) into a tidy CSV used by the web app.

Defaults are relative to ./important_files so you can deploy the app with the CSV bundled.
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Optional, Tuple, Union


BASE_DIR = Path(__file__).resolve().parent
IMPORTANT_DIR = BASE_DIR / "important_files"

DEFAULT_SRC: Path = IMPORTANT_DIR / "davidson_courses_normalized.csv"
DEFAULT_OUT: Path = IMPORTANT_DIR / "davidson_courses_tidy.csv"


def parse_json_cell(s: Any) -> Any:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if s[0] in "[{":
        try:
            return json.loads(s)
        except Exception:
            return None
    return s


def subject_code(subject_cell: Any) -> str:
    obj = parse_json_cell(subject_cell)
    if isinstance(obj, dict):
        return (obj.get("code", "") or "").strip()
    return str(subject_cell).strip() if subject_cell else ""


def format_time_hhmm(hhmm: Any) -> str:
    if not hhmm:
        return ""
    hhmm = str(hhmm).zfill(4)
    try:
        h = int(hhmm[:2])
        m = int(hhmm[2:])
    except ValueError:
        return ""
    if h == 0:
        h12, ampm = 12, "AM"
    elif h == 12:
        h12, ampm = 12, "PM"
    elif h > 12:
        h12, ampm = h - 12, "PM"
    else:
        h12, ampm = h, "AM"
    return f"{h12}:{m:02d} {ampm}"


def format_time_range(start: Any, end: Any) -> str:
    if not start or not end:
        return ""
    a = format_time_hhmm(start)
    b = format_time_hhmm(end)
    return f"{a} - {b}" if a and b else ""


def format_instructors(instr_cell: Any) -> str:
    obj = parse_json_cell(instr_cell)
    if obj is None:
        return ""
    if isinstance(obj, dict):
        obj = [obj]
    if isinstance(obj, str):
        return obj
    out = []
    if isinstance(obj, list):
        for d in obj:
            if isinstance(d, str):
                out.append(d)
                continue
            if not isinstance(d, dict):
                continue
            fn = (d.get("first_name") or d.get("firstName") or "").strip()
            ln = (d.get("last_name") or d.get("lastName") or "").strip()
            if ln and fn:
                out.append(f"{ln} {fn[0]}")
            elif ln:
                out.append(ln)
            elif fn:
                out.append(fn)
    return "; ".join([x for x in out if x])


def pick_meeting_fields(meetings_cell: Any) -> Tuple[str, str, str, str, str]:
    """Returns: (weekdays, start_time, end_time, building, room)."""
    meetings = parse_json_cell(meetings_cell)
    if not meetings:
        return ("", "", "", "", "")
    if isinstance(meetings, dict):
        meetings = [meetings]
    if not isinstance(meetings, list) or not meetings:
        return ("", "", "", "", "")

    m = meetings[0] if isinstance(meetings[0], dict) else {}
    weekdays = (m.get("weekdays") or "").strip()
    start = str(m.get("start_time") or "").strip()
    end = str(m.get("end_time") or "").strip()

    building_obj = m.get("building") or {}
    building = ""
    if isinstance(building_obj, dict):
        building = (building_obj.get("code") or building_obj.get("name") or "").strip()
    elif isinstance(building_obj, str):
        building = building_obj.strip()

    room = str(m.get("room") or "").strip()
    return (weekdays, start, end, building, room)


def to_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def make_tidy_csv(
    src: Union[str, Path] = DEFAULT_SRC,
    out: Union[str, Path] = DEFAULT_OUT,
) -> Path:
    """Convert scraper's normalized CSV -> tidy CSV (display columns + machine columns)."""
    src_path = Path(src)
    out_path = Path(out)

    if not src_path.exists():
        raise FileNotFoundError(f"Source CSV not found: {src_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    with src_path.open(newline="", encoding="utf-8") as f_in, out_path.open("w", newline="", encoding="utf-8") as f_out:
        r = csv.DictReader(f_in)

        fieldnames = [
            # human-friendly columns (compat)
            "Crs & Sec",
            "CRN",
            "Title",
            "Cred",
            "Days",
            "Time",
            "Room",
            "Instructor",
            "Notes",
            "Grad. Reqs.",
            "Seats Left",
            # machine-friendly columns
            "subject",
            "course_number",
            "section",
            "credits",
            "weekdays",
            "start_time",
            "end_time",
            "building",
            "room",
            "enrolled",
            "capacity",
            "seats_remaining",
        ]

        w = csv.DictWriter(f_out, fieldnames=fieldnames)
        w.writeheader()

        for row in r:
            subj = subject_code(row.get("subject"))
            course_num = to_int(row.get("course_number"))
            section = (row.get("section") or "").strip()
            crs_sec = f"{subj}-{course_num:03d}-{section}" if subj and course_num is not None and section else ""

            weekdays, start_time, end_time, building, room = pick_meeting_fields(row.get("meetings"))
            time_str = format_time_range(start_time, end_time)
            room_str = f"{building} {room}".strip() if (building or room) else ""

            instr_str = format_instructors(row.get("instructors"))

            enrolled = to_int(row.get("enrolled"))
            capacity = to_int(row.get("capacity"))
            seats_remaining = to_int(row.get("seats_remaining"))

            seats_disp = (
                f"{enrolled}/{capacity}"
                if (enrolled is not None and capacity is not None)
                else (str(enrolled) if enrolled is not None else "")
            )

            w.writerow(
                {
                    # display
                    "Crs & Sec": crs_sec,
                    "CRN": row.get("crn") or "",
                    "Title": row.get("title") or "",
                    "Cred": row.get("credits") or "",
                    "Days": weekdays,
                    "Time": time_str,
                    "Room": room_str,
                    "Instructor": instr_str,
                    "Notes": row.get("notes") or "",
                    "Grad. Reqs.": "",
                    "Seats Left": seats_disp,
                    # machine
                    "subject": subj,
                    "course_number": course_num if course_num is not None else "",
                    "section": section,
                    "credits": row.get("credits") or "",
                    "weekdays": weekdays,
                    "start_time": start_time,
                    "end_time": end_time,
                    "building": building,
                    "room": room,
                    "enrolled": enrolled if enrolled is not None else "",
                    "capacity": capacity if capacity is not None else "",
                    "seats_remaining": seats_remaining if seats_remaining is not None else "",
                }
            )

    return out_path


def _cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--src", default=str(DEFAULT_SRC), help="Path to normalized CSV")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="Path to tidy CSV")
    args = p.parse_args()

    out_path = make_tidy_csv(args.src, args.out)
    print(f"Saved tidy CSV: {out_path}")


if __name__ == "__main__":
    _cli()
