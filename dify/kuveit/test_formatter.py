"""Offline regression checks using sanitized copies of batch 11 payloads."""

import copy
import json
import os
import unittest

from formatter import THREE_SUBJECT_NOTE, main


class KuwaitFormatterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.getenv("KUVEIT_BATCH11_PAYLOADS")
        if not path:
            raise unittest.SkipTest("private batch 11 fixtures unavailable")
        with open(path, encoding="utf-8") as stream:
            cls.reports = [json.loads(line)["payload"] for line in stream]

    def sanitized(self, report):
        report = copy.deepcopy(report)
        report["student"]["full_name"] = "Тестовый студент"
        report["student"]["parent_name"] = "Тестовый родитель"
        report["student"]["parent_phone"] = "+996700000000"
        return report

    def values(self, report):
        result = main(self.sanitized(report))
        payload = json.loads(result["whatsapp_payload"])
        parameters = payload["template"]["components"][0]["parameters"]
        self.assertEqual(len(parameters), 24)
        for item in parameters:
            self.assertEqual(item["type"], "text")
            text = item["text"]
            self.assertNotIn("\r", text)
            self.assertNotIn("\n", text)
            self.assertNotIn("\t", text)
            self.assertNotIn("     ", text)
            self.assertEqual(text, " ".join(text.split()))
        return [item["text"] for item in parameters]

    def test_explanation_is_only_in_template_parameter(self):
        output = main(self.sanitized(self.reports[0]))
        callback = json.loads(output["backend_payload"])
        self.assertNotIn(THREE_SUBJECT_NOTE, output["absence_text"])
        self.assertNotIn(THREE_SUBJECT_NOTE, callback["absence_text"])
        self.assertIn(THREE_SUBJECT_NOTE, output["whatsapp_payload"])

    def test_three_real_reports_have_fourth_slot_marked_absent(self):
        self.assertEqual(len(self.reports), 3)
        for report in self.reports:
            with self.subTest(student_id=report["student"]["id"]):
                self.assertEqual(len(report["subjects"]), 3)
                values = self.values(report)
                self.assertEqual(len(values), 24)
                self.assertEqual(values[18:23], ["—"] * 5)
                self.assertEqual(values[3], report["subjects"][0]["name"])
                self.assertTrue(values[23].endswith(" " + THREE_SUBJECT_NOTE))
                self.assertEqual(values[23].count(THREE_SUBJECT_NOTE), 1)
                self.assertTrue(values[23].startswith(" ".join(main(self.sanitized(report))["absence_text"].split()) + " "))

    def test_four_subjects_keep_original_positions(self):
        report = copy.deepcopy(self.reports[0])
        fourth = copy.deepcopy(report["subjects"][0])
        fourth["name"] = "Тестовый четвёртый предмет"
        fourth["grade_counts"] = {"5": 2, "4": 1, "3": 0, "2": 0}
        report["subjects"].append(fourth)
        values = self.values(report)
        self.assertEqual(len(values), 24)
        self.assertEqual(values[18:23], ["Тестовый четвёртый предмет", "2", "1", "0", "0"])
        self.assertNotIn(THREE_SUBJECT_NOTE, values[23])

    def test_normalizes_all_final_meta_text_values(self):
        report = copy.deepcopy(self.reports[0])
        report["main_group"]["name"] = "  Тестовая\t\nгруппа     "
        report["subjects"][0]["name"] = "  Первый\r\n предмет     "
        values = self.values(report)
        self.assertEqual(values[0], "Тестовая группа")
        self.assertEqual(values[3], "Первый предмет")
        self.assertEqual(values[18:23], ["—"] * 5)
        self.assertTrue(values[23].endswith(" " + THREE_SUBJECT_NOTE))

    def test_invalid_subject_counts_are_rejected(self):
        for subjects in ([], self.reports[0]["subjects"] * 2, "wrong"):
            report = copy.deepcopy(self.reports[0])
            report["subjects"] = subjects
            with self.assertRaises(ValueError):
                self.values(report)

    def test_missing_grades_are_not_invented_as_zero(self):
        report = copy.deepcopy(self.reports[0])
        report["subjects"][0]["grade_counts"] = {}
        self.assertEqual(self.values(report)[4:8], ["—"] * 4)
        report["subjects"][0]["grade_counts"] = {"5": "bad"}
        with self.assertRaises(ValueError):
            self.values(report)


if __name__ == "__main__":
    unittest.main()
