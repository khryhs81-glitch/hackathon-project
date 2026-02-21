from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any


# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).resolve().parent

# CSV is inside the folder labeled "important_files"
TIDY_CSV_PATH = BASE_DIR / "important_files" / "davidson_courses_tidy.csv"

# Where to write/read students.csv (in same folder as this script)
STUDENTS_CSV_PATH = BASE_DIR / "students.csv"


# ============================================================
# HELPERS
# ============================================================
def _clean(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _to_int_or_none(s: Any) -> Optional[int]:
    s = _clean(s)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _to_float_or_none(s: Any) -> Optional[float]:
    s = _clean(s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_seats_value(seats_left: Any) -> tuple[Optional[int], Optional[int]]:
    """
    Seats field in your tidy CSV might look like:
      - "23/25" (enrolled/capacity)
      - "" or None
      - "23" (ambiguous; we'll treat as enrolled, capacity unknown)

    Returns: (enrolled, capacity)
    """
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
    """
    Accepts:
      - "20001"
      - "20001 | Intro to Africana Studies"
    Returns:
      - "20001"
    """
    s = _clean(cell)
    if not s:
        return ""
    if "|" in s:
        s = s.split("|", 1)[0].strip()
    return s


# ============================================================
# CLASS MODEL (tidy CSV -> Class)
# ============================================================
@dataclass
class Class:
    # identity
    class_id: str  # CRN
    subject: str
    course_number: str
    section: str
    title: str

    # logistics
    credits: Optional[float] = None
    instructor: str = ""
    meeting_days: str = ""    # e.g. "MWF"
    start_time: str = ""      # e.g. "1530"
    end_time: str = ""        # e.g. "1620"
    building: str = ""
    room: str = ""

    # enrollment
    enrolled: Optional[int] = None
    capacity: Optional[int] = None

    raw: Dict[str, str] = field(default_factory=dict)

    @staticmethod
    def from_tidy_row(row: Dict[str, str]) -> "Class":
        """
        Tries common header variants. If your tidy CSV uses different headers,
        update the 'pick()' keys below.
        """
        def pick(*keys: str) -> str:
            for k in keys:
                if k in row and _clean(row[k]) != "":
                    return _clean(row[k])
            return ""

        crn = pick("crn", "CRN", "class_id", "Class ID")
        subject = pick("subject", "SUBJECT", "subject_code", "Subject Code")
        course_number = pick("course_number", "COURSE_NUMBER", "course", "Course Number")
        section = pick("section", "SECTION", "sec", "Section")
        title = pick("title", "TITLE", "course_title", "Course Title")

        credits = _to_float_or_none(pick("credits", "CREDITS", "credit_hours", "Credit Hours"))

        instructor = pick("instructor", "INSTRUCTOR", "instructors", "Instructor")
        meeting_days = pick("weekdays", "WEEKDAYS", "days", "Days")
        start_time = pick("start_time", "START_TIME", "Start Time")
        end_time = pick("end_time", "END_TIME", "End Time")
        building = pick("building", "BUILDING", "Building")
        room = pick("room", "ROOM", "Room")

        seats_field = pick("seats_left", "SEATS_LEFT", "seats", "Seats", "enrolled_capacity")
        enrolled = _to_int_or_none(pick("enrolled", "ENROLLED"))
        capacity = _to_int_or_none(pick("capacity", "CAPACITY"))

        if enrolled is None and capacity is None and seats_field:
            enrolled, capacity = parse_seats_value(seats_field)

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
            building=building,
            room=room,
            enrolled=enrolled,
            capacity=capacity,
            raw=dict(row),
        )


def load_classes_from_tidy_csv(path: Path) -> List[Class]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found at: {path}")

    classes: List[Class] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            classes.append(Class.from_tidy_row(row))
    return classes


# ============================================================
# STUDENTS + LOTTERY
# ============================================================
class Student:
    def __init__(self, student_id: str, choices: List[List[str]], grade: int):
        self.student_id = student_id
        self.choices = choices                  # list of ranked lists of CRNs
        self.assigned_classes: List[Optional[str]] = [None] * len(choices)
        self.grade = grade
        self.lottery_number: Optional[int] = None


def assign_lottery_by_grade(students_by_grade: Dict[int, List[Student]], grade_order: List[int]) -> None:
    """
    Assign fully random, unique lottery numbers.
    Seniors get the lowest number range, then juniors, etc.
    """
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

assign_lottery_by_grade(
    students_by_grade,
    grade_order=[12, 11, 10, 9]
)

# -------------------------
# Lottery Debug Tools
# -------------------------
def print_lottery_by_grade(students_by_grade):
    for grade in sorted(students_by_grade.keys(), reverse=True):
        print(f"\n--- Grade {grade} Lottery Order ---")
        students = students_by_grade[grade]  # keep original shuffled order
        for student in students:
            print(f"{student.student_id} -> Lottery #{student.lottery_number}")

def check_for_duplicate_lottery_numbers(students_by_grade):
    seen = set()
    duplicates = []
    for grade in students_by_grade:
        for student in students_by_grade[grade]:
            if student.lottery_number in seen:
                duplicates.append(student.lottery_number)
            else:
                seen.add(student.lottery_number)

    if duplicates:
        print("Duplicate lottery numbers found:", duplicates)
    else:
        print("No duplicate lottery numbers.")

# -------------------------
# Scheduling Function
# -------------------------
def run_lottery_for_grade(students):
    students_sorted = sorted(students, key=lambda s: s.lottery_number)
    num_choices = len(students_sorted[0].choices)

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

# -------------------------
# Run Scheduling
# -------------------------
run_lottery_for_grade(students_by_grade[12])
run_lottery_for_grade(students_by_grade[11])
run_lottery_for_grade(students_by_grade[10])
run_lottery_for_grade(students_by_grade[9])

    # 8) Output results
    all_students = students_by_grade[12] + students_by_grade[11] + students_by_grade[10] + students_by_grade[9]

    print("\n---- Student Schedules ----")
    for student in all_students:
        print(f"\nStudent {student.student_id} (Grade {student.grade}) - Lottery #{student.lottery_number}")
        for idx, class_id in enumerate(student.assigned_classes):
            if class_id:
                cls = class_dict[class_id]
                print(f" Round {idx+1}: {cls.class_id} | {class_pretty(cls)}")
            else:
                print(f" Round {idx+1}: No class assigned")

print("\n---- Final Class Enrollment ----")
for cls in CLASSES:
    print(f"{cls.name} ({cls.class_id}) - {len(cls.enrolled_students)}/{cls.capacity}")
    print(" Students:", cls.enrolled_students)

