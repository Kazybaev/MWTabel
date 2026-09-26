"""Conservative, insert-only import of supported college seed schemas."""
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from tabel_app.models import (
    User, MentorProfile, StudentProfile, CollegeGroup, Group, UserOrganizationAccess,
    Lesson, LessonRecord, ImportedGradeCell,
)


# Owner-reviewed exceptions are deliberately scoped by source, student and
# canonical phone.  The decisions file must also opt in explicitly, so neither
# the allowlist nor a copied flag can weaken the general collision check alone.
APPROVED_SHARED_PARENT_PHONES = frozenset({
    ('college-2026-second-course', 'Mukhammadaziz-40', '+996508054080'),
})


def normalize_phone(value, allow_bare_international=False):
    if not isinstance(value, str):
        raise ValueError('invalid_parent_phone')
    cleaned = ''.join(c for c in value if not (c.isspace() or unicodedata.category(c) == 'Cf' or c in '-()./–—'))
    if not cleaned:
        raise ValueError('missing_parent_phone')
    if re.fullmatch(r'[0-9]{9}', cleaned):
        cleaned = '+996' + cleaned
    elif re.fullmatch(r'7[0-9]{10}', cleaned):
        cleaned = '+' + cleaned
    elif allow_bare_international and re.fullmatch(r'[1-9][0-9]{6,14}', cleaned):
        cleaned = '+' + cleaned
    elif not re.fullmatch(r'\+[1-9][0-9]{6,14}', cleaned):
        raise ValueError('unrecognized_parent_phone')
    from phonenumber_field.phonenumber import PhoneNumber
    phone = PhoneNumber.from_string(cleaned)
    if not phone.is_valid():
        raise ValueError('invalid_parent_phone')
    return phone


def normalized_grade(value, nonempty_is_absence=False):
    value = '' if value is None else str(value).strip()
    if nonempty_is_absence:
        return value if value in {'2', '3', '4', '5'} else ('Н' if value else '')
    return {'н': 'Н', 'abs': 'Н', 'abs.': 'Н'}.get(value, value)


def unsupported_grade_reason(value):
    """Diagnostic categories only: never infer a replacement grade."""
    if value == '1':
        return 'grade_one_not_in_choices'
    if value.isdigit():
        return 'numeric_grade_not_in_choices'
    if value == 'н':
        return 'lowercase_absence_not_in_choices'
    if value in ('abs', 'abs.'):
        return 'english_absence_not_in_choices'
    if value and set(value) == {'-'}:
        return 'dash_placeholder'
    if re.fullmatch(r'[0-9нН]+(?:[,/]\s*[0-9нН]+)+', value):
        return 'multiple_results_in_one_cell'
    if 'point' in value or 'words' in value:
        return 'points_or_word_count_not_grade'
    return {
        'новенький': 'new_student_status',
        'Новенкий': 'new_student_status',
        'time off': 'time_off_status',
        'pass': 'pass_status',
        'late': 'late_status',
        'н/б': 'unconfirmed_absence_abbreviation',
        'bs': 'unknown_abbreviation',
    }.get(value, 'unrecognized_grade')


