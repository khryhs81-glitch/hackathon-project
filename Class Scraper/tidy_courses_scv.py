import csv, json

SRC = "davidson_courses_normalized.csv"
OUT = "davidson_courses_tidy.csv"

def parse_json_cell(s):
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

def subject_code(subject_cell):
    obj = parse_json_cell(subject_cell)
    if isinstance(obj, dict):
        return obj.get("code", "") or ""
    return str(subject_cell).strip() if subject_cell else ""

def format_time_hhmm(hhmm):
    if not hhmm:
        return ""
    hhmm = str(hhmm).zfill(4)
    h = int(hhmm[:2]); m = int(hhmm[2:])
    if h == 0:
        h12, ampm = 12, "AM"
    elif h == 12:
        h12, ampm = 12, "PM"
    elif h > 12:
        h12, ampm = h - 12, "PM"
    else:
        h12, ampm = h, "AM"
    return f"{h12}:{m:02d} {ampm}"

def format_time_range(start, end):
    if not start or not end:
        return ""
    return f"{format_time_hhmm(start)} - {format_time_hhmm(end)}"

def format_instructors(instr_cell):
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
                out.append(d); continue
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

def pick_meeting_fields(meetings_cell):
    meetings = parse_json_cell(meetings_cell)
    if not meetings:
        return ("", "", "")
    if isinstance(meetings, dict):
        meetings = [meetings]
    if not isinstance(meetings, list) or not meetings:
        return ("", "", "")

    m = meetings[0]
    days = m.get("weekdays") or ""
    start = m.get("start_time")
    end = m.get("end_time")
    time_str = format_time_range(start, end)

    building = m.get("building") or {}
    bcode = building.get("code") if isinstance(building, dict) else ""
    room = m.get("room") or ""
    room_str = f"{bcode} {room}".strip() if (bcode or room) else ""
    return (days, time_str, room_str)

def to_int(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None

with open(SRC, newline="", encoding="utf-8") as f_in, open(OUT, "w", newline="", encoding="utf-8") as f_out:
    r = csv.DictReader(f_in)
    fieldnames = ["Crs & Sec","CRN","Title","Cred","Days","Time","Room","Instructor","Notes","Grad. Reqs.","Seats Left"]
    w = csv.DictWriter(f_out, fieldnames=fieldnames)
    w.writeheader()

    for row in r:
        subj = subject_code(row.get("subject"))
        course_num = to_int(row.get("course_number"))
        section = (row.get("section") or "").strip()
        crs_sec = f"{subj}-{course_num:03d}-{section}" if subj and course_num is not None and section else ""

        days, time_str, room_str = pick_meeting_fields(row.get("meetings"))
        instr_str = format_instructors(row.get("instructors"))

        enrolled = to_int(row.get("enrolled"))
        capacity = to_int(row.get("capacity"))
        # fallback: in your older export this held the left number
        fallback = to_int(row.get("seats_remaining"))
        if enrolled is None and fallback is not None:
            enrolled = fallback

        seats_disp = f"{enrolled}/{capacity}" if (enrolled is not None and capacity is not None) else (str(enrolled) if enrolled is not None else "")

        w.writerow({
            "Crs & Sec": crs_sec,
            "CRN": row.get("crn") or "",
            "Title": row.get("title") or "",
            "Cred": row.get("credits") or "",
            "Days": days,
            "Time": time_str,
            "Room": room_str,
            "Instructor": instr_str,
            "Notes": row.get("notes") or "",
            "Grad. Reqs.": "",
            "Seats Left": seats_disp,
        })

print(f"Saved tidy CSV: {OUT}")