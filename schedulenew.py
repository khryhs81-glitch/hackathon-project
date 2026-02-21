# -------------------------
# Classes
# -------------------------
class Class:
    def __init__(self, class_id, name, time, location, capacity):
        self.class_id = class_id
        self.name = name
        self.time = time
        self.location = location
        self.capacity = capacity
        self.enrolled_students = []

class Student:
    def __init__(self, student_id, choices, grade):
        self.student_id = student_id
        self.choices = choices
        self.assigned_classes = [None] * len(choices)
        self.grade = grade
        self.lottery_number = None

import csv
import random

# -------------------------
# Configuration
# -------------------------
NUM_STUDENTS = 200
GRADES = [9, 10, 11, 12]

# -------------------------
# Create Class Objects
# -------------------------
CLASSES = [
    Class("C101", "Algebra I", "Mon 9-10", "Room A", 40),
    Class("C102", "Biology", "Mon 10-11", "Room B", 35),
    Class("C103", "World History", "Tue 9-10", "Room C", 40),
    Class("C104", "Art I", "Wed 9-10", "Room D", 25),
    Class("C105", "Choir", "Thu 10-11", "Room E", 25),
    Class("C106", "Physical Education", "Fri 9-10", "Gym", 50),
    Class("C107", "Chemistry", "Mon 11-12", "Room F", 35),
    Class("C108", "English", "Tue 10-11", "Room G", 40),
    Class("C109", "Computer Science", "Wed 10-11", "Room H", 30),
    Class("C110", "Spanish I", "Thu 9-10", "Room I", 30),
]

CLASS_IDS = [c.class_id for c in CLASSES]
class_dict = {c.class_id: c for c in CLASSES}

# -------------------------
# Generate students.csv (NO lottery column)
# -------------------------
with open("students.csv", "w", newline="") as f:
    writer = csv.writer(f)

    header = [
        "student_id","grade",
        "choice1_1","choice1_2","choice1_3","choice1_4","choice1_5",
        "choice2_1","choice2_2","choice2_3","choice2_4","choice2_5",
        "choice3_1","choice3_2","choice3_3","choice3_4","choice3_5",
        "choice4_1","choice4_2","choice4_3","choice4_4","choice4_5",
    ]
    writer.writerow(header)

    for i in range(1, NUM_STUDENTS + 1):
        grade = random.choice(GRADES)
        row = [f"S{i:03}", grade]

        for _ in range(4):
            ranked_classes = random.sample(CLASS_IDS, 5)
            row.extend(ranked_classes)

        writer.writerow(row)

print("students.csv generated successfully.")

# -------------------------
# Load Students
# -------------------------
students_by_grade = {9: [], 10: [], 11: [], 12: []}

with open("students.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:

        choices = [
            [row["choice1_1"], row["choice1_2"], row["choice1_3"], row["choice1_4"], row["choice1_5"]],
            [row["choice2_1"], row["choice2_2"], row["choice2_3"], row["choice2_4"], row["choice2_5"]],
            [row["choice3_1"], row["choice3_2"], row["choice3_3"], row["choice3_4"], row["choice3_5"]],
            [row["choice4_1"], row["choice4_2"], row["choice4_3"], row["choice4_4"], row["choice4_5"]],
        ]

        student = Student(
            row["student_id"],
            choices,
            int(row["grade"])
        )

        students_by_grade[int(row["grade"])].append(student)

# -------------------------
# Assign Lottery (After Loading)
# -------------------------
def assign_lottery_by_grade(students_by_grade, grade_order):
    """
    Assign fully random, unique lottery numbers.
    Seniors get the lowest number range,
    then juniors, then sophomores, etc.
    """

    current_min = 1

    for grade in grade_order:
        students = students_by_grade[grade]
        count = len(students)

        # Create unique number range for this grade
        grade_numbers = list(range(current_min, current_min + count))

        # Shuffle numbers to make them non-sequential
        random.shuffle(grade_numbers)

        # Shuffle students so pairing is random
        random.shuffle(students)

        # Assign shuffled numbers to shuffled students
        for student, lottery_number in zip(students, grade_numbers):
            student.lottery_number = lottery_number

        # Move range forward for next grade
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

    for choice_index in range(num_choices):
        for student in students_sorted:
            for class_id in student.choices[choice_index]:
                cls = class_dict[class_id]

                if len(cls.enrolled_students) < cls.capacity:
                    cls.enrolled_students.append(student.student_id)
                    student.assigned_classes[choice_index] = cls.class_id
                    break

# -------------------------
# Run Scheduling
# -------------------------
run_lottery_for_grade(students_by_grade[12])
run_lottery_for_grade(students_by_grade[11])
run_lottery_for_grade(students_by_grade[10])
run_lottery_for_grade(students_by_grade[9])

# -------------------------
# Output Results
# -------------------------
all_students = (
    students_by_grade[12] +
    students_by_grade[11] +
    students_by_grade[10] +
    students_by_grade[9]
)

print("\n---- Student Schedules ----")
for student in all_students:
    print(f"\nStudent {student.student_id} (Grade {student.grade}) - Lottery #{student.lottery_number}")
    for idx, class_id in enumerate(student.assigned_classes):
        if class_id:
            cls = class_dict[class_id]
            print(f" Choice {idx+1}: {cls.name} ({cls.time}, {cls.location})")
        else:
            print(f" Choice {idx+1}: No class assigned")

print("\n---- Final Class Enrollment ----")
for cls in CLASSES:
    print(f"{cls.name} ({cls.class_id}) - {len(cls.enrolled_students)}/{cls.capacity}")
    print(" Students:", cls.enrolled_students)

print_lottery_by_grade(students_by_grade)
check_for_duplicate_lottery_numbers(students_by_grade)