def validate_synthetic_date_approval(data, decisions, source_id):
    """Bind synthetic FULL dates to one owner-reviewed immutable proposal."""
    metadata = data.get('metadata', {})
    if metadata.get('synthetic_full_dates') is not True:
        return
    approval = decisions.get('synthetic_date_approvals', {}).get('FULL', {})
    required = {
        'approved': True,
        'synthetic_dates': True,
        'approved_by': 'data owner confirmation relayed by Alymbek Ibragimov',
    }
    if any(approval.get(key) != value for key, value in required.items()):
        raise CommandError('Synthetic FULL dates lack the exact reviewed approval.')
    proposal_path = approval.get('proposal_path')
    proposal_sha256 = approval.get('proposal_sha256')
    if not all(isinstance(value, str) and value for value in (
        proposal_path, proposal_sha256, approval.get('approved_at'),
        approval.get('algorithm_basis'),
    )):
        raise CommandError('Synthetic FULL approval is incomplete.')
    if metadata.get('proposal_v2_sha256') != proposal_sha256:
        raise CommandError('Corrected seed and reviewed FULL proposal hashes differ.')
    try:
        proposal_raw = Path(proposal_path).read_bytes()
        proposal = json.loads(proposal_raw)
    except (OSError, ValueError, TypeError):
        raise CommandError('Reviewed FULL proposal is unreadable.') from None
    if hashlib.sha256(proposal_raw).hexdigest() != proposal_sha256:
        raise CommandError('Reviewed FULL proposal SHA-256 mismatch.')
    if proposal.get('source_id') != source_id:
        raise CommandError('Reviewed FULL proposal source-id mismatch.')
    proposed = {
        row['class_name']: {
            item['source_column']: item['proposed_date']
            for item in row.get('columns', [])
        }
        for row in proposal.get('classes', [])
    }
    for class_row in (row for row in data['classes'] if row.get('subject_name') == 'FULL'):
        class_map = proposed.get(class_row['class_name'])
        if class_map is None:
            raise CommandError('Corrected seed contains an unreviewed FULL class.')
        source_rows = class_row['students'] + class_row['unmatched_gradebook_students']
        for student_row in source_rows:
            for record in student_row['records']:
                expected_iso = class_map.get(record.get('column'))
                try:
                    actual_iso = datetime.strptime(
                        record.get('header_value', record.get('date_or_header')),
                        '%d.%m.%Y',
                    ).date().isoformat()
                except (TypeError, ValueError):
                    actual_iso = None
                if record.get('synthetic') is not True or actual_iso != expected_iso:
                    raise CommandError('Corrected seed FULL date is outside the reviewed proposal.')


