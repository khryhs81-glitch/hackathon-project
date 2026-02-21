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
    def __init__(self, student_id, lottery_number, choices):
        self.student_id = student_id
        self.lottery_number = lottery_number
        self.choices = choices  # List of 4 choices, each a list of 5 class_ids
        self.assigned_classes = [None] * len(choices)  # One class per choice

# -------------------------
# Sample Data
# -------------------------
classes = [
    Class("C101", "Math", "Mon 9-10", "Room A", 2),
    Class("C102", "Science", "Mon 10-11", "Room B", 1),
    Class("C103", "History", "Tue 9-10", "Room C", 2),
    Class("C104", "Art", "Wed 9-10", "Room D", 1),
    Class("C105", "Music", "Thu 10-11", "Room E", 1),
    Class("C106", "PE", "Fri 9-10", "Gym", 2),
]

students = [
    Student("S001", 10, [
        ["C101", "C102", "C103", "C104", "C105"],
        ["C106", "C103", "C101", "C104", "C102"],
        ["C104", "C101", "C102", "C105", "C106"],
        ["C103", "C105", "C101", "C106", "C104"]
    ]),
    Student("S002", 5, [
        ["C102", "C101", "C103", "C104", "C105"],
        ["C101", "C102", "C104", "C106", "C103"],
        ["C105", "C104", "C103", "C101", "C102"],
        ["C106", "C105", "C101", "C103", "C104"]
    ]),
    Student("S003", 15, [
        ["C103", "C101", "C102", "C104", "C105"],
        ["C104", "C106", "C105", "C101", "C102"],
        ["C101", "C103", "C102", "C105", "C106"],
        ["C102", "C101", "C103", "C104", "C106"]
    ])
]

# -------------------------
# Build class dictionary
# -------------------------
class_dict = {c.class_id: c for c in classes}

# -------------------------
# Sort students by lottery number
# -------------------------
students_sorted = sorted(students, key=lambda s: s.lottery_number)

# -------------------------
# Round-robin assignment per choice
# -------------------------
num_choices = len(students_sorted[0].choices)

for choice_index in range(num_choices):
    # Go student by student for this choice
    for student in students_sorted:
        # Skip if student already has a class assigned for this choice
        if student.assigned_classes[choice_index] is not None:
            continue
        # Try to assign one class from their ranked preferences for this choice
        for class_id in student.choices[choice_index]:
            cls = class_dict[class_id]
            if len(cls.enrolled_students) < cls.capacity:
                cls.enrolled_students.append(student.student_id)
                student.assigned_classes[choice_index] = cls.class_id
                break  # Assigned one class for this choice, move to next student

# -------------------------
# Output student schedules
# -------------------------
print("---- Student Schedules ----")
for student in students:
    print(f"\nStudent {student.student_id}:")
    for idx, class_id in enumerate(student.assigned_classes):
        if class_id:
            cls = class_dict[class_id]
            print(f" Choice {idx+1}: {cls.name} ({cls.time}, {cls.location})")
        else:
            print(f" Choice {idx+1}: No class assigned")

# -------------------------
# Output class enrollments
# -------------------------
print("\n---- Class Enrollments ----")
for cls in classes:
    print(f"{cls.name} ({cls.class_id}) - Enrolled: {cls.enrolled_students}")