# Kuwait monthly report formatter

Target Dify app: `7237fd4d-3859-4b73-b478-61c22df586ce` (`kuveit`).
Baseline published workflow: `133b3a19-0eb7-470c-bc25-2b4518568e3c`.
Meta template requested by the workflow: `student_monthsly_send_v5`, `ky_KG`.

The published formatter had an unconditional requirement for exactly four
subjects. Batch 11 contained three actual subjects in each of its three
failed items. One student also had a fourth group relation, but that group
was archived before the batch and had no October lessons or marks. The other
two students had only three group relations. The backend includes active
assigned subjects even when their grade counts are zero; no subject was
removed merely because it had no marks.

## Exact body parameter contract

The formatter sends 24 text parameters in this order. `subjects` comes from
the college report payload and retains the backend's group order. For a
missing subject slot, the proposed formatter sends `—` in all five fields.

| Position | Name | Source and meaning |
| --- | --- | --- |
| 1 | Main group | `report.main_group.name`, student's college group |
| 2 | Student | `report.student.full_name`, student name |
| 3 | Period | `report.period` or `period_label`, report month/span |
| 4 | Subject 1 | `subjects[0].name`, first assigned subject |
| 5 | Subject 1 grade 5 | `subjects[0].grade_counts["5"]`, number of grade 5 marks |
| 6 | Subject 1 grade 4 | `subjects[0].grade_counts["4"]`, number of grade 4 marks |
| 7 | Subject 1 grade 3 | `subjects[0].grade_counts["3"]`, number of grade 3 marks |
| 8 | Subject 1 grade 2 | `subjects[0].grade_counts["2"]`, number of grade 2 marks |
| 9 | Subject 2 | `subjects[1].name`, second assigned subject |
| 10 | Subject 2 grade 5 | `subjects[1].grade_counts["5"]`, number of grade 5 marks |
| 11 | Subject 2 grade 4 | `subjects[1].grade_counts["4"]`, number of grade 4 marks |
| 12 | Subject 2 grade 3 | `subjects[1].grade_counts["3"]`, number of grade 3 marks |
| 13 | Subject 2 grade 2 | `subjects[1].grade_counts["2"]`, number of grade 2 marks |
| 14 | Subject 3 | `subjects[2].name`, third assigned subject |
| 15 | Subject 3 grade 5 | `subjects[2].grade_counts["5"]`, number of grade 5 marks |
| 16 | Subject 3 grade 4 | `subjects[2].grade_counts["4"]`, number of grade 4 marks |
| 17 | Subject 3 grade 3 | `subjects[2].grade_counts["3"]`, number of grade 3 marks |
| 18 | Subject 3 grade 2 | `subjects[2].grade_counts["2"]`, number of grade 2 marks |
| 19 | Subject 4 | `subjects[3].name`, fourth assigned subject or `—` |
| 20 | Subject 4 grade 5 | `subjects[3].grade_counts["5"]` or `—` if no fourth subject |
| 21 | Subject 4 grade 4 | `subjects[3].grade_counts["4"]` or `—` if no fourth subject |
| 22 | Subject 4 grade 3 | `subjects[3].grade_counts["3"]` or `—` if no fourth subject |
| 23 | Subject 4 grade 2 | `subjects[3].grade_counts["2"]` or `—` if no fourth subject |
| 24 | Absences | Union of `report.absence_dates` and each subject's `absence_dates`, formatted as dates or explicit no-absence text; for exactly three subjects add one final line: `Бул отчетто 3 сабак бар; төртүнчү орундагы «—» сабак жок экенин билдирет.` |

## Publication gate

The workflow's Meta request contains the template name and 24 values. The
user-provided BODY is saved in `meta_body.user_provided.txt`. On 2026-11-07,
a direct Meta read using the published Kuwait workflow's credential returned
HTTP 200 for WABA `2097917931058144` and template `student_monthsly_send_v5`
(`ky_KG`), ID `2053563205335543`, status `APPROVED`. The returned BODY matched
the saved text. The fourth slot's five `—` values are explained in parameter
24 for three-subject reports. On 2026-11-07, the formatter was saved to the
exact Kuwait draft and published as workflow
`213e4bf4-8cd9-408a-858b-db918f4c6bef`. The published code matches
`formatter.py`; the backend callback secret decrypts to the same value as in
the previous published workflow, and the Meta authorization is unchanged.
The new workflow had zero runs at verification. Do not change the Meta
template as part of this patch.

The private published graph and three batch-11 payloads can be supplied to
`runtime_audit.py` in a Dify 1.14.2 container. The audit replaces the code,
both HTTP destinations, and authorization with synthetic values before running
the graph. It never sends a real message.
