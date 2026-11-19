from .report import is_absence_grade


def calculate_average_grade(grades):
    """Return the gradebook average, counting absences as zero grades."""
    total_points = 0
    marked_count = 0

    for value in grades:
        grade = (value or "").strip()
        if grade.isdigit():
            total_points += int(grade)
            marked_count += 1
        elif is_absence_grade(grade):
            marked_count += 1

    if not marked_count:
        return None
    return round(total_points / marked_count, 1)
