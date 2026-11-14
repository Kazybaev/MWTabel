import copy
import json
import pathlib
import unittest

from formatter import BODY_LIMIT, SUBJECT_LIMIT, calculate, main, normalize, render_meta

EXAMPLES = json.loads((pathlib.Path(__file__).parents[2] / "docs" / "agrarian_report_examples.json").read_text())["examples"]


class AgrarianFormatterTests(unittest.TestCase):
    def test_real_examples_and_separate_missing_data(self):
        for report in EXAMPLES.values():
            result = main(report)
            self.assertEqual(len(result["parameters"]), 5)
            self.assertLessEqual(result["characters"], BODY_LIMIT)
            for param in result["parameters"]:
                self.assertEqual(param, normalize(param))
                self.assertNotIn("\n", param)
                self.assertNotIn("\t", param)
        missing = calculate(EXAMPLES["missing_grades"])
        self.assertEqual(missing["lessons"]["unmarked"], 70)
        self.assertIn("белгиленбеген сабактар 70", render_meta(missing)["parameters"][4])

    def test_numeric_grades_unbounded_and_mixed_lesson(self):
        report = copy.deepcopy(EXAMPLES["full"])
        row = next(row for row in report["lessons"] if row["grade"] in ("2", "3", "4", "5"))
        for grade in ("5", "4", "3", "2", "Н"):
            extra = dict(row, record_id="extra-" + grade, grade=grade)
            report["lessons"].append(extra)
        result = calculate(report)
        subject = next(subject for subject in result["subjects"] if subject["group_id"] == row["group_id"])
        detail = next(item for item in subject["lesson_details"] if item["lesson_id"] == row["lesson_id"])
        self.assertEqual(detail["category"], "mixed")
        self.assertEqual(len(detail["grades"]), 6)
        self.assertEqual(sum(subject["grades"].values()), sum(grade in ("2", "3", "4", "5") for item in subject["lesson_details"] for grade in item["grades"]))

    def test_same_date_distinct_lessons_and_unmarked(self):
        report = copy.deepcopy(EXAMPLES["full"])
        row = next(row for row in report["lessons"] if row["grade"])
        extra = dict(row, lesson_id="another-lesson", record_id=None, grade="", status="unmarked")
        report["lessons"].append(extra)
        result = calculate(report)
        self.assertEqual(result["lessons"]["unmarked"], calculate(EXAMPLES["full"])["lessons"]["unmarked"] + 1)

    def test_no_grades_is_not_zero_grades(self):
        report = copy.deepcopy(EXAMPLES["full"])
        for row in report["lessons"]:
            row["grade"] = ""
        result = main(report)
        self.assertIn("баа коюлган эмес", result["parameters"][3])
        self.assertNotIn("5: 0", result["parameters"][3])

    def test_capacity_rejects_without_truncation(self):
        calculation = calculate(EXAMPLES["full"])
        calculation["subjects"] = calculation["subjects"] * (SUBJECT_LIMIT // len(calculation["subjects"]) + 1)
        with self.assertRaisesRegex(ValueError, "Subject capacity"):
            render_meta(calculation)
        calculation = calculate(EXAMPLES["full"])
        calculation["student_name"] = "А" * BODY_LIMIT
        with self.assertRaisesRegex(ValueError, "BODY capacity"):
            render_meta(calculation)

    def test_final_parameters_normalized(self):
        calculation = calculate(EXAMPLES["full"])
        calculation["student_name"] = " А\n\t  Б "
        calculation["subjects"][0]["name"] = "Предмет\n  бир"
        params = render_meta(calculation)["parameters"]
        self.assertEqual(params[0], "А Б")
        self.assertIn("Предмет бир", params[3])


if __name__ == "__main__":
    unittest.main()
