import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, transaction
from django.db.models.signals import post_save, m2m_changed
from django.test import TransactionTestCase

from .management.commands.import_college_seed import Planner
from .models import User, StudentProfile, LessonRecord


class CollegeImportTests(TransactionTestCase):
    def setUp(self):
        self.mentor = dict(login='mentor-seed', full_name='Mentor Seed', password='private-password')
        self.student = dict(login='student-seed', full_name='Student Seed', password='private-password', parent_phone='+996555123456')
        self.data = dict(schema_version='2.0', mentors=[self.mentor], groups=[dict(group_name='cohort', students=[self.student])], classes=[dict(class_name='cohort-Кибер', group_name='cohort', mentor=self.mentor, unmatched_gradebook_students=[], students=[dict(self.student, exact_gradebook_match=True, source_row_gradebook=3, records=[dict(column='C', header_value='03.08.2025', value='5')])])])
        self.decisions = dict(classes={'cohort-Кибер': dict(study_days='MON_FRI')}, students={'student-seed': dict(parent_name='Parent', primary_class='cohort-Кибер')})

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
        self.assertIn('invalid_parent_phone', issue['reasons'])


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
        for value in ['12345', '89991234567', 'call555123456', '000000000']:
            with self.assertRaises(ValueError):
                normalize_phone(value)

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
