from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from .report import (
    ReportConfigurationError, get_dify_run_url, get_dify_setting,
    get_report_callback_token, get_report_destination,
)


@register(Tags.security, deploy=True)
def report_integration_deployment_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    messages = []
    for organization in ("academy", "college"):
        destination = get_report_destination(organization)
        api_key = get_dify_setting("API_KEY", organization)
        callback_token = get_report_callback_token(organization)
        try:
            workflow_url = get_dify_run_url(organization)
        except ReportConfigurationError as exc:
            messages.append(Error(f"{destination}: {exc}", id="tabel.E001"))
        else:
            parsed_url = urlparse(workflow_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                messages.append(Error(f"{destination}: Dify workflow URL must be an absolute HTTP(S) URL.", id="tabel.E002"))
            elif parsed_url.scheme != "https":
                messages.append(Warning(
                    f"{destination}: Dify workflow URL uses HTTP; API credentials are not protected by TLS.",
                    hint="Expose Dify through HTTPS before production rollout.", id="tabel.W001",
                ))
        if not api_key:
            messages.append(Error(f"{destination}: Dify API key must be configured.", id="tabel.E003"))
        if len(callback_token) < 32:
            messages.append(Error(f"{destination}: report callback token must contain at least 32 characters.", id="tabel.E004"))
        if api_key and callback_token == api_key:
            messages.append(Error(f"{destination}: Dify API key and callback token must be different.", id="tabel.E005"))
    return messages
