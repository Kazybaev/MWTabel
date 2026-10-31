import assert from "node:assert/strict";
import test from "node:test";
import { buildManualReportRequest } from "./manualReportRequest.js";

for (const [organization, collegeBranch] of [["academy", undefined], ["college", "kuwait"], ["college", "agrarian"]]) {
  test(`manual report request isolates ${collegeBranch || organization}`, () => {
    const base = { organization, collegeBranch, month: "2026-09", confirmRetryFailed: false, groupIds: [14], studentIds: [100] };
    const all = buildManualReportRequest({ ...base, mode: "all" });
    const groups = buildManualReportRequest({ ...base, mode: "groups" });
    const students = buildManualReportRequest({ ...base, mode: "students" });
    assert.equal(all.organization, organization);
    assert.equal(all.college_branch, collegeBranch);
    assert.equal(all.month, "2026-09");
    assert.equal("group_ids" in all || "student_ids" in all, false);
    assert.deepEqual(groups.group_ids, [14]);
    assert.equal("student_ids" in groups, false);
    assert.deepEqual(students.student_ids, [100]);
    assert.equal("group_ids" in students, false);
  });
}
