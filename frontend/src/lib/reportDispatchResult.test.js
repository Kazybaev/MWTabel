import assert from "node:assert/strict";
import test from "node:test";

import {
  getBulkDispatchPresentation,
  sanitizeBulkFailureReason,
  shouldPollReportBatch,
} from "./reportDispatchResult.js";

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
  assert.equal(presentation.title, "Пакет обрабатывается");
});

test("polling continues when remaining is unchanged until the batch is terminal", () => {
  const unchanged = {
    status: "processing",
    status_url: "/api/reports/batches/7/",
    remaining: 9,
  };
  assert.equal(shouldPollReportBatch(unchanged), true);
  assert.equal(shouldPollReportBatch({ ...unchanged }), true);
  assert.equal(shouldPollReportBatch({ ...unchanged, status: "completed", remaining: 0 }), false);
  assert.equal(shouldPollReportBatch({ ...unchanged, status: "cancelled", remaining: 0 }), false);
});

test("batch presentation distinguishes queued, processing, processed and error states", () => {
  const base = { status_url: "/api/reports/batches/7/", total: 1 };
  assert.equal(getBulkDispatchPresentation({ ...base, status: "queued", remaining: 1 }).title, "Пакет в очереди");
  assert.equal(getBulkDispatchPresentation({ ...base, status: "processing", remaining: 1 }).title, "Пакет обрабатывается");
  assert.equal(getBulkDispatchPresentation({ ...base, status: "completed", remaining: 0 }).title, "Пакет обработан");
  assert.equal(
    getBulkDispatchPresentation({ ...base, status: "completed", remaining: 0, accepted: 1 }).title,
    "Пакет обработан, доставка ожидает подтверждения",
  );
  assert.equal(
    getBulkDispatchPresentation({ ...base, status: "completed", remaining: 0, failed: 1 }).title,
    "Пакет завершён с ошибками",
  );
});
