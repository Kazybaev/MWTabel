import os
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from .report import ReportConfigurationError, get_dify_run_url


@register(Tags.security, deploy=True)
def report_integration_deployment_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    messages = []
    api_key = os.getenv("DIFY_API_KEY", "").strip()
    callback_token = os.getenv("BACKEND_REPORT_CALLBACK_TOKEN", "").strip()

    try:
        workflow_url = get_dify_run_url()
    except ReportConfigurationError as exc:
        messages.append(Error(str(exc), id="tabel.E001"))
    else:
        parsed_url = urlparse(workflow_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            messages.append(Error("Dify workflow URL must be an absolute HTTP(S) URL.", id="tabel.E002"))
        elif parsed_url.scheme != "https":
            messages.append(
                Warning(
                    "Dify workflow URL uses HTTP; API credentials are not protected by TLS.",
                    hint="Expose Dify through HTTPS before production rollout.",
                    id="tabel.W001",
                )
            )

    if not api_key:
        messages.append(Error("DIFY_API_KEY must be configured.", id="tabel.E003"))
    if len(callback_token) < 32:
        messages.append(
            Error(
                "BACKEND_REPORT_CALLBACK_TOKEN must contain at least 32 characters.",
                id="tabel.E004",
            )
        )
    if api_key and callback_token == api_key:
        messages.append(Error("Dify API key and callback token must be different.", id="tabel.E005"))
    return messages
