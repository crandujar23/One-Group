from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("api/notifications/unread-count", views.notifications_unread_count, name="notifications_unread_count"),
    path("rbac/health/", views.rbac_reports_health, name="rbac_health"),
    path("rbac/users/<int:user_id>/manage/", views.rbac_manage_user_example, name="rbac_manage_user"),
    path("rbac/users/<int:user_id>/approve-commission/", views.rbac_approve_commission_example, name="rbac_approve_commission"),
]
