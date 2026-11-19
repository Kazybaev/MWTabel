from __future__ import annotations

import os

from .models import (
    COLLEGE_BRANCH_AGRARIAN,
    COLLEGE_BRANCH_KUWAIT,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    StudentProfile,
)


ROUTE_ACADEMY = "academy"
ROUTE_KUWAIT = "kuwait"
ROUTE_AGRARIAN = "agrarian"
WORKFLOW_ROUTES = (ROUTE_ACADEMY, ROUTE_KUWAIT, ROUTE_AGRARIAN)

ROUTE_API_KEY_ENV = {
    ROUTE_ACADEMY: "DIFY_ACADEMY_API_KEY",
    ROUTE_KUWAIT: "DIFY_KUWAIT_API_KEY",
    ROUTE_AGRARIAN: "DIFY_AGRARIAN_API_KEY",
}

ROUTE_UNAVAILABLE_MESSAGES = {
    ROUTE_ACADEMY: "Отправка отчётов академии пока не настроена.",
    ROUTE_KUWAIT: "Отправка отчётов колледжа Kuwait пока не настроена.",
    ROUTE_AGRARIAN: "Отправка отчётов Аграрного колледжа пока не настроена.",
}


class ReportRouteError(ValueError):
    pass


def workflow_route_for_context(organization_type: str, college_branch: str | None = None) -> str:
    if organization_type == ORGANIZATION_ACADEMY:
        if college_branch:
            raise ReportRouteError("У академии не может быть маршрута колледжа.")
        return ROUTE_ACADEMY
    if organization_type != ORGANIZATION_COLLEGE:
        raise ReportRouteError("Неизвестная организация для отправки отчёта.")
    if college_branch == COLLEGE_BRANCH_KUWAIT:
        return ROUTE_KUWAIT
    if college_branch == COLLEGE_BRANCH_AGRARIAN:
        return ROUTE_AGRARIAN
    raise ReportRouteError("Для колледжа не определён проверенный маршрут отчёта.")


def workflow_route_for_student(student: StudentProfile) -> str:
    group = student.group
    if student.organization_type != group.organization_type:
        raise ReportRouteError("Организация студента не совпадает с организацией группы.")
    if student.organization_type == ORGANIZATION_COLLEGE:
        if student.college_branch != group.college_branch:
            raise ReportRouteError("Колледж студента не совпадает с колледжем группы.")
        return workflow_route_for_context(student.organization_type, student.college_branch)
    return workflow_route_for_context(student.organization_type)


def get_route_api_key(workflow_route: str) -> str:
    env_name = ROUTE_API_KEY_ENV.get(workflow_route)
    if env_name is None:
        raise ReportRouteError("Неизвестный маршрут отчёта.")
    api_key = os.getenv(env_name, "").strip()
    if not api_key:
        raise ReportRouteError(ROUTE_UNAVAILABLE_MESSAGES[workflow_route])
    return api_key


def ensure_route_configured(workflow_route: str) -> None:
    get_route_api_key(workflow_route)
