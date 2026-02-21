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
    def __init__(self, student_id, lottery_number, choices, grade):
        self.student_id = student_id
        self.lottery_number = lottery_number
        self.choices = choices
        self.assigned_classes = [None] * len(choices)
        self.grade = grade

import csv
import random

# -------------------------
# Configuration
# -------------------------
NUM_STUDENTS = 200
GRADES = [9, 10, 11, 12]
# -------------------------
# Create Class Objects Properly
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
# Generate students.csv
# -------------------------
with open("students.csv", "w", newline="") as f:
    writer = csv.writer(f)

    header = [
        "student_id","grade","lottery_number",
        "choice1_1","choice1_2","choice1_3","choice1_4","choice1_5",
        "choice2_1","choice2_2","choice2_3","choice2_4","choice2_5",
        "choice3_1","choice3_2","choice3_3","choice3_4","choice3_5",
        "choice4_1","choice4_2","choice4_3","choice4_4","choice4_5",
    ]
    writer.writerow(header)

    for i in range(1, NUM_STUDENTS + 1):
        grade = random.choice(GRADES)
        lottery_number = random.randint(1, 1000)

        row = [f"S{i:03}", grade, lottery_number]

        # Generate 4 choices
        for _ in range(4):
            ranked_classes = random.sample(CLASS_IDS, 5)  # No duplicates in choice
            row.extend(ranked_classes)

        writer.writerow(row)

print("students.csv generated successfully.")

import csv

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
            int(row["lottery_number"]),
            choices,
            int(row["grade"])
        )

        students_by_grade[int(row["grade"])].append(student)



# -------------------------
# Function to Run Lottery For One Grade
# -------------------------
def run_lottery_for_grade(students):
    students_sorted = sorted(students, key=lambda s: s.lottery_number)
    num_choices = len(students_sorted[0].choices)

    for choice_index in range(num_choices):
        for student in students_sorted:
            if student.assigned_classes[choice_index] is not None:
                continue

            for class_id in student.choices[choice_index]:
                cls = class_dict[class_id]

                if len(cls.enrolled_students) < cls.capacity:
                    cls.enrolled_students.append(student.student_id)
                    student.assigned_classes[choice_index] = cls.class_id
                    break




# -------------------------
# Run Scheduling Grade by Grade
# -------------------------
run_lottery_for_grade(students_by_grade[12])
run_lottery_for_grade(students_by_grade[11])
run_lottery_for_grade(students_by_grade[10])
run_lottery_for_grade(students_by_grade[9])


# -------------------------
# Output Final Results
# -------------------------
all_students = students_by_grade[12] + students_by_grade[11] + students_by_grade[10]+ students_by_grade[9]

print("---- Student Schedules ----")
for student in all_students:
    print(f"\nStudent {student.student_id} (Grade {student.grade}):")
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