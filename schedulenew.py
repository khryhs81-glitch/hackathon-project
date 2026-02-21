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


def generate_students_csv(
    out_path: Path,
    class_ids: List[str],
    class_dict: Dict[str, Class],
    num_students: int = 200,
    grades: List[int] = [9, 10, 11, 12],
    num_rounds: int = 4,
    picks_per_round: int = 5,
) -> None:
    """
    Creates students.csv with columns:
      student_id, grade, choice1_1..choice1_5, ..., choice4_1..choice4_5

    Each choice cell is written as:
      "CRN | Title"
    Scheduler will parse CRN back out when loading.
    """
    if len(class_ids) == 0:
        raise ValueError("No classes available to sample from. Your tidy CSV load returned 0 classes.")

    header = ["student_id", "grade"]
    for r in range(1, num_rounds + 1):
        for k in range(1, picks_per_round + 1):
            header.append(f"choice{r}_{k}")

    def label(cid: str) -> str:
        cls = class_dict.get(cid)
        title = cls.title if cls else ""
        return f"{cid} | {title}" if title else cid

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for i in range(1, num_students + 1):
            grade = random.choice(grades)
            row = [f"S{i:03}", grade]

            for _ in range(num_rounds):
                k = min(picks_per_round, len(class_ids))
                ranked_ids = random.sample(class_ids, k)

                ranked_cells = [label(cid) for cid in ranked_ids]
                ranked_cells += [""] * (picks_per_round - len(ranked_cells))
                row.extend(ranked_cells)

            writer.writerow(row)


def load_students_from_csv(path: Path, num_rounds: int = 4, picks_per_round: int = 5) -> Dict[int, List[Student]]:
    students_by_grade: Dict[int, List[Student]] = {9: [], 10: [], 11: [], 12: []}

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            grade = int(row["grade"])
            choices: List[List[str]] = []

            for r in range(1, num_rounds + 1):
                ranked: List[str] = []
                for k in range(1, picks_per_round + 1):
                    raw_cell = row.get(f"choice{r}_{k}", "")
                    cid = extract_class_id(raw_cell)
                    if cid:
                        ranked.append(cid)
                choices.append(ranked)

            students_by_grade[grade].append(Student(row["student_id"], choices, grade))

    return students_by_grade


def run_lottery_for_grade(
    students: List[Student],
    class_dict: Dict[str, Class],
    rosters: Dict[str, List[str]],
    capacity_by_class_id: Dict[str, int],
) -> None:
    """
    For each "round" of choices: process students in lottery order.
    Attempt to place them into their highest available choice.
    """
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
    time = " ".join([x for x in [cls.meeting_days, f"{cls.start_time}-{cls.end_time}".strip("-")] if x])
    bits = [cls.title]
    if time:
        bits.append(time)
    if where:
        bits.append(where)
    return " | ".join(bits)


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    # 1) Load classes from tidy CSV
    CLASSES = load_classes_from_tidy_csv(TIDY_CSV_PATH)
    class_dict: Dict[str, Class] = {c.class_id: c for c in CLASSES}
    CLASS_IDS = list(class_dict.keys())

    print(f"Loaded {len(CLASSES)} classes from: {TIDY_CSV_PATH}")

    # 2) Capacity setup
    # Turn this on for testing: every class capacity = 25
    FORCE_CAPACITY_25_FOR_TESTING = True

    capacity_by_class_id: Dict[str, int] = {}
    for c in CLASSES:
        if FORCE_CAPACITY_25_FOR_TESTING:
            capacity_by_class_id[c.class_id] = 25
        else:
            capacity_by_class_id[c.class_id] = c.capacity if c.capacity is not None else 25

    # 3) Build rosters
    rosters: Dict[str, List[str]] = {cid: [] for cid in CLASS_IDS}

    # 4) Generate students.csv (with "CRN | Title") if desired
    REGENERATE_STUDENTS_CSV = True
    NUM_STUDENTS = 200
    GRADES = [9, 10, 11, 12]
    NUM_ROUNDS = 4
    PICKS_PER_ROUND = 5

    if REGENERATE_STUDENTS_CSV:
        generate_students_csv(
            out_path=STUDENTS_CSV_PATH,
            class_ids=CLASS_IDS,
            class_dict=class_dict,
            num_students=NUM_STUDENTS,
            grades=GRADES,
            num_rounds=NUM_ROUNDS,
            picks_per_round=PICKS_PER_ROUND,
        )
        print(f"students.csv generated at: {STUDENTS_CSV_PATH}")

    # 5) Load students (parses CRN out of "CRN | Title")
    students_by_grade = load_students_from_csv(
        STUDENTS_CSV_PATH,
        num_rounds=NUM_ROUNDS,
        picks_per_round=PICKS_PER_ROUND,
    )

    # 6) Assign lottery numbers (seniors first)
    assign_lottery_by_grade(students_by_grade, grade_order=[12, 11, 10, 9])

    # 7) Run scheduling by grade
    run_lottery_for_grade(students_by_grade[12], class_dict, rosters, capacity_by_class_id)
    run_lottery_for_grade(students_by_grade[11], class_dict, rosters, capacity_by_class_id)
    run_lottery_for_grade(students_by_grade[10], class_dict, rosters, capacity_by_class_id)
    run_lottery_for_grade(students_by_grade[9],  class_dict, rosters, capacity_by_class_id)

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

print_lottery_by_grade(students_by_grade)
check_for_duplicate_lottery_numbers(students_by_grade)