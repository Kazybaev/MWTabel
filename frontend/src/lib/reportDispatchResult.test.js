import assert from "node:assert/strict";
import test from "node:test";

import { getBulkDispatchPresentation, sanitizeBulkFailureReason } from "./reportDispatchResult.js";

test("full bulk failure is an alert with the concrete first reason", () => {
  const presentation = getBulkDispatchPresentation({
    outcome: "failed",
    succeeded: 0,
    sent: 0,
    failed: 188,
    skipped: 0,
    total: 188,
    first_error: "DIFY_API_KEY must be configured.",
  });

  assert.equal(presentation.title, "Отправка не выполнена");
  assert.equal(presentation.role, "alert");
  assert.equal(presentation.failed, 188);
  assert.equal(presentation.firstError, "DIFY_API_KEY must be configured.");
});

test("partial bulk failure has a distinct warning presentation", () => {
  const presentation = getBulkDispatchPresentation({
    outcome: "partial",
    succeeded: 3,
    sent: 3,
    failed: 1,
    skipped: 2,
    total: 6,
    first_error: "Dify returned HTTP 500.",
  });

  assert.equal(presentation.title, "Отправка завершена частично");
  assert.equal(presentation.tone, "warning");
  assert.deepEqual(
    [presentation.succeeded, presentation.failed, presentation.skipped, presentation.total],
    [3, 1, 2, 6],
  );
});

test("general banner masks phone-like values", () => {
  assert.equal(
    sanitizeBulkFailureReason("Recipient +996 700 123 456 rejected"),
    "Recipient [номер скрыт] rejected",
  );
});

test("persistent batch exposes queue progress without treating accepted as delivered", () => {
  const presentation = getBulkDispatchPresentation({
    status: "processing",
    status_url: "/api/reports/batches/7/",
    queued: 8,
    processing: 1,
    accepted: 3,
    delivered: 2,
    failed: 1,
    skipped: 4,
    remaining: 9,
    total: 19,
  });

  assert.equal(presentation.isBatch, true);
  assert.equal(presentation.accepted, 3);
  assert.equal(presentation.delivered, 2);
  assert.equal(presentation.remaining, 9);
});
