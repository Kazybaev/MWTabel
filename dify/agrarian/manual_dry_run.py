"""Fresh, read-only October 2026 manual-route dry-run; no batch or HTTP writes."""
import json
import subprocess
from collections import Counter
from pathlib import Path

from formatter import calculate, render_meta

BACKEND_CODE = r'''
import json
from datetime import date
from django.db import connection, transaction
from tabel_app.models import (StudentProfile, MonthlyStudentReportDispatch, MonthlyStudentReportAttempt,
    MonthlyStudentReportBatchItem, WahaParentReportBatchItem, WahaTestReportBatchItem)
from tabel_app.report import build_student_month_report, student_has_month_report_activity
month = date(2026, 10, 1)
result = []
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    students = StudentProfile.objects.filter(organization_type='college', college_branch='agrarian').select_related('user', 'group').order_by('pk')
    for student in students:
        report = build_student_month_report(student, month)
        dispatch = MonthlyStudentReportDispatch.objects.filter(student=student, month=month).first()
        attempts = list(MonthlyStudentReportAttempt.objects.filter(dispatch=dispatch).order_by('attempt_number').values('id', 'attempt_number', 'status', 'message_status')) if dispatch else []
        active = MonthlyStudentReportBatchItem.objects.filter(student=student, month=month, status__in=MonthlyStudentReportBatchItem.ACTIVE_STATUSES).exists()
        parent = list(WahaParentReportBatchItem.objects.filter(student=student, month=month, status__in=WahaParentReportBatchItem.ACTIVE_STATUSES + (WahaParentReportBatchItem.STATUS_ACCEPTED, WahaParentReportBatchItem.STATUS_UNKNOWN, WahaParentReportBatchItem.STATUS_FAILED)).values_list('status', flat=True).distinct())
        test = WahaTestReportBatchItem.objects.filter(student=student, month=month, status__in=(WahaTestReportBatchItem.STATUS_QUEUED, WahaTestReportBatchItem.STATUS_PROCESSING, WahaTestReportBatchItem.STATUS_ACCEPTED, WahaTestReportBatchItem.STATUS_UNKNOWN)).exists()
        result.append({'id':student.pk,'name':student.user.full_name,'group':student.group.course_name,
            'activity':student_has_month_report_activity(student,month),'report':report,
            'dispatch': {'id':dispatch.pk,'status':dispatch.status,'attempts':dispatch.attempts} if dispatch else None,
            'attempts':attempts,
            'all_dispatches':list(MonthlyStudentReportDispatch.objects.filter(student=student).order_by('month').values('month','status','attempts')),
            'all_attempts':list(MonthlyStudentReportAttempt.objects.filter(dispatch__student=student).order_by('dispatch__month','attempt_number').values('dispatch__month','attempt_number','status','message_status')),
            'active_item':active,'waha_parent':parent,'waha_test':test})
print('DRYRUN_JSON=' + json.dumps(result, ensure_ascii=False, default=str))
'''


def main():
    command = ['docker', 'exec', '-i', 'mwtabel-web-1', 'python', 'manage.py', 'shell',
               '-c', 'exec(__import__("sys").stdin.read())']
    run = subprocess.run(command, input=BACKEND_CODE, capture_output=True, text=True)
    if run.returncode:
        raise SystemExit('STOP: production read-only dry-run failed; output withheld')
    line = next((line for line in run.stdout.splitlines() if line.startswith('DRYRUN_JSON=')), None)
    if line is None:
        raise SystemExit('STOP: read-only dry-run returned no result')
    rows = json.loads(line.removeprefix('DRYRUN_JSON='))
    reasons = Counter()
    candidates = []
    phones = Counter()
    for row in rows:
        report = row['report']
        if not row['activity'] or report.get('status') == 'skipped':
            reasons[report.get('reason', 'no_month_activity')] += 1
            continue
        dispatch = row['dispatch']
        attempts = row['attempts']
        if dispatch and dispatch['status'] in ('accepted', 'delivered', 'succeeded'):
            reasons['already_accepted_or_delivered'] += 1
            continue
        if any(a['status'] in ('pending', 'accepted', 'delivered', 'succeeded') or a['message_status'] == 'unknown' for a in attempts):
            reasons['attempt_requires_review'] += 1
            continue
        if dispatch and dispatch['status'] == 'failed':
            reasons['failed_retry_requires_confirmation'] += 1
            continue
        if dispatch and dispatch['status'] == 'pending' and dispatch['attempts']:
            reasons['pending_review'] += 1
            continue
        if row['active_item']:
            reasons['active_dify_item'] += 1
            continue
        if row['waha_parent']:
            status = 'accepted' if 'accepted' in row['waha_parent'] else 'unknown' if 'unknown' in row['waha_parent'] else 'failed' if 'failed' in row['waha_parent'] else 'draft_or_active'
            reasons['waha_parent_' + status] += 1
            continue
        if row['waha_test']:
            reasons['waha_test_conflict'] += 1
            continue
        try:
            calculated = calculate(report)
            rendered = render_meta(calculated)
        except (ValueError, KeyError, TypeError) as exc:
            reasons['formatter_error:' + type(exc).__name__] += 1
            continue
        phone = str(report['student']['parent_phone'])
        digits = ''.join(c for c in phone if c.isdigit())
        if not 8 <= len(digits) <= 15:
            reasons['invalid_parent_phone'] += 1
            continue
        if len(rendered['parameters']) != 24:
            reasons['parameter_count_error'] += 1
            continue
        phones[digits] += 1
        candidates.append((row, calculated, rendered, digits))
    if len(rows) != sum(reasons.values()) + len(candidates):
        raise SystemExit('STOP: dry-run accounting mismatch')
    # Prefer an untouched student with an unshared recipient and recorded numeric grades.
    eligible = [c for c in candidates if c[0]['dispatch'] is None and sum(sum(s['grades'].values()) for s in c[1]['subjects']) > 0 and phones[c[3]] == 1]
    if not eligible:
        raise SystemExit('STOP: no clean single-recipient candidate')
    selected = max(eligible, key=lambda c: (sum(sum(subject['grades'].values()) for subject in c[1]['subjects']), -c[1]['lessons']['absent'], -c[0]['id']))
    row, calc, rendered, digits = selected
    result = {'total': len(rows), 'ready': len(candidates), 'excluded': sum(reasons.values()),
              'reasons': dict(sorted(reasons.items())), 'max_ready_preview_characters': max(r[2]['characters'] for r in candidates),
              'candidate': {'id': row['id'], 'name': row['name'], 'group': calc['group_name'],
                            'period': row['report']['period']['month'], 'recipient_masked': '***' + digits[-4:],
                            'october_dispatch': row['dispatch'], 'october_attempts': row['attempts'],
                            'all_dispatches': row['all_dispatches'], 'all_attempts': row['all_attempts'],
                            'parameters': rendered['parameters'], 'preview': rendered['preview']}}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
