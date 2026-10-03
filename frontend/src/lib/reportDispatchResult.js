const PHONE_LIKE_PATTERN = /\+?\d[\d\s().-]{6,}\d/g;

export function sanitizeBulkFailureReason(value) {
  return String(value || "")
    .replace(PHONE_LIKE_PATTERN, "[номер скрыт]")
    .slice(0, 300);
}

export function shouldPollReportBatch(result) {
  return Boolean(
    result?.status_url
    && !["completed", "cancelled"].includes(result.status)
    && Number(result.remaining || 0) > 0,
  );
}

export function getBulkDispatchPresentation(result) {
  if (result?.status_url) {
    const batchStatus = result.status || "queued";
    const failed = Number(result.failed || 0);
    const accepted = Number(result.accepted || 0);
    const variants = {
      queued: { title: "Пакет в очереди", tone: "neutral", role: "status" },
      processing: { title: "Пакет обрабатывается", tone: "neutral", role: "status" },
      completed: failed
        ? { title: "Пакет завершён с ошибками", tone: "warning", role: "alert" }
        : accepted
          ? { title: "Пакет обработан, доставка ожидает подтверждения", tone: "warning", role: "status" }
          : { title: "Пакет обработан", tone: "neutral", role: "status" },
      cancelled: { title: "Пакет отменён", tone: "neutral", role: "status" },
    };
    const variant = variants[batchStatus] || variants.processing;
    return {
      ...variant,
      isBatch: true,
      queued: Number(result.queued || 0),
      processing: Number(result.processing || 0),
      accepted,
      delivered: Number(result.delivered || 0),
      failed,
      skipped: Number(result.skipped || 0),
      cancelled: Number(result.cancelled || 0),
      remaining: Number(result.remaining || 0),
      total: Number(result.total || 0),
      firstError: "",
    };
  }
  const outcome = result?.outcome || (result?.failed ? "partial" : "succeeded");
  const variants = {
    succeeded: {
      title: "Обработка завершена",
      tone: "neutral",
      role: "status",
    },
    partial: {
      title: "Отправка завершена частично",
      tone: "warning",
      role: "alert",
    },
    failed: {
      title: "Отправка не выполнена",
      tone: "danger",
      role: "alert",
    },
    skipped: {
      title: "Новые отчёты не отправлялись",
      tone: "neutral",
      role: "status",
    },
  };
  const variant = variants[outcome] || variants.failed;

  return {
    ...variant,
    succeeded: Number(result?.succeeded ?? result?.sent ?? 0),
    failed: Number(result?.failed || 0),
    skipped: Number(result?.skipped || 0),
    total: Number(result?.total || 0),
    firstError: sanitizeBulkFailureReason(result?.first_error),
  };
}
