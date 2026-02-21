from __future__ import annotations

import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

BASE_DIR = Path(__file__).resolve().parent
TIDY_CSV_PATH = BASE_DIR / "important_files" / "davidson_courses_tidy.csv"


def _clean(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _to_int_or_none(s: Any) -> Optional[int]:
    s = _clean(s)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except Exception:
            return None


def _to_float_or_none(s: Any) -> Optional[float]:
    s = _clean(s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_seats_value(seats_left: Any) -> Tuple[Optional[int], Optional[int]]:
    s = _clean(seats_left)
    if not s:
        return (None, None)

    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return (int(a.strip()), int(b.strip()))
        except ValueError:
            return (None, None)

    try:
        return (int(s), None)
    except ValueError:
        return (None, None)


def extract_class_id(cell: str) -> str:
    s = _clean(cell)
    if not s:
        return ""
    if "|" in s:
        s = s.split("|", 1)[0].strip()
    return s


def _parse_crs_sec(crs_sec: str) -> Tuple[str, str, str]:
    s = _clean(crs_sec)
    if not s or "-" not in s:
        return ("", "", "")
    parts = s.split("-")
    if len(parts) < 3:
        return ("", "", "")
    subj = parts[0].strip()
    num = parts[1].strip()
    sec = "-".join(parts[2:]).strip()
    return (subj, num, sec)


def _parse_time_range_to_hhmm(time_range: str) -> Tuple[str, str]:
    s = _clean(time_range)
    if not s or "-" not in s:
        return ("", "")
    left, right = [x.strip() for x in s.split("-", 1)]

    def parse_one(t: str) -> str:
        m = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", t, re.I)
        if not m:
            return ""
        hh = int(m.group(1))
        mm = int(m.group(2))
        ap = m.group(3).upper()
        if ap == "AM":
            if hh == 12:
                hh = 0
        else:
            if hh != 12:
                hh += 12
        return f"{hh:02d}{mm:02d}"

    return (parse_one(left), parse_one(right))


@dataclass
class Class:
    class_id: str  # CRN
    subject: str = ""
    course_number: str = ""
    section: str = ""
    title: str = ""

    credits: Optional[float] = None
    instructor: str = ""
    meeting_days: str = ""
    start_time: str = ""
    end_time: str = ""
    time_range: str = ""
    building: str = ""
    room: str = ""

    enrolled: Optional[int] = None
    capacity: Optional[int] = None

    raw: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def from_tidy_row(row: Dict[str, str]) -> "Class":
        def pick(*keys: str) -> str:
            for k in keys:
                if k in row and _clean(row[k]) != "":
                    return _clean(row[k])
            return ""

        crn = pick("crn", "CRN", "class_id", "Class ID")
        title = pick("title", "Title", "TITLE", "course_title", "Course Title")
        credits = _to_float_or_none(pick("credits", "Cred", "CREDITS", "credit_hours", "Credit Hours"))

        subject = pick("subject", "SUBJECT", "subject_code", "Subject Code")
        course_number = pick("course_number", "COURSE_NUMBER", "course", "Course Number")
        section = pick("section", "SECTION", "sec", "Section")

        if not subject or not course_number or not section:
            crs_sec = pick("Crs & Sec", "crs_sec", "CRS_SEC")
            subj2, num2, sec2 = _parse_crs_sec(crs_sec)
            subject = subject or subj2
            course_number = course_number or num2
            section = section or sec2

        instructor = pick("instructor", "Instructor", "INSTRUCTOR", "instructors", "Instructors")
        meeting_days = pick("weekdays", "Days", "days", "WEEKDAYS")

        start_time = pick("start_time", "START_TIME", "Start Time")
        end_time = pick("end_time", "END_TIME", "End Time")
        time_range = pick("time_range", "Time", "TIME")

        if (not start_time or not end_time) and time_range:
            s, e = _parse_time_range_to_hhmm(time_range)
            start_time = start_time or s
            end_time = end_time or e

        building = pick("building", "BUILDING", "Building")
        room = pick("room", "ROOM", "Room")

        if not building and room and " " in room:
            b, r = room.split(" ", 1)
            building = b
            room = r

        seats_field = pick("seats_left", "SEATS_LEFT", "Seats Left", "seats", "Seats", "enrolled_capacity")
        enrolled = _to_int_or_none(pick("enrolled", "ENROLLED"))
        capacity = _to_int_or_none(pick("capacity", "CAPACITY"))

        if (enrolled is None or capacity is None) and seats_field:
            e2, c2 = parse_seats_value(seats_field)
            enrolled = enrolled if enrolled is not None else e2
            capacity = capacity if capacity is not None else c2

        if not crn:
            raise ValueError(f"Missing CRN/class_id in row. Row keys: {list(row.keys())}")

        return Class(
            class_id=crn,
            subject=subject,
            course_number=course_number,
            section=section,
            title=title,
            credits=credits,
            instructor=instructor,
            meeting_days=meeting_days,
            start_time=start_time,
            end_time=end_time,
            time_range=time_range,
            building=building,
            room=room,
            enrolled=enrolled,
            capacity=capacity,
            raw=dict(row),
        )


def load_classes_from_tidy_csv(path: Path = TIDY_CSV_PATH) -> List[Class]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found at: {path}")

    classes: List[Class] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            classes.append(Class.from_tidy_row(row))
    return classes


class Student:
    def __init__(self, student_id: str, choices: List[List[str]], grade: int):
        self.student_id = student_id
        self.choices = choices
        self.assigned_classes: List[Optional[str]] = [None] * len(choices)
        self.grade = grade
        self.lottery_number: Optional[int] = None


def assign_lottery_by_grade(students_by_grade: Dict[int, List[Student]], grade_order: List[int]) -> None:
    current_min = 1
    for grade in grade_order:
        students = students_by_grade.get(grade, [])
        count = len(students)

        grade_numbers = list(range(current_min, current_min + count))
        random.shuffle(grade_numbers)
        random.shuffle(students)

        for student, lottery_number in zip(students, grade_numbers):
            student.lottery_number = lottery_number

        current_min += count


def run_lottery_for_grade(
    students: List[Student],
    class_dict: Dict[str, Class],
    rosters: Dict[str, List[str]],
    capacity_by_class_id: Dict[str, int],
) -> None:
    students_sorted = sorted(students, key=lambda s: (s.lottery_number is None, s.lottery_number))
    if not students_sorted:
        return

    num_rounds = len(students_sorted[0].choices)

    for round_idx in range(num_rounds):
        for student in students_sorted:
            if student.assigned_classes[round_idx] is not None:
                continue

            for class_id in student.choices[round_idx]:
                if class_id not in class_dict:
                    continue
                if len(rosters[class_id]) < capacity_by_class_id[class_id]:
                    rosters[class_id].append(student.student_id)
                    student.assigned_classes[round_idx] = class_id
                    break


def class_pretty(cls: Class) -> str:
    where = " ".join([x for x in [cls.building, cls.room] if x])
    time = cls.time_range or " ".join([x for x in [cls.meeting_days, f"{cls.start_time}-{cls.end_time}".strip("-")] if x])
    bits = [cls.title] if cls.title else []
    if time:
        bits.append(time)
    if where:
        bits.append(where)
    return " | ".join(bits) if bits else cls.class_id


def run_lottery_from_payload(
    students_payload: List[Dict[str, Any]],
    *,
    force_capacity: Optional[int] = None,
    grade_order: tuple[int, ...] = (12, 11, 10, 9),
) -> Dict[str, Any]:
    grade_order_list = list(grade_order)
    classes = load_classes_from_tidy_csv(TIDY_CSV_PATH)
    class_dict: Dict[str, Class] = {c.class_id: c for c in classes}
    class_ids = list(class_dict.keys())

    capacity_by_class_id: Dict[str, int] = {}
    if force_capacity is not None:
        try:
            force_capacity = int(force_capacity)
        except Exception:
            raise ValueError("force_capacity must be an integer")
        if force_capacity <= 0:
            raise ValueError("force_capacity must be > 0")
    for c in classes:
        capacity_by_class_id[c.class_id] = int(force_capacity) if force_capacity is not None else (c.capacity if c.capacity is not None else 25)

    rosters: Dict[str, List[str]] = {cid: [] for cid in class_ids}

    students_by_grade: Dict[int, List[Student]] = {9: [], 10: [], 11: [], 12: []}
    for s in students_payload:
        sid = str(s.get("student_id", "")).strip()
        grade = int(s.get("grade", 12))
        choices = s.get("choices", [])
        if not sid:
            continue
        if not isinstance(choices, list) or not choices:
            choices = [[] for _ in range(4)]
        norm_choices: List[List[str]] = []
        for round_list in choices:
            if isinstance(round_list, list):
                norm_choices.append([str(x).strip() for x in round_list if str(x).strip()])
            else:
                norm_choices.append([])
        students_by_grade.setdefault(grade, []).append(Student(sid, norm_choices, grade))

    assign_lottery_by_grade(students_by_grade, grade_order=grade_order_list)

    for g in grade_order:
        run_lottery_for_grade(students_by_grade.get(g, []), class_dict, rosters, capacity_by_class_id)

    all_students: List[Student] = []
    for g in grade_order:
        all_students.extend(sorted(students_by_grade.get(g, []), key=lambda st: (st.lottery_number is None, st.lottery_number)))

    students_out = []
    for st in all_students:
        students_out.append({
            "student_id": st.student_id,
            "grade": st.grade,
            "lottery_number": st.lottery_number,
            "assigned_classes": st.assigned_classes,
        })

    classes_out = []
    for cid in class_ids:
        c = class_dict[cid]
        classes_out.append({
            "class_id": cid,
            "display": f"{c.subject} {c.course_number}-{c.section}".strip(),
            "title": c.title,
            "credits": c.credits,
            "capacity": capacity_by_class_id[cid],
            "enrolled_roster_count": len(rosters[cid]),
            "roster": rosters[cid],
            "pretty": class_pretty(c),
        })

    return {"students": students_out, "classes": classes_out}


if __name__ == "__main__":
    classes = load_classes_from_tidy_csv(TIDY_CSV_PATH)
    print(f"Loaded {len(classes)} classes from: {TIDY_CSV_PATH}")