class Planner:
    def __init__(self, data, decisions, source_id="college-seed-2.0"):
        self.source_id = source_id
        self.source_schema = data['schema_version']
        self.cells = Counter()
        self.data, self.decisions = data, decisions
        self.pending = []
        self.cache = {}
        self.issues = []
        self.counts = defaultdict(Counter)
        self.phone_review = {
            'students_total': 0,
            'students_prepared': 0,
            'missing_parent_phone': 0,
            'unapproved_phone_conflicts': 0,
            'explicitly_approved_shared_phones': 0,
            'approved_shared_phone_details': [],
        }

    def issue(self, kind, source, reason, **details):
        self.issues.append(dict(kind=kind, source=source, reason=reason, **details))

    def ensure(self, model, key, values, source, password=None):
        token = (model, tuple(sorted((k, (v._meta.label, v.pk if v.pk is not None else id(v)) if hasattr(v, '_meta') else repr(v)) for k, v in key.items())))
        if token in self.cache:
            obj = self.cache[token]
            if obj and any(getattr(obj, k) != v for k, v in values.items()):
                self.issue('conflict', source, 'inconsistent_source_values', model=model.__name__)
                return None
            return obj
        # Unsaved FK dependencies cannot match any database row.
        rows = [] if any(hasattr(v, 'pk') and v.pk is None for v in key.values()) else list(model.objects.filter(**key)[:2])
        if len(rows) > 1:
            self.issue('conflict', source, 'ambiguous_database_key', model=model.__name__)
            return None
        if rows:
            obj = rows[0]
            fields = [k for k, v in values.items() if getattr(obj, k) != v]
            if fields:
                self.issue('conflict', source, 'existing_values_differ', model=model.__name__, fields=fields)
                return None
            self.counts[model.__name__]['existing'] += 1
        else:
            obj = model(**key, **values)
            if isinstance(obj, User):
                if not isinstance(password, str) or not password:
                    self.issue('blocked', source, 'missing_password')
                    return None
                # Hash only at application time; plaintext is never included in reports.
                obj.set_unusable_password()
                parts = obj.full_name.split(maxsplit=1)
                obj.first_name = parts[0] if parts else ''
                obj.last_name = parts[1] if len(parts) > 1 else ''
            try:
                obj.full_clean(exclude=[f.name for f in model._meta.fields if f.is_relation], validate_unique=False, validate_constraints=False)
            except ValidationError as exc:
                self.issue('blocked', source, 'invalid_fields', model=model.__name__, fields=sorted(exc.message_dict))
                return None
            self.pending.append((obj, password))
            self.counts[model.__name__]['new'] += 1
        self.cache[token] = obj
        return obj

    def user(self, row, role, source):
        login, name = row.get('login'), row.get('full_name')
        if not isinstance(login, str) or not login or not isinstance(name, str) or not name:
            self.issue('blocked', source, 'missing_identity')
            return None
        # A name is never an identity key, even an exact name match.
        if not User.objects.filter(username=login).exists() and User.objects.filter(full_name__iexact=name).exists():
            self.issue('conflict', source, 'name_exists_with_different_login')
            return None
        if User.objects.filter(username__iexact=login).exclude(username=login).exists():
            self.issue('conflict', source, 'case_insensitive_login_collision')
            return None
        return self.ensure(User, {'username': login}, {'full_name': name, 'role': role, 'is_active': True, 'is_staff': False, 'is_superuser': False}, source, row.get('password'))

    def audit_user_identity(self, row, role, source):
        """Check identity collisions without planning an orphan User."""
        login, name = row.get('login'), row.get('full_name')
        if not isinstance(login, str) or not login or not isinstance(name, str) or not name:
            self.issue('blocked', source, 'missing_identity')
            return False
        existing = User.objects.filter(username=login).first()
        if existing:
            expected = {
                'full_name': name, 'role': role, 'is_active': True,
                'is_staff': False, 'is_superuser': False,
            }
            fields = [field for field, value in expected.items() if getattr(existing, field) != value]
            if fields:
                self.issue('conflict', source, 'existing_values_differ', model='User', fields=fields)
                return False
        elif User.objects.filter(full_name__iexact=name).exists():
            self.issue('conflict', source, 'name_exists_with_different_login')
            return False
        if User.objects.filter(username__iexact=login).exclude(username=login).exists():
            self.issue('conflict', source, 'case_insensitive_login_collision')
            return False
        return True

    def access(self, user, source):
        self.ensure(UserOrganizationAccess, {'user': user, 'organization_type': 'college'}, {}, source)

    def build(self):
        mentors, groups, students = {}, {}, {}
        cohorts = {}
        for row in self.data['groups']:
            name = row['group_name']
            if not CollegeGroup.objects.filter(name=name).exists() and CollegeGroup.objects.filter(name__iexact=name).exists():
                self.issue('conflict', 'cohort:' + name, 'case_insensitive_cohort_collision')
                cohorts[name] = None
                continue
            cohorts[name] = self.ensure(CollegeGroup, {'name': name}, {}, 'cohort:' + name)
        for row in self.data.get('mentors', []):
            src = 'mentor:' + row['login']
            user = self.user(row, 'MENTOR', src)
            if user:
                profile = self.ensure(MentorProfile, {'user': user}, {'organization_type': 'college'}, src)
                if profile:
                    mentors[row['login']] = profile
                    self.access(user, src)
        for row in self.data['classes']:
            name = row['class_name']
            src = 'class:' + name
            decision = self.decisions.get('classes', {}).get(name, {})
            if self.source_schema == '1.0':
                mentor_login = decision.get('mentor_login')
                mentor_rows = list(MentorProfile.objects.filter(
                    user__username=mentor_login,
                    user__role='MENTOR',
                    user__is_active=True,
                ).filter(
                    Q(user__organization_accesses__organization_type='college')
                    | Q(user__organization_accesses__isnull=True, organization_type='college')
                ).distinct()[:2]) if isinstance(mentor_login, str) and mentor_login else []
                mentor = mentor_rows[0] if len(mentor_rows) == 1 else None
            else:
                mentor = mentors.get(row['mentor']['login'])
            days = 'MON_FRI'
            if not days:
                self.issue('blocked', src, 'missing_study_days')
            if mentor is None:
                reason = 'mentor_decision_unresolved' if self.source_schema == '1.0' else 'mentor_unresolved'
                self.issue('blocked', src, reason)
            if cohorts.get(row['group_name']) is None:
                self.issue('blocked', src, 'cohort_unresolved')
                continue
            course = decision.get('college_course', self.decisions.get('college_course'))
            if self.source_schema == '1.0' and course != '2':
                self.issue('blocked', src, 'second_course_decision_required')
                continue
            if not days or mentor is None:
                continue
            values = dict(mentor=mentor, study_days=days, archived_at=None)
            if 'college_course' in decision:
                values['college_course'] = decision['college_course']
            college_branch = 'agrarian' if decision.get('college_course') == '1' else 'kuwait'
            group = self.ensure(
                Group,
                {'course_name': name, 'organization_type': 'college', 'college_branch': college_branch},
                values,
                src,
            )
            if group:
                groups[name] = group
        roster = {}
        roster_name_counts = {g['group_name']: Counter(s['full_name'] for s in g['students']) for g in self.data['groups']}
        for cohort in self.data['groups']:
            class_names = [c['class_name'] for c in self.data['classes'] if c['group_name'] == cohort['group_name']]
            for row in cohort['students']:
                login = row['login']
                src = 'student:' + login
                self.phone_review['students_total'] += 1
                roster[login] = row
                decision = self.decisions.get('students', {}).get(login, {})
                existing = StudentProfile.objects.filter(user__username=login).first()
                parent_name = decision.get('parent_name', existing.parent_name if existing else '')
                if self.source_schema == '1.0':
                    candidates = [c['class_name'] for c in self.data['classes']
                                  if c['group_name'] == cohort['group_name'] and c.get('subject_name') == 'FULL']
                else:
                    candidates = [n for n in class_names if n == cohort['group_name'] + '-Кибер']
                primary = candidates[0] if len(candidates) == 1 else None
                reasons = []
                if not self.audit_user_identity(row, 'STUDENT', src):
                    reasons.append('user_identity_conflict')
                if primary not in class_names:
                    primary_reason = 'missing_or_ambiguous_full_class' if self.source_schema == '1.0' else 'missing_or_ambiguous_cyber_class'
                    reasons.append(primary_reason)
                    self.issue('conflict', src, primary_reason)
                if any(n not in groups for n in class_names):
                    reasons.append('classes_unresolved')
                course = decision.get('college_course', self.decisions.get('college_course'))
                if self.source_schema == '1.0' and course != '2':
                    reasons.append('second_course_decision_required')
                # Diagnose supplied fields even when unrelated dependencies are
                # missing, so the report does not hide later validation failures.
                try:
                    phone = normalize_phone(
                        decision.get('parent_phone', row['parent_phone']),
                        allow_bare_international=self.source_schema == '1.0',
                    )
                    phone_valid = True
                except ValueError as exc:
                    phone_error = str(exc)
                    reasons.append(phone_error)
                    if phone_error == 'missing_parent_phone':
                        self.phone_review['missing_parent_phone'] += 1
                    phone = ''
                    phone_valid = False
                probe = StudentProfile(parent_name=parent_name, parent_phone=phone, organization_type='college')
                excluded = ['user', 'group'] + ([] if parent_name else ['parent_name']) + ([] if phone_valid else ['parent_phone'])
                try:
                    probe.full_clean(exclude=excluded, validate_unique=False, validate_constraints=False)
                except ValidationError as exc:
                    reasons.extend('invalid_' + field for field in sorted(exc.message_dict))
                phone_conflict = bool(
                    phone and StudentProfile.objects.filter(parent_phone=phone)
                    .exclude(user__username=login).exists()
                )
                approved_shared_phone = (
                    phone_conflict
                    and decision.get('allow_existing_parent_phone') is True
                    and (self.source_id, login, str(phone)) in APPROVED_SHARED_PARENT_PHONES
                )
                if phone_conflict and not approved_shared_phone:
                    self.issue('conflict', src, 'parent_phone_exists_for_different_student')
                    reasons.append('parent_phone_exists_for_different_student')
                    self.phone_review['unapproved_phone_conflicts'] += 1
                elif approved_shared_phone:
                    self.phone_review['explicitly_approved_shared_phones'] += 1
                    self.phone_review['approved_shared_phone_details'].append({
                        'login': login,
                        'parent_phone': str(phone),
                    })
                if phone_valid and (not phone_conflict or approved_shared_phone):
                    self.phone_review['students_prepared'] += 1
                cohort_groups = [groups[name] for name in class_names if name in groups]
                if (
                    existing
                    and any(group.main_group_id is not None for group in cohort_groups)
                    and existing.college_groups.exclude(main_group=cohorts[cohort['group_name']]).exists()
                ):
                    self.issue('conflict', src, 'existing_memberships_different_cohort')
                    reasons.append('existing_memberships_different_cohort')
                if reasons:
                    self.issue('blocked', src, 'student_dependencies', reasons=reasons)
                    continue
                user = self.user(row, 'STUDENT', src)
                if not user:
                    continue
                values = dict(parent_name=parent_name, parent_phone=probe.parent_phone, group=groups[primary], organization_type='college', archived_at=None)
                if 'college_course' in decision:
                    values['college_course'] = decision['college_course']
                values['college_branch'] = 'agrarian' if decision.get('college_course') == '1' else 'kuwait'
                profile = self.ensure(StudentProfile, {'user': user}, values, src)
                if profile:
                    students[login] = profile
                    self.access(user, src)
                    for name in class_names:
                        self.ensure(StudentProfile.college_groups.through, {'studentprofile': profile, 'group': groups[name]}, {}, src)
        for row in self.data['classes']:
            name = row['class_name']
            for unmatched in row['unmatched_gradebook_students']:
                self.issue('unresolved', name, 'gradebook_without_roster_identity',
                           row=unmatched.get('source_row_gradebook', unmatched.get('source_row')))
                self.grade_cells(row, unmatched, None, groups.get(name), False)
            for student in row['students']:
                src = name + ':' + student['login']
                reference = roster.get(student['login'])
                identity_ok = reference is not None and all(reference[k] == student[k] for k in ('full_name', 'parent_phone', 'login', 'password'))
                identity_ok = identity_ok and roster_name_counts.get(row['group_name'], {}).get(student['full_name'], 0) == 1
                if not identity_ok:
                    self.issue('conflict', src, 'class_roster_identity_differs')
                if not student['exact_gradebook_match']:
                    self.issue('unresolved', src, 'roster_without_exact_gradebook_match')
                self.grade_cells(row, student, students.get(student['login']) if identity_ok and student['exact_gradebook_match'] else None, groups.get(name), identity_ok and student['exact_gradebook_match'])
        return self

    def grade_cells(self, row, student_row, student, group, identity_ok):
        records = student_row['records']
        parsed = []
        for record in records:
            header = record.get('header_value', record.get('date_or_header'))
            try:
                date = datetime.strptime(header, '%d.%m.%Y').date()
            except (ValueError, TypeError):
                date = None
            parsed.append((record, header, date, normalized_grade(
                record['value'], nonempty_is_absence=self.source_schema == '1.0')))
        dates = Counter(date for _, _, date, grade in parsed if date and grade in dict(LessonRecord.GRADE_CHOICES))
        for record, header, date, grade in parsed:
            self.cells['total'] += 1
            if date is None:
                self.cells['without_date'] += 1
            if not identity_ok:
                self.cells['without_identity'] += 1
            reason = 'unsupported_grade'
            lesson = None
            if grade in ('', '-', '--', '---'):
                reason = 'no_grade'
            elif not date:
                reason = 'missing_or_invalid_date'
            elif not identity_ok or student is None:
                reason = 'student_unresolved'
            elif group is None:
                reason = 'group_unresolved'
            elif grade in dict(LessonRecord.GRADE_CHOICES):
                reason = 'multiple_records_same_student_date' if dates[date] > 1 else 'lesson_record'
            src = row['class_name']
            source_row = student_row.get('source_row_gradebook', student_row.get('source_row'))
            if not isinstance(source_row, int) or source_row < 1 or not record.get('column'):
                self.issue('conflict', src, 'missing_cell_coordinates')
                self.cells['ambiguous'] += 1
                continue
            key = dict(source_id=self.source_id, source_class=src, source_row=source_row, source_column=record['column'])
            original = dict(original_value=record['value'], original_header=header)
            fingerprint = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            # Check immutable evidence before even planning a derived LessonRecord.
            existing = ImportedGradeCell.objects.filter(**key).first()
            token = (ImportedGradeCell, tuple(sorted((k, repr(v)) for k, v in key.items())))
            previous = existing or self.cache.get(token)
            if previous and previous.content_sha256 != fingerprint:
                self.issue('conflict', src, 'source_cell_changed', row=source_row, column=record['column'])
                self.cells['ambiguous'] += 1
                continue
            if reason == 'lesson_record':
                lesson = self.ensure(Lesson, {'group': group, 'lesson_date': date}, {}, src)
                result = self.ensure(LessonRecord, {'student': student, 'lesson': lesson, 'sequence': 1}, {'grade': grade}, src) if lesson else None
                if result is None:
                    reason = 'existing_lesson_or_grade_conflict'
            if reason == 'no_grade':
                self.cells['skipped'] += 1
            elif reason == 'lesson_record':
                self.cells['lesson_record'] += 1
            else:
                self.cells['imported_only'] += 1
            if reason in ('missing_or_invalid_date', 'student_unresolved', 'group_unresolved', 'multiple_records_same_student_date', 'existing_lesson_or_grade_conflict'):
                self.cells['unresolved'] += 1
            # Archive all cells, including normalized/skipped ones, to preserve originals.
            self.ensure(ImportedGradeCell, key, dict(**original, content_sha256=fingerprint, student=student, group=group, lesson=lesson, reason=reason), src)

    def apply(self):
        # bulk_create deliberately bypasses model save hooks, all save/M2M signals,
        # API views and their report delivery code. FK IDs resolve in dependency order.
        for obj, password in self.pending:
            for field in obj._meta.fields:
                if field.is_relation and field.is_cached(obj):
                    related = getattr(obj, field.name)
                    setattr(obj, field.attname, related.pk if related is not None else None)
            if isinstance(obj, User):
                obj.set_password(password)
            type(obj).objects.bulk_create([obj])


