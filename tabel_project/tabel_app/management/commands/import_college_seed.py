"""Conservative, insert-only import of college seed schema 2.0."""
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
from tabel_app.models import (
    User, MentorProfile, StudentProfile, Group, UserOrganizationAccess,
    Lesson, LessonRecord, ImportedGradeCell,
)


def normalize_phone(value):
    if not isinstance(value, str):
        raise ValueError('invalid_parent_phone')
    cleaned = ''.join(c for c in value if not (c.isspace() or unicodedata.category(c) == 'Cf' or c in '-()./–—'))
    if re.fullmatch(r'[0-9]{9}', cleaned):
        cleaned = '+996' + cleaned
    elif re.fullmatch(r'7[0-9]{10}', cleaned):
        cleaned = '+' + cleaned
    elif not re.fullmatch(r'\+[1-9][0-9]{6,14}', cleaned):
        raise ValueError('unrecognized_parent_phone')
    from phonenumber_field.phonenumber import PhoneNumber
    phone = PhoneNumber.from_string(cleaned)
    if not phone.is_valid():
        raise ValueError('invalid_parent_phone')
    return phone


def normalized_grade(value):
    value = '' if value is None else str(value).strip()
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


class Planner:
    def __init__(self, data, decisions, source_id="college-seed-2.0"):
        self.source_id = source_id
        self.cells = Counter()
        self.data, self.decisions = data, decisions
        self.pending = []
        self.cache = {}
        self.issues = []
        self.counts = defaultdict(Counter)

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

    def access(self, user, source):
        self.ensure(UserOrganizationAccess, {'user': user, 'organization_type': 'college'}, {}, source)

    def build(self):
        mentors, groups, students = {}, {}, {}
        for row in self.data['mentors']:
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
            mentor = mentors.get(row['mentor']['login'])
            decision = self.decisions.get('classes', {}).get(name, {})
            days = 'MON_FRI'
            if not days:
                self.issue('blocked', src, 'missing_study_days')
            if mentor is None:
                self.issue('blocked', src, 'mentor_unresolved')
            if not days or mentor is None:
                continue
            values = dict(mentor=mentor, study_days=days, archived_at=None)
            if 'college_course' in decision:
                values['college_course'] = decision['college_course']
            group = self.ensure(Group, {'course_name': name, 'organization_type': 'college'}, values, src)
            if group:
                groups[name] = group
        roster = {}
        roster_name_counts = {g['group_name']: Counter(s['full_name'] for s in g['students']) for g in self.data['groups']}
        for cohort in self.data['groups']:
            class_names = [c['class_name'] for c in self.data['classes'] if c['group_name'] == cohort['group_name']]
            for row in cohort['students']:
                login = row['login']
                src = 'student:' + login
                roster[login] = row
                decision = self.decisions.get('students', {}).get(login, {})
                existing = StudentProfile.objects.filter(user__username=login).first()
                parent_name = decision.get('parent_name', existing.parent_name if existing else '')
                candidates = [n for n in class_names if n == cohort['group_name'] + '-Кибер']
                primary = candidates[0] if len(candidates) == 1 else None
                reasons = []
                if primary not in class_names:
                    reasons.append('missing_or_ambiguous_cyber_class')
                    self.issue('conflict', src, 'missing_or_ambiguous_cyber_class')
                if any(n not in groups for n in class_names):
                    reasons.append('classes_unresolved')
                # Diagnose supplied fields even when unrelated dependencies are
                # missing, so the report does not hide later validation failures.
                try:
                    phone = normalize_phone(decision.get('parent_phone', row['parent_phone']))
                except ValueError as exc:
                    reasons.append(str(exc))
                    phone = ''
                probe = StudentProfile(parent_name=parent_name, parent_phone=phone, organization_type='college')
                excluded = ['user', 'group'] + ([] if parent_name else ['parent_name'])
                try:
                    probe.full_clean(exclude=excluded, validate_unique=False, validate_constraints=False)
                except ValidationError as exc:
                    reasons.extend('invalid_' + field for field in sorted(exc.message_dict))
                if reasons:
                    self.issue('blocked', src, 'student_dependencies', reasons=reasons)
                    continue
                user = self.user(row, 'STUDENT', src)
                if not user:
                    continue
                values = dict(parent_name=parent_name, parent_phone=probe.parent_phone, group=groups[primary], organization_type='college', archived_at=None)
                if 'college_course' in decision:
                    values['college_course'] = decision['college_course']
                profile = self.ensure(StudentProfile, {'user': user}, values, src)
                if profile:
                    students[login] = profile
                    self.access(user, src)
                    for name in class_names:
                        self.ensure(StudentProfile.college_groups.through, {'studentprofile': profile, 'group': groups[name]}, {}, src)
        for row in self.data['classes']:
            name = row['class_name']
            for unmatched in row['unmatched_gradebook_students']:
                self.issue('unresolved', name, 'gradebook_without_roster_identity', row=unmatched['source_row_gradebook'])
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
            try:
                date = datetime.strptime(record['header_value'], '%d.%m.%Y').date()
            except (ValueError, TypeError):
                date = None
            parsed.append((record, date, normalized_grade(record['value'])))
        dates = Counter(date for _, date, grade in parsed if date and grade in dict(LessonRecord.GRADE_CHOICES))
        for record, date, grade in parsed:
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
            source_row = student_row.get('source_row_gradebook')
            if not isinstance(source_row, int) or source_row < 1 or not record.get('column'):
                self.issue('conflict', src, 'missing_cell_coordinates')
                self.cells['ambiguous'] += 1
                continue
            key = dict(source_id=self.source_id, source_class=src, source_row=source_row, source_column=record['column'])
            original = dict(original_value=record['value'], original_header=record['header_value'])
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
                result = self.ensure(LessonRecord, {'student': student, 'lesson': lesson}, {'grade': grade}, src) if lesson else None
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
    help = 'Insert-only college schema 2.0 import; defaults to a read-only dry-run.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('source')
        parser.add_argument('--source-id', required=True, help='Stable source identifier; reuse for corrected files, never use a content hash.')
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--dry-run', action='store_true')
        mode.add_argument('--apply', action='store_true')
        parser.add_argument('--decisions', help='Reviewed JSON: classes/name/study_days; students/login/parent_name,primary_class; optional parent_phone,college_course.')
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
            if data['schema_version'] != '2.0':
                raise ValueError
            for section, key in [('mentors', 'login'), ('classes', 'class_name')]:
                keys = [r[key] for r in data[section]]
                if len(keys) != len(set(keys)):
                    raise ValueError
            logins = [s['login'] for g in data['groups'] for s in g['students']] + [m['login'] for m in data['mentors']]
            if len(logins) != len(set(logins)):
                raise ValueError
            mentor_rows = {m['login']: m for m in data['mentors']}
            cohort_names = [g['group_name'] for g in data['groups']]
            if len(cohort_names) != len(set(cohort_names)):
                raise ValueError
            for row in data['classes']:
                if row['group_name'] not in cohort_names:
                    raise ValueError
                mentor = mentor_rows[row['mentor']['login']]
                if any(mentor[k] != row['mentor'][k] for k in ('login', 'full_name', 'password')):
                    raise ValueError
                class_logins = [s['login'] for s in row['students']]
                if len(class_logins) != len(set(class_logins)):
                    raise ValueError
        except (ValueError, KeyError, TypeError, OSError):
            raise CommandError('Invalid input structure, duplicate source identities or unreadable file.') from None
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    if options['apply']:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        models = [User, MentorProfile, Group, StudentProfile, UserOrganizationAccess, Lesson, LessonRecord, ImportedGradeCell, StudentProfile.college_groups.through]
                        tables = ', '.join(connection.ops.quote_name(m._meta.db_table) for m in models)
                        cursor.execute('LOCK TABLE ' + tables + ' IN SHARE ROW EXCLUSIVE MODE')
                    else:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    cursor.execute("SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema = 'public'")
                    if cursor.fetchall():
                        raise CommandError('Database has triggers; review them before importing.')
            planner = Planner(data, decisions, options['source_id']).build()
            result = dict(mode='apply' if options['apply'] else 'dry-run', applied=False, database=options['expect_database'], source_sha256=hashlib.sha256(raw).hexdigest(), counts=planner.counts, cells=planner.cells, source_id=options['source_id'], issues_summary=Counter(i['kind'] for i in planner.issues), issue_reasons=Counter(i.get('detail_reason', i['reason']) for i in planner.issues), dependency_reasons=Counter(reason for i in planner.issues for reason in i.get('reasons', [])), issues=planner.issues)
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
