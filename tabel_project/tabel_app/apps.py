from django.apps import AppConfig


class TabelAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tabel_app'

    def ready(self):
        from .scheduler import start_report_scheduler

        start_report_scheduler()
