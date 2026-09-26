import json
import os
import tempfile
import copy
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, transaction
from django.db.models.signals import post_save, m2m_changed
from django.test import TransactionTestCase

from .management.commands.import_college_seed import Planner, validate_synthetic_date_approval
from .models import User, MentorProfile, StudentProfile, LessonRecord


class CollegeImportTests(TransactionTestCase):
    def setUp(self):
        self.mentor = dict(login='mentor-seed', full_name='Mentor Seed', password='private-password')
        self.student = dict(login='student-seed', full_name='Student Seed', password='private-password', parent_phone='+996555123456')
        self.data = dict(schema_version='2.0', mentors=[self.mentor], groups=[dict(group_name='cohort', students=[self.student])], classes=[dict(class_name='cohort-Кибер', group_name='cohort', mentor=self.mentor, unmatched_gradebook_students=[], students=[dict(self.student, exact_gradebook_match=True, source_row_gradebook=3, records=[dict(column='C', header_value='03.08.2025', value='5')])])])
        self.decisions = dict(classes={'cohort-Кибер': dict(study_days='MON_FRI')}, students={'student-seed': dict(parent_name='Parent', primary_class='cohort-Кибер')})

    def second_course_data(self, values=None):
        data = copy.deepcopy(self.data)
        data['schema_version'] = '1.0'
        data.pop('mentors')
        row = data['classes'][0]
        row.pop('mentor')
        row['subject_name'] = 'FULL'
        row['class_name'] = 'cohort-FULL'
        for student in row['students'] + row['unmatched_gradebook_students']:
            if 'source_row_gradebook' in student:
                student['source_row'] = student.pop('source_row_gradebook')
            for record in student['records']:
                record['date_or_header'] = record.pop('header_value')
        if values is not None:
            row['students'][0]['records'] = [
                dict(column=str(index + 1), date_or_header=f'{index + 1:02d}.08.2025', value=value)
                for index, value in enumerate(values)
            ]
        decisions = {
            'source_id': 'college-2026-second-course',
            'college_course': '2',
            'classes': {'cohort-FULL': {'college_course': '2', 'mentor_login': self.mentor['login']}},
            'students': {'student-seed': {'college_course': '2'}},
        }
        return data, decisions

    def create_existing_college_mentor(self):
        user = User.objects.create_user(
            username=self.mentor['login'], full_name=self.mentor['full_name'],
            role='MENTOR', password='existing-password',
        )
        return MentorProfile.objects.create(user=user, organization_type='college')

    def approved_shared_phone_data(self, login='Mukhammadaziz-40', phone='+996508054080'):
        data, decisions = self.second_course_data()
        student = data['groups'][0]['students'][0]
        student.update(
            login=login,
            full_name='Каримов Мухаммадазиз' if login == 'Mukhammadaziz-40' else 'Other Reviewed Student',
            parent_phone=phone,
        )
        data['classes'][0]['students'][0].update({
            key: student[key] for key in ('login', 'full_name', 'password', 'parent_phone')
        })
        decisions['students'] = {
            login: {
                'college_course': '2',
                'parent_phone': phone,
                'allow_existing_parent_phone': True,
            },
        }
        return data, decisions

    def create_phone_collision_profiles(self, mentor, phone, count=1):
        from .models import CollegeGroup, Group
        group = Group.objects.create(
            course_name='existing-phone-group-' + str(StudentProfile.objects.count()),
            mentor=mentor,
            study_days='MON_FRI',
            organization_type='college',
            main_group=CollegeGroup.objects.create(
                name='existing-phone-cohort-' + str(StudentProfile.objects.count()),
            ),
        )
        profiles = []
        for index in range(count):
            user = User.objects.create_user(
                username=f'existing-phone-student-{StudentProfile.objects.count()}-{index}',
                full_name=f'Existing Phone Student {StudentProfile.objects.count()} {index}',
                role='STUDENT',
            )
            profiles.append(StudentProfile.objects.create(
                user=user,
                parent_name=f'Existing Parent {index}',
                parent_phone=phone,
                group=group,
                organization_type='college',
            ))
        return profiles

    def test_apply_idempotency_passwords_and_no_signals(self):
        events = []
        def receiver(**kwargs):
            events.append(kwargs)
        post_save.connect(receiver)
        m2m_changed.connect(receiver)
        try:
            with transaction.atomic():
                plan = Planner(self.data, self.decisions).build()
                self.assertEqual(plan.issues, [])
                plan.apply()
            self.assertEqual(events, [])
        finally:
            post_save.disconnect(receiver)
            m2m_changed.disconnect(receiver)
        user = User.objects.get(username='student-seed')
        self.assertTrue(user.check_password('private-password'))
        old_hash = user.password
        self.student['password'] = 'changed-source-password'
        self.data['classes'][0]['students'][0]['password'] = 'changed-source-password'
        repeated = Planner(self.data, self.decisions).build()
        self.assertEqual(repeated.pending, [])
        self.assertEqual(repeated.issues, [])
        user.refresh_from_db()
        self.assertEqual(user.password, old_hash)
        self.assertEqual(StudentProfile.objects.get().college_groups.count(), 1)
        self.assertEqual(LessonRecord.objects.get().lesson.lesson_date.year, 2025)

    def test_dry_run_does_not_execute_mutations_or_log_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            source, report = Path(directory)/'seed.json', Path(directory)/'report.json'
            source.write_text(json.dumps(self.data))
            def guard(execute, sql, params, many, context):
                self.assertFalse(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')))
                return execute(sql, params, many, context)
            with patch.dict(os.environ, AUTO_MONTHLY_REPORTS='false'), connection.execute_wrapper(guard):
                call_command('import_college_seed', str(source), dry_run=True, report=str(report), expect_database=connection.settings_dict['NAME'], source_id='test-source')
            self.assertNotIn('private-password', report.read_text())
            self.assertEqual(User.objects.count(), 0)

    def test_conflicting_user_is_not_updated(self):
        User.objects.create_user(username='mentor-seed', full_name='Other Person', role='MENTOR', password='original')
        plan = Planner(self.data, self.decisions).build()
        self.assertTrue(any(i['reason'] == 'existing_values_differ' for i in plan.issues))
        self.assertTrue(User.objects.get().check_password('original'))

    def test_unsupported_and_unmatched_are_not_imported(self):
        row = self.data['classes'][0]
        row['students'][0]['records'][0]['value'] = '1'
        row['unmatched_gradebook_students'] = [dict(source_row_gradebook=9, records=[dict(column='D', header_value='', value='abs')])]
        plan = Planner(self.data, self.decisions).build()
        self.assertEqual({i['kind'] for i in plan.issues}, {'unresolved'})
        self.assertEqual(plan.counts['ImportedGradeCell']['new'], 2)
        self.assertFalse(any(isinstance(obj, LessonRecord) for obj, _ in plan.pending))

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                Planner(self.data, self.decisions).build().apply()
                raise RuntimeError('abort')
        self.assertEqual(User.objects.count(), 0)

    def test_same_name_different_login_requires_review(self):
        User.objects.create_user(username='other', full_name='Student Seed')
        plan = Planner(self.data, self.decisions).build()
        self.assertTrue(any(i['reason'] == 'name_exists_with_different_login' for i in plan.issues))

    def test_grade_whitespace_matches_gradebook_api(self):
        self.data['classes'][0]['students'][0]['records'][0]['value'] = ' 5 '
        plan = Planner(self.data, self.decisions).build()
        self.assertEqual(plan.issues, [])
        self.assertEqual([obj.grade for obj, _ in plan.pending if isinstance(obj, LessonRecord)], ['5'])

    def test_empty_cell_is_reported_and_preserves_existing_grade(self):
        Planner(self.data, self.decisions).build().apply()
        self.data['classes'][0]['students'][0]['records'][0]['value'] = '  '
        plan = Planner(self.data, self.decisions).build()
        self.assertEqual(plan.pending, [])
        self.assertEqual([i['reason'] for i in plan.issues], ['source_cell_changed'])
        plan.apply()
        self.assertEqual(LessonRecord.objects.get().grade, '5')

    def test_detailed_unsupported_reasons(self):
        from .management.commands.import_college_seed import unsupported_grade_reason
        for value, reason in [('1', 'grade_one_not_in_choices'), ('н', 'lowercase_absence_not_in_choices'), ('abs', 'english_absence_not_in_choices'), ('5,5', 'multiple_results_in_one_cell'), ('0 point', 'points_or_word_count_not_grade')]:
            with self.subTest(value=value):
                self.assertEqual(unsupported_grade_reason(value), reason)

    def test_group_api_requires_schedule_before_perform_create(self):
        from .serializers import GroupWriteSerializer, StudentProfileSerializer
        from rest_framework.exceptions import ValidationError
        from rest_framework.fields import empty
        schedule = GroupWriteSerializer().fields['study_days']
        for value in [empty, '', None]:
            with self.subTest(value=str(value)), self.assertRaises(ValidationError):
                schedule.run_validation(value)
        self.assertTrue(StudentProfileSerializer().fields['group'].required)
        self.assertFalse(StudentProfileSerializer().fields['parent_name'].required)
        self.assertTrue(StudentProfileSerializer().fields['parent_name'].allow_blank)

    def test_phone_validation_is_not_hidden_by_missing_dependencies(self):
        self.student['parent_phone'] = 'invalid'
        plan = Planner(self.data, {}).build()
        issue = next(i for i in plan.issues if i['reason'] == 'student_dependencies')
        self.assertIn('unrecognized_parent_phone', issue['reasons'])


    def test_normalization_and_raw_json_types(self):
        from .models import ImportedGradeCell
        row = self.data['classes'][0]['students'][0]
        row['records'] = [dict(column=str(i), header_value=f'{i+1:02d}.08.2025', value=value)
                          for i, value in enumerate([' н ', 'abs', 'abs. ', '-', '--', '---', None, 2, 1, {'a': 5}, '----'])]
        plan = Planner(self.data, {}).build()
        self.assertEqual(plan.cells['lesson_record'], 4)
        self.assertEqual(plan.cells['skipped'], 4)
        self.assertEqual(plan.cells['imported_only'], 3)
        plan.apply()
        self.assertEqual(ImportedGradeCell.objects.get(source_column='7').original_value, 2)
        self.assertIsNone(ImportedGradeCell.objects.get(source_column='6').original_value)
        self.assertEqual(ImportedGradeCell.objects.get(source_column='0').original_value, ' н ')
        self.assertEqual(Planner(self.data, {}).build().pending, [])
        row['records'][7]['value'] = '2'
        repeated = Planner(self.data, {}).build()
        self.assertTrue(any(i['reason'] == 'source_cell_changed' for i in repeated.issues))
        self.assertEqual(repeated.pending, [])

    def test_missing_date_and_identity_remain_null(self):
        from .models import ImportedGradeCell, Lesson
        row = self.data['classes'][0]
        row['students'][0]['records'][0]['header_value'] = 'copybook '
        row['unmatched_gradebook_students'] = [dict(source_row_gradebook=9, records=[dict(column='D', header_value='01.08.2025', value='5')])]
        plan = Planner(self.data, {}).build()
        plan.apply()
        self.assertEqual(Lesson.objects.count(), 0)
        self.assertEqual(ImportedGradeCell.objects.filter(lesson=None).count(), 2)
        self.assertIsNone(ImportedGradeCell.objects.get(source_row=9).student)
        self.assertEqual(plan.cells['unresolved'], 2)

    def test_phone_rules(self):
        from .management.commands.import_college_seed import normalize_phone
        for value, expected in [('555 123-456\u202c', '+996555123456'), ('7 (999) 123-45-67', '+79991234567'), ('+44 20 7946 0958', '+442079460958')]:
            self.assertEqual(str(normalize_phone(value)), expected)
        self.assertEqual(
            str(normalize_phone('442079460958', allow_bare_international=True)),
            '+442079460958',
        )
        with self.assertRaises(ValueError):
            normalize_phone('442079460958')
        for value in ['', '  ', '12345', '89991234567', 'call555123456', '000000000']:
            with self.assertRaises(ValueError):
                normalize_phone(value)

    def test_second_course_nonempty_values_become_absence(self):
        values = ['2', '3', '4', '5', '', None, ' ', 'н', 'Н', 'abw', 'Abw', 'Abs',
                  'm', 'конспект', 'конпспект', 'Sleeping', '3 sleeping', 'Ff', 'k']
        data, decisions = self.second_course_data(values)
        self.create_existing_college_mentor()
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        self.assertEqual(plan.issues, [])
        self.assertEqual(plan.cells['lesson_record'], 16)
        self.assertEqual(plan.cells['skipped'], 3)
        self.assertEqual(Counter(
            obj.grade for obj, _ in plan.pending if isinstance(obj, LessonRecord)
        ), {'2': 1, '3': 1, '4': 1, '5': 1, 'Н': 12})
        plan.apply()
        student = StudentProfile.objects.get(user__username='student-seed')
        self.assertEqual(student.college_course, '2')
        self.assertEqual(student.group.college_course, '2')
        self.assertEqual(student.group.course_name, 'cohort-FULL')

    def test_second_course_membership_survives_missing_gradebook_row(self):
        data, decisions = self.second_course_data()
        student_row = data['classes'][0]['students'][0]
        student_row['exact_gradebook_match'] = False
        student_row['records'] = []
        self.create_existing_college_mentor()
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        self.assertEqual(plan.counts['StudentProfile']['new'], 1)
        self.assertEqual(plan.counts['StudentProfile_college_groups']['new'], 1)
        self.assertFalse(any(isinstance(obj, LessonRecord) for obj, _ in plan.pending))
        plan.apply()
        student = StudentProfile.objects.get(user__username='student-seed')
        self.assertEqual(student.college_groups.count(), 1)
        self.assertEqual(LessonRecord.objects.count(), 0)
        from .models import ImportedGradeCell
        self.assertEqual(ImportedGradeCell.objects.count(), 0)

    def test_second_course_requires_exact_existing_mentor_decision(self):
        data, decisions = self.second_course_data()
        decisions['classes']['cohort-FULL']['mentor_login'] = ''
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        self.assertTrue(any(i['reason'] == 'mentor_decision_unresolved' for i in plan.issues))
        self.assertEqual(plan.counts['Group']['new'], 0)
        self.assertEqual(plan.counts['StudentProfile']['new'], 0)

    def test_second_course_missing_phone_is_explicit_blocker(self):
        data, decisions = self.second_course_data()
        data['groups'][0]['students'][0]['parent_phone'] = ''
        data['classes'][0]['students'][0]['parent_phone'] = ''
        self.create_existing_college_mentor()
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        issue = next(i for i in plan.issues if i['reason'] == 'student_dependencies')
        self.assertIn('missing_parent_phone', issue['reasons'])

    def test_second_course_phone_collision_is_not_guessed(self):
        data, decisions = self.second_course_data()
        mentor = self.create_existing_college_mentor()
        other_user = User.objects.create_user(username='other-student', full_name='Other Student')
        from .models import CollegeGroup, Group
        other_group = Group.objects.create(
            course_name='other', mentor=mentor, study_days='MON_FRI',
            organization_type='college', main_group=CollegeGroup.objects.create(name='other'),
        )
        StudentProfile.objects.create(
            user=other_user, parent_phone=self.student['parent_phone'], group=other_group,
            organization_type='college',
        )
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        self.assertTrue(any(i['reason'] == 'parent_phone_exists_for_different_student' for i in plan.issues))
        self.assertEqual(plan.counts['StudentProfile']['new'], 0)

    def test_approved_shared_phone_is_limited_to_exact_reviewed_tuple(self):
        mentor = self.create_existing_college_mentor()
        self.create_phone_collision_profiles(mentor, '+996508054080')
        self.create_phone_collision_profiles(mentor, '+996555000999')

        data, decisions = self.approved_shared_phone_data()
        without_flag = copy.deepcopy(decisions)
        without_flag['students']['Mukhammadaziz-40'].pop('allow_existing_parent_phone')
        blocked = Planner(data, without_flag, source_id='college-2026-second-course').build()
        self.assertTrue(any(
            i['reason'] == 'parent_phone_exists_for_different_student'
            for i in blocked.issues
        ))
        self.assertEqual(blocked.counts['StudentProfile']['new'], 0)

        approved = Planner(data, decisions, source_id='college-2026-second-course').build()
        self.assertFalse(any(
            i['reason'] == 'parent_phone_exists_for_different_student'
            for i in approved.issues
        ))
        self.assertEqual(approved.counts['StudentProfile']['new'], 1)
        self.assertEqual(approved.phone_review, {
            'students_total': 1,
            'students_prepared': 1,
            'missing_parent_phone': 0,
            'unapproved_phone_conflicts': 0,
            'explicitly_approved_shared_phones': 1,
            'approved_shared_phone_details': [{
                'login': 'Mukhammadaziz-40',
                'parent_phone': '+996508054080',
            }],
        })

        for login, phone, source_id in (
            ('different-login', '+996508054080', 'college-2026-second-course'),
            ('Mukhammadaziz-40', '+996555000999', 'college-2026-second-course'),
            ('Mukhammadaziz-40', '+996508054080', 'different-source'),
        ):
            with self.subTest(login=login, phone=phone, source_id=source_id):
                variant_data, variant_decisions = self.approved_shared_phone_data(login, phone)
                plan = Planner(variant_data, variant_decisions, source_id=source_id).build()
                self.assertTrue(any(
                    i['reason'] == 'parent_phone_exists_for_different_student'
                    for i in plan.issues
                ))
                self.assertEqual(plan.counts['StudentProfile']['new'], 0)
                self.assertEqual(plan.phone_review['unapproved_phone_conflicts'], 1)
                self.assertEqual(plan.phone_review['explicitly_approved_shared_phones'], 0)

    def test_approved_shared_phone_does_not_update_existing_profiles(self):
        mentor = self.create_existing_college_mentor()
        existing = self.create_phone_collision_profiles(
            mentor, '+996508054080', count=6,
        )
        before = list(StudentProfile.objects.filter(pk__in=[p.pk for p in existing])
                      .order_by('pk').values())
        data, decisions = self.approved_shared_phone_data()
        plan = Planner(data, decisions, source_id=decisions['source_id']).build()
        self.assertFalse(any(i['kind'] == 'conflict' for i in plan.issues))
        plan.apply()
        after = list(StudentProfile.objects.filter(pk__in=[p.pk for p in existing])
                     .order_by('pk').values())
        self.assertEqual(after, before)
        self.assertEqual(
            str(StudentProfile.objects.get(user__username='Mukhammadaziz-40').parent_phone),
            '+996508054080',
        )

    def test_approved_shared_phone_repeated_dry_run_is_idempotent(self):
        mentor = self.create_existing_college_mentor()
        self.create_phone_collision_profiles(mentor, '+996508054080', count=6)
        data, decisions = self.approved_shared_phone_data()
        before = list(StudentProfile.objects.order_by('pk').values())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'seed.json'
            decision_path = Path(directory) / 'decisions.json'
            source.write_text(json.dumps(data))
            decision_path.write_text(json.dumps(decisions))
            reports = []
            with patch.dict(os.environ, AUTO_MONTHLY_REPORTS='false'):
                for index in range(2):
                    report = Path(directory) / f'dry-run-{index}.json'
                    call_command(
                        'import_college_seed', str(source), dry_run=True,
                        source_id='college-2026-second-course',
                        decisions=str(decision_path), report=str(report),
                        expect_database=connection.settings_dict['NAME'],
                    )
                    reports.append(json.loads(report.read_text()))
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(reports[0]['phone_review']['students_prepared'], 1)
        self.assertEqual(reports[0]['phone_review']['explicitly_approved_shared_phones'], 1)
        self.assertEqual(list(StudentProfile.objects.order_by('pk').values()), before)

    def test_synthetic_full_dates_require_the_exact_reviewed_proposal(self):
        data, decisions = self.second_course_data()
        data['metadata'] = {
            'synthetic_full_dates': True,
            'proposal_v2_sha256': '',
        }
        data['classes'][0]['students'][0]['records'][0].update(synthetic=True)
        with tempfile.TemporaryDirectory() as directory:
            proposal_path = Path(directory) / 'proposal.json'
            proposal = {
                'source_id': decisions['source_id'],
                'classes': [{
                    'class_name': 'cohort-FULL',
                    'columns': [{
                        'source_column': 'C',
                        'proposed_date': '2025-08-03',
                    }],
                }],
            }
            raw = json.dumps(proposal, ensure_ascii=False).encode()
            proposal_path.write_bytes(raw)
            import hashlib
            digest = hashlib.sha256(raw).hexdigest()
            data['metadata']['proposal_v2_sha256'] = digest
            decisions['synthetic_date_approvals'] = {'FULL': {
                'proposal_path': str(proposal_path),
                'proposal_sha256': digest,
                'approved': True,
                'approved_at': '2026-09-10T08:55:59Z',
                'approved_by': 'data owner confirmation relayed by Alymbek Ibragimov',
                'synthetic_dates': True,
                'algorithm_basis': 'D starts at an approved date and source columns advance deterministically.',
            }}
            validate_synthetic_date_approval(data, decisions, decisions['source_id'])
            proposal_path.write_text('{}')
            from django.core.management.base import CommandError
            with self.assertRaisesMessage(CommandError, 'SHA-256 mismatch'):
                validate_synthetic_date_approval(data, decisions, decisions['source_id'])

    def test_synthetic_full_dates_reject_unapproved_or_changed_coordinates(self):
        data, decisions = self.second_course_data()
        data['metadata'] = {'synthetic_full_dates': True, 'proposal_v2_sha256': 'pending'}
        data['classes'][0]['students'][0]['records'][0].update(synthetic=True)
        with tempfile.TemporaryDirectory() as directory:
            proposal_path = Path(directory) / 'proposal.json'
            proposal = {
                'source_id': decisions['source_id'],
                'classes': [{
                    'class_name': 'cohort-FULL',
                    'columns': [{'source_column': 'C', 'proposed_date': '2025-08-04'}],
                }],
            }
            raw = json.dumps(proposal).encode()
            proposal_path.write_bytes(raw)
            import hashlib
            digest = hashlib.sha256(raw).hexdigest()
            data['metadata']['proposal_v2_sha256'] = digest
            decisions['synthetic_date_approvals'] = {'FULL': {
                'proposal_path': str(proposal_path),
                'proposal_sha256': digest,
                'approved': False,
                'approved_at': '2026-09-10T08:55:59Z',
                'approved_by': 'data owner confirmation relayed by Alymbek Ibragimov',
                'synthetic_dates': True,
                'algorithm_basis': 'reviewed deterministic source-column map',
            }}
            from django.core.management.base import CommandError
            with self.assertRaisesMessage(CommandError, 'exact reviewed approval'):
                validate_synthetic_date_approval(data, decisions, decisions['source_id'])
            decisions['synthetic_date_approvals']['FULL']['approved'] = True
            with self.assertRaisesMessage(CommandError, 'outside the reviewed proposal'):
                validate_synthetic_date_approval(data, decisions, decisions['source_id'])

    def test_schedule_primary_and_existing_name_conflicts(self):
        from .models import Group
        plan = Planner(self.data, self.decisions).build()
        plan.apply()
        student = StudentProfile.objects.get()
        self.assertEqual(Planner(self.data, {}).build().pending, [])
        self.assertEqual(student.parent_name, 'Parent')
        group = Group.objects.get()
        Group.objects.filter(pk=group.pk).update(study_days='TUE_THU_SAT')
        self.assertTrue(any('study_days' in i.get('fields', []) for i in Planner(self.data, {}).build().issues))
        Group.objects.filter(pk=group.pk).update(study_days='MON_FRI')
        other = Group.objects.create(course_name='other', mentor=group.mentor, study_days='MON_FRI', organization_type='college')
        student.group = other
        student.save()
        self.assertTrue(any('group' in i.get('fields', []) for i in Planner(self.data, {}).build().issues))
        student.refresh_from_db()
        self.assertEqual(student.group, other)

    def test_duplicate_date_never_creates_grade(self):
        row = self.data['classes'][0]['students'][0]
        row['records'].append(dict(column='D', header_value='03.08.2025', value='4'))
        plan = Planner(self.data, {}).build()
        self.assertEqual(plan.cells['unresolved'], 2)
        self.assertFalse(any(isinstance(obj, LessonRecord) for obj, _ in plan.pending))

    def test_same_full_name_different_logins_do_not_share_profile_cache(self):
        import copy
        other = dict(self.student, login='second-student')
        self.data['groups'][0]['students'].append(other)
        row = copy.deepcopy(self.data['classes'][0]['students'][0])
        row.update(other)
        row['source_row_gradebook'] = 4
        self.data['classes'][0]['students'].append(row)
        plan = Planner(self.data, {}).build()
        self.assertEqual(plan.counts['StudentProfile']['new'], 2)
        self.assertFalse(any(i['reason'] == 'inconsistent_source_values' for i in plan.issues))

    def test_parent_name_api_omission_preserves_existing_name(self):
        from .serializers import StudentProfileSerializer
        Planner(self.data, self.decisions).build().apply()
        student = StudentProfile.objects.get()
        from django.test import RequestFactory
        request = RequestFactory().patch('/', HTTP_X_ORGANIZATION_TYPE='college')
        request.user = student.user
        serializer = StudentProfileSerializer(student, data={}, partial=True, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        student.refresh_from_db()
        self.assertEqual(student.parent_name, 'Parent')
        serializer = StudentProfileSerializer(student, data={'parent_name': ''}, partial=True, context={'request': request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        student.refresh_from_db()
        self.assertEqual(student.parent_name, '')

    def test_imported_cells_admin_is_read_only_and_role_restricted(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from .admin import ImportedGradeCellAdmin
        from .models import ImportedGradeCell
        admin = ImportedGradeCellAdmin(ImportedGradeCell, AdminSite())
        request = RequestFactory().get('/')
        for role, expected in [('ADMIN', True), ('MENTOR', False), ('STUDENT', False)]:
            request.user = User(role=role, is_staff=True, is_active=True)
            self.assertEqual(admin.has_view_permission(request), expected)
            self.assertEqual(admin.has_module_permission(request), expected)
            self.assertFalse(admin.has_add_permission(request))
            self.assertFalse(admin.has_change_permission(request))
            self.assertFalse(admin.has_delete_permission(request))

    def test_college_branch_and_primary_subject_are_distinct(self):
        self.decisions['classes']['cohort-Кибер']['college_course'] = '1'
        self.decisions['students']['student-seed']['college_course'] = '1'
        Planner(self.data, self.decisions).build().apply()
        student = StudentProfile.objects.get()
        self.assertEqual(student.group.course_name, 'cohort-Кибер')
        self.assertEqual(student.college_branch, 'agrarian')
        self.assertEqual(student.group.college_branch, 'agrarian')
        self.assertIsNone(student.group.main_group)
        self.assertEqual(list(student.college_groups.all()), [student.group])

    def test_existing_membership_in_other_branch_does_not_reclassify_import(self):
        from .models import CollegeGroup, Group
        Planner(self.data, self.decisions).build().apply()
        student = StudentProfile.objects.get()
        extra = Group.objects.create(course_name='other', mentor=student.group.mentor,
            study_days='MON_FRI', organization_type='college', college_branch='agrarian',
            main_group=CollegeGroup.objects.create(name='other', college_branch='agrarian'))
        student.college_groups.add(extra)
        plan = Planner(self.data, self.decisions).build()
        self.assertFalse(any(i['reason'] == 'existing_memberships_different_cohort' for i in plan.issues))
        self.assertEqual(plan.pending, [])
        student.refresh_from_db()
        self.assertEqual(student.college_branch, 'kuwait')
        self.assertEqual(student.group.college_branch, 'kuwait')
        self.assertEqual(
            set(student.college_groups.values_list('college_branch', flat=True)),
            {'agrarian', 'kuwait'},
        )
