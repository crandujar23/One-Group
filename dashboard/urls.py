from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-overview/", views.admin_overview, name="admin_overview"),
    path("solar/", views.business_unit_overview, {"unit_key": "solar"}, name="unit_solar"),
    path("solar/cotizador/", views.quoter_iframe, name="quoter_iframe"),
    path("solar/sunrun/", views.sunrun_iframe, name="sunrun_iframe"),
    path("solar/email/", views.email_iframe, name="email_iframe"),
    path("techo/", views.business_unit_overview, {"unit_key": "techo"}, name="unit_techo"),
    path("sunvida/", views.business_unit_overview, {"unit_key": "sunvida"}, name="unit_sunvida"),
    path("cash-d/", views.business_unit_overview, {"unit_key": "cash-d"}, name="unit_cash_d"),
    path("agua/", views.business_unit_overview, {"unit_key": "agua"}, name="unit_agua"),
    path("internet/", views.business_unit_overview, {"unit_key": "internet"}, name="unit_internet"),
    path("sales-overview/", views.sales_overview, name="sales_overview"),
    path("sales/", views.sales_list, name="sales_list"),
    path("sales/<int:pk>/", views.sales_detail, name="sales_detail"),
    path("mi-perfil/", views.associate_profile, name="associate_profile"),
    path("points/", views.points_summary, name="points_summary"),
    path("call-logs/", views.call_logs, name="call_logs"),
    path("call-logs/new/", views.call_log_create, name="call_log_create"),
    path("financiamiento/", views.financing, name="financing"),
    path("asociados/nuevo/", views.associate_create, name="associate_create"),
    path("accesos/", views.access_management, name="access_management"),
    path("gestion-clientes/", views.client_management, name="client_management"),
    path("mi-equipo/", views.my_team, name="my_team"),
    path("tareas/", views.tasks, name="tasks"),
    path("tareas/feed/", views.tasks_calendar_feed, name="tasks_calendar_feed"),
    path("tareas/task/<int:pk>/status/", views.task_update_status, name="task_update_status"),
    path("tareas/cita/<int:pk>/status/", views.appointment_update_status, name="appointment_update_status"),
    path("herramientas/", views.tools, name="tools"),
    path("herramientas/recurso/<int:pk>/", views.tools_resource_present, name="tools_resource_present"),
    path("legales/", views.legal, name="legal"),
    path("ayuda/", views.help_center, name="help_center"),
]
