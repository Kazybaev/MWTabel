"""Read-only audit of already built October payloads; prints aggregates only."""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from formatter import BODY, SUBJECT_LIMIT, calculate, render_meta


def audit(path):
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    reports = json.loads(text[text.index('[{'):])
    assert len(reports) == 104
    assert sum(report.get('skipped') is True for report in reports) == 1
    totals = Counter()
    max_length = 0
    failures = []
    for position, report in enumerate(reports, 1):
        if report.get('skipped'):
            continue
        try:
            assert report['period']['month'] == '2026-10'
            calculation = calculate(report)
            rendered = render_meta(calculation)
            params = rendered['parameters']
            assert len(params) == 24 and len(report['groups']) <= SUBJECT_LIMIT
            assert params[:2] == [calculation['group_name'], calculation['student_name']]
            assert params[2] == '2026-жылдын октябрь'
            by_lesson = defaultdict(list)
            by_group = defaultdict(Counter)
            for row in report['lessons']:
                key = (row['group_id'], row['lesson_id'])
                by_lesson[key].append(row['grade'])
                if row['grade'] in '2345' and row['grade']:
                    by_group[row['group_id']][row['grade']] += 1
            categories = Counter()
            for grades in by_lesson.values():
                numeric = any(grade in ('2', '3', '4', '5') for grade in grades)
                absent = 'Н' in grades
                categories['mixed' if numeric and absent else 'graded' if numeric else 'absent' if absent else 'unmarked'] += 1
            assert sum(calculation['lessons'].values()) == len(by_lesson)
            assert all(calculation['lessons'][kind] == categories[kind] for kind in ('graded', 'absent', 'mixed', 'unmarked'))
            assert sum(len(s['lesson_details']) for s in calculation['subjects']) == len(by_lesson)
            for i, subject in enumerate(calculation['subjects']):
                start = 3 + 5 * i
                assert params[start] == subject['name']
                assert params[start + 1:start + 5] == [str(by_group[subject['group_id']][grade]) for grade in ('5', '4', '3', '2')]
                assert subject['grades'] == by_group[subject['group_id']]
            for i in range(len(calculation['subjects']), 4):
                assert params[3 + 5 * i:8 + 5 * i] == ['—'] * 5
            assert all(param == ' '.join(param.split()) and param for param in params)
            assert all(not re.search(r'[\r\n\t]|  ', param) for param in params)
            assert f"Н гана белгиленген сабактар: {categories['absent']}" in params[23]
            assert f"аралаш белгилер (баа жана Н, пропуск катары эсептелбейт): {categories['mixed']}" in params[23]
            assert f"белгиленбеген сабактар (пропуск катары эсептелбейт): {categories['unmarked']}" in params[23]
            expected = BODY
            for i, param in enumerate(params, 1):
                expected = expected.replace('{{' + str(i) + '}}', param)
            assert rendered['preview'] == expected and not re.search(r'{{\d+}}', expected)
            assert rendered['characters'] == len(expected)
            max_length = max(max_length, len(expected))
            totals.update(categories)
        except Exception as exc:
            failures.append({'position': position, 'error': str(exc) or type(exc).__name__})
    print(json.dumps({'total': len(reports), 'ready': len(reports) - 1, 'skipped': 1,
                      'checked': len(reports) - 1 - len(failures), 'lesson_categories': totals,
                      'max_body_characters': max_length, 'local_body_limit': 1024,
                      'failures': failures}, ensure_ascii=False))
    assert not failures


if __name__ == '__main__':
    audit(sys.argv[1])
