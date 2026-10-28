import unittest
from pathlib import Path

import yaml


class AcademyFormatterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = yaml.safe_load(Path(__file__).with_name('monthly_send.yml').read_text())
        node = next(n for n in workflow['workflow']['graph']['nodes'] if n['id'] == '1782296762177')
        namespace = {}
        exec(compile(node['data']['code'], '<academy formatter>', 'exec'), namespace)
        cls.build_payload = staticmethod(namespace['build_payload'])
        cls.main = staticmethod(namespace['main'])

    def inputs(self):
        summary = {
            'total_lessons': 28,
            'marked_lessons_count': 13,
            'attendance_count': 13,
            'absence_count': 0,
            'unmarked_count': 15,
            'attendance_status_text': 'Белгиленген калуулар (Н): 0; белги коюлбаган сабактар: 15.',
        }
        return {
            'student_name': 'Шакеева Айдана',
            'recipient_name': '.',
            'recipient_phone': '+996700000001',
            'group_name': 'ИИ-30',
            'mentor_name': 'Mentor',
            'month': '2026-09',
            'average_grade': 3.2,
            'attendance_count': 13,
            'absence_count': 0,
            'attendance_rate': 46.4,
            'total_five': 0,
            'total_four': 3,
            'total_three': 10,
            'total_two': 0,
            'report': {'organization': 'academy', 'period': {'month': '2026-09'}, 'summary': summary},
        }

    def test_partial_attendance_is_explicit_in_template_parameter(self):
        result = self.build_payload(**self.inputs())
        self.assertEqual(result['absence_text'], self.inputs()['report']['summary']['attendance_status_text'])
        self.assertEqual(result['grade_line_3'], '—')
        self.assertEqual(result['grade_line_4'], '—')

    def test_mismatched_snapshot_is_rejected(self):
        inputs = self.inputs()
        inputs['report']['summary']['attendance_status_text'] = '1ай ичинде сабактан калган жок'
        with self.assertRaisesRegex(ValueError, 'Текст посещаемости'):
            self.build_payload(**inputs)

    def test_false_gate_stops_before_payload(self):
        with self.assertRaisesRegex(ValueError, 'ACADEMY_SEND_ENABLED=false'):
            self.main(send_enabled='false', **self.inputs())


if __name__ == '__main__':
    unittest.main()
