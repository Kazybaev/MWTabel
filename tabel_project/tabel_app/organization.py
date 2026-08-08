from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE, User

VALID_ORGANIZATIONS = {ORGANIZATION_ACADEMY, ORGANIZATION_COLLEGE}


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
