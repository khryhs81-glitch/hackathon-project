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


# -------------------------
# Create Classes ONCE
# -------------------------
classes = [
    Class("C101", "Math", "Mon 9-10", "Room A", 4),
    Class("C102", "Science", "Mon 10-11", "Room B", 3),
    Class("C103", "History", "Tue 9-10", "Room C", 4),
    Class("C104", "Art", "Wed 9-10", "Room D", 2),
    Class("C105", "Music", "Thu 10-11", "Room E", 2),
    Class("C106", "PE", "Fri 9-10", "Gym", 4),
]

class_dict = {c.class_id: c for c in classes}


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
# Create Students By Grade
# -------------------------

grade9 = [
    Student("G9_S1", 5, [
        ["C101","C102","C103","C104","C105"],
        ["C106","C101","C102","C103","C104"],
        ["C103","C104","C105","C101","C102"],
        ["C102","C101","C106","C103","C104"]
    ], 9),
]

grade10 = [
    Student("G10_S1", 2, [
        ["C101","C102","C103","C104","C105"],
        ["C106","C101","C102","C103","C104"],
        ["C103","C104","C105","C101","C102"],
        ["C102","C101","C106","C103","C104"]
    ], 10),
]

grade11 = [
    Student("G11_S1", 1, [
        ["C102","C101","C103","C104","C105"],
        ["C106","C102","C101","C103","C104"],
        ["C105","C103","C104","C101","C102"],
        ["C101","C102","C106","C103","C104"]
    ], 11),
]

grade12 = [
    Student("G12_S1", 3, [
        ["C101","C102","C103","C104","C105"],
        ["C106","C101","C102","C103","C104"],
        ["C103","C104","C105","C101","C102"],
        ["C102","C101","C106","C103","C104"]
    ], 12),
]

# -------------------------
# Run Scheduling Grade by Grade
# -------------------------
run_lottery_for_grade(grade9)
run_lottery_for_grade(grade10)
run_lottery_for_grade(grade11)
run_lottery_for_grade(grade12)


# -------------------------
# Output Final Results
# -------------------------
all_students = grade9 + grade10 + grade11 + grade12

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
for cls in classes:
    print(f"{cls.name} ({cls.class_id}) - {len(cls.enrolled_students)}/{cls.capacity}")
    print(" Students:", cls.enrolled_students)