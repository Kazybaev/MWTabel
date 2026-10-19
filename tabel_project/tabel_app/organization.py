from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import (
    COLLEGE_BRANCH_AGRARIAN,
    COLLEGE_BRANCH_KUWAIT,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    User,
)

VALID_ORGANIZATIONS = {ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE}
VALID_COLLEGE_BRANCHES = {COLLEGE_BRANCH_KUWAIT, COLLEGE_BRANCH_AGRARIAN}


def allowed_organizations_for_user(user):
    if not user or not user.is_authenticated or not user.is_active:
        return []
    explicit = list(
        user.organization_accesses.order_by("organization_type").values_list(
            "organization_type", flat=True
        )
    )
    if explicit:
        return explicit
    if user.role == User.ROLE_ADMIN:
        return [ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE]
    if user.role == User.ROLE_MENTOR and hasattr(user, "mentor_profile"):
        return [user.mentor_profile.organization_type]
    if user.role == User.ROLE_STUDENT and hasattr(user, "student_profile"):
        return [user.student_profile.organization_type]
    return [ORGANIZATION_ACADEMY]


def organization_for_request(request):
    value = request.headers.get("X-Organization-Type", ORGANIZATION_ACADEMY).strip().lower()
    if value not in VALID_ORGANIZATIONS:
        raise ValidationError({"organization_type": "Неизвестный тип организации."})
    if value not in allowed_organizations_for_user(request.user):
        raise PermissionDenied("Нет доступа к выбранной организации.")
    return value


def college_branch_for_request(request):
    """Return and authorize the selected college without affecting academy requests."""
    if organization_for_request(request) != ORGANIZATION_COLLEGE:
        return None

    value = request.headers.get("X-College-Branch", COLLEGE_BRANCH_KUWAIT).strip().lower()
    if value not in VALID_COLLEGE_BRANCHES:
        raise ValidationError({"college_branch": "Неизвестный колледж."})

    student_profile = getattr(request.user, "student_profile", None)
    if request.user.role == User.ROLE_STUDENT and student_profile:
        if value != student_profile.college_branch:
            raise PermissionDenied("Нет доступа к выбранному колледжу.")
    return value


def require_agrarian_college(request):
    if organization_for_request(request) != ORGANIZATION_COLLEGE:
        raise PermissionDenied("Функция доступна только в колледже.")
    if college_branch_for_request(request) != COLLEGE_BRANCH_AGRARIAN:
        raise PermissionDenied("Функция доступна только в Аграрном колледже.")
    return COLLEGE_BRANCH_AGRARIAN
