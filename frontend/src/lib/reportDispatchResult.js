const PHONE_LIKE_PATTERN = /\+?\d[\d\s().-]{6,}\d/g;

export function sanitizeBulkFailureReason(value) {
  return String(value || "")
    .replace(PHONE_LIKE_PATTERN, "[номер скрыт]")
    .slice(0, 300);
}

export function getBulkDispatchPresentation(result) {
  if (result?.status_url) {
    const complete = Number(result.remaining || 0) === 0;
    return {
      title: complete ? "Пакет обработан" : "Пакет поставлен в очередь",
      tone: complete ? (result.failed ? "warning" : "success") : "neutral",
      role: result.failed ? "alert" : "status",
      isBatch: true,
      queued: Number(result.queued || 0),
      processing: Number(result.processing || 0),
      accepted: Number(result.accepted || 0),
      delivered: Number(result.delivered || 0),
      failed: Number(result.failed || 0),
      skipped: Number(result.skipped || 0),
      remaining: Number(result.remaining || 0),
      total: Number(result.total || 0),
      firstError: "",
    };
  }
  const outcome = result?.outcome || (result?.failed ? "partial" : "succeeded");
  const variants = {
    succeeded: {
      title: "Отправка завершена",
      tone: "success",
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
