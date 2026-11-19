"""Mock-only check of the deployed backend's agrarian Dify route; no DB or network."""
import json
import os
from unittest.mock import patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tabel_project.settings')
import django
django.setup()

from tabel_app.report import ReportConfigurationError, build_dify_inputs, run_dify_workflow
from tabel_app.report_routing import workflow_route_for_context


class MockResponse:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self):
        return b'{"workflow_run_id":"mock-only"}'


def main():
    report = {
        'organization': 'college', 'college_branch': 'agrarian', 'workflow_route': 'agrarian',
        'student': {'full_name': 'Test Student', 'parent_name': 'Test Parent', 'parent_phone': '+996700000000'},
        'main_group': {'name': 'Test Group'}, 'group': {'course_name': 'Test Subject'},
        'mentor': {'full_name': 'Test Mentor'}, 'period': {'month': '2026-10'},
        'summary': {'average_grade': 4, 'attendance_count': 1, 'absence_count': 0,
                    'total_five': 0, 'total_four': 1, 'total_three': 0, 'total_two': 0,
                    'attendance_rate': 100},
    }
    assert workflow_route_for_context('college', 'agrarian') == 'agrarian'
    inputs = build_dify_inputs(report)
    assert inputs['report'] == report and inputs['report']['workflow_route'] == 'agrarian'
    assert inputs['group_name'] == 'Test Group' and inputs['month'] == '2026-10'
    assert inputs['recipient_phone'] == '+996700000000'
    assert len(inputs) == 15
    env = {'DIFY_API_KEY': 'shared-must-not-be-used', 'DIFY_ACADEMY_API_KEY': 'academy-must-not-be-used',
           'DIFY_KUWAIT_API_KEY': 'kuwait-must-not-be-used', 'DIFY_AGRARIAN_API_KEY': 'agrarian-synthetic',
           'BACKEND_REPORT_CALLBACK_TOKEN': 'synthetic-callback-token-long-enough-32',
           'DIFY_API_URL': 'https://mock.invalid/v1/workflows/run'}
    with patch.dict(os.environ, env), patch('tabel_app.report.request.urlopen', return_value=MockResponse()) as mocked:
        result = run_dify_workflow(inputs, 'report:test:2026-10', 'agrarian')
        request = mocked.call_args.args[0]
        body = json.loads(request.data)
        assert result['workflow_run_id'] == 'mock-only'
        assert request.get_header('Authorization') == 'Bearer agrarian-synthetic'
        assert body['inputs'] == inputs and body['user'] == 'report:test:2026-10'
        assert body['response_mode'] == 'blocking'
        assert mocked.call_count == 1
    env['DIFY_AGRARIAN_API_KEY'] = ''
    with patch.dict(os.environ, env), patch('tabel_app.report.request.urlopen') as mocked:
        try:
            run_dify_workflow(inputs, 'report:test:2026-10', 'agrarian')
        except ReportConfigurationError:
            pass
        else:
            raise AssertionError('agrarian route fell back to another key')
        mocked.assert_not_called()
    print('agrarian route, 15 inputs, own key, no fallback: PASS; HTTP calls are mocked')


if __name__ == '__main__':
    main()