class Command(BaseCommand):
    help = 'Insert-only college seed import; defaults to a read-only dry-run.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('source')
        parser.add_argument('--source-id', required=True, help='Stable source identifier; reuse for corrected files, never use a content hash.')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')
        parser.add_argument('--decisions', help='Reviewed JSON: source_id, college_course; students/login/parent_name,parent_phone,college_course,allow_existing_parent_phone; classes/name/college_course,mentor_login. Schedule and primary subject follow fixed import rules.')
        parser.add_argument('--report', required=True)
        parser.add_argument('--allow-partial', action='store_true', help='Explicitly accept unresolved rows listed in this run report.')
        parser.add_argument('--expect-database', required=True)

    def handle(self, *args, **options):
        if os.getenv('AUTO_MONTHLY_REPORTS', '').lower() not in ('false', '0', 'off'):
            raise CommandError('Run with AUTO_MONTHLY_REPORTS=false before Django starts.')
        if connection.settings_dict['NAME'] != options['expect_database']:
            raise CommandError('Database does not match --expect-database.')
        source = Path(options['source'])
        report_path = Path(options['report'])
        if report_path.resolve() == source.resolve() or (options['decisions'] and report_path.resolve() == Path(options['decisions']).resolve()):
            raise CommandError('Report must not overwrite input.')
        try:
            raw = source.read_bytes()
            data = json.loads(raw)
            decisions = json.loads(Path(options['decisions']).read_text()) if options['decisions'] else {}
            if data['schema_version'] not in ('1.0', '2.0'):
                raise ValueError
            if decisions.get('source_id', options['source_id']) != options['source_id']:
                raise ValueError
            sections = [('classes', 'class_name')]
            if data['schema_version'] == '2.0':
                sections.append(('mentors', 'login'))
            for section, key in sections:
                keys = [r[key] for r in data[section]]
                if len(keys) != len(set(keys)):
                    raise ValueError
            logins = [s['login'] for g in data['groups'] for s in g['students']]
            if data['schema_version'] == '2.0':
                logins += [m['login'] for m in data['mentors']]
            if len(logins) != len(set(logins)):
                raise ValueError
            mentor_rows = {m['login']: m for m in data.get('mentors', [])}
            cohort_names = [g['group_name'] for g in data['groups']]
            if len(cohort_names) != len(set(cohort_names)):
                raise ValueError
            for row in data['classes']:
                if row['group_name'] not in cohort_names:
                    raise ValueError
                if data['schema_version'] == '2.0':
                    mentor = mentor_rows[row['mentor']['login']]
                    if any(mentor[k] != row['mentor'][k] for k in ('login', 'full_name', 'password')):
                        raise ValueError
                elif 'subject_name' not in row:
                    raise ValueError
                class_logins = [s['login'] for s in row['students']]
                if len(class_logins) != len(set(class_logins)):
                    raise ValueError
            if data['schema_version'] == '1.0':
                for cohort_name in cohort_names:
                    if sum(c.get('subject_name') == 'FULL' and c['group_name'] == cohort_name for c in data['classes']) != 1:
                        raise ValueError
        except (ValueError, KeyError, TypeError, OSError):
            raise CommandError('Invalid input structure, duplicate source identities or unreadable file.') from None
        validate_synthetic_date_approval(data, decisions, options['source_id'])
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    if options['apply']:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        models = [User, MentorProfile, CollegeGroup, Group, StudentProfile, UserOrganizationAccess, Lesson, LessonRecord, ImportedGradeCell, StudentProfile.college_groups.through]
                        tables = ', '.join(connection.ops.quote_name(m._meta.db_table) for m in models)
                        cursor.execute('LOCK TABLE ' + tables + ' IN SHARE ROW EXCLUSIVE MODE')
                    else:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    cursor.execute("SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema = 'public'")
                    if cursor.fetchall():
                        raise CommandError('Database has triggers; review them before importing.')
            planner = Planner(data, decisions, options['source_id']).build()
            result = dict(mode='apply' if options['apply'] else 'dry-run', applied=False, database=options['expect_database'], source_schema=data['schema_version'], source_sha256=hashlib.sha256(raw).hexdigest(), counts=planner.counts, cells=planner.cells, phone_review=planner.phone_review, source_id=options['source_id'], issues_summary=Counter(i['kind'] for i in planner.issues), issue_reasons=Counter(i.get('detail_reason', i['reason']) for i in planner.issues), dependency_reasons=Counter(reason for i in planner.issues for reason in i.get('reasons', [])), issues=planner.issues)
            # Report creation is exclusive and private; never replaces previous evidence.
            with report_path.open('x', encoding='utf-8') as report:
                os.chmod(report_path, 0o600)
                json.dump(result, report, ensure_ascii=False, indent=2)
            self.stdout.write(json.dumps({k: v for k, v in result.items() if k != 'issues'}, ensure_ascii=False, indent=2))
            if options['apply']:
                if any(i['kind'] == 'conflict' for i in planner.issues):
                    raise CommandError('Conflicts: application refused; source and existing values must be reviewed.')
                if any(i['kind'] not in ('skipped_record', 'unresolved') for i in planner.issues) and not options['allow_partial']:
                    raise CommandError('Unresolved rows: review report; application refused without --allow-partial.')
                planner.apply()
        if options['apply']:
            self.stdout.write('Import committed. Report contains the pre-commit plan; preserve this success message.')
