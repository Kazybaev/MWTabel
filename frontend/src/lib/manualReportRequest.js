export function buildManualReportRequest({ organization, collegeBranch, month, mode, groupIds, studentIds, confirmRetryFailed }) {
  const body = { organization, month, confirm_retry_failed: confirmRetryFailed };
  if (organization === "college") body.college_branch = collegeBranch;
  if (mode === "groups") body.group_ids = groupIds;
  if (mode === "students") body.student_ids = studentIds;
  return body;
}
