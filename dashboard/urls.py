from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-overview/", views.admin_overview, name="admin_overview"),
    path("solar/", views.business_unit_overview, {"unit_key": "solar"}, name="unit_solar"),
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
    path("gestion-clientes/", views.client_management, name="client_management"),
    path("mi-equipo/", views.my_team, name="my_team"),
    path("tareas/", views.tasks, name="tasks"),
    path("herramientas/", views.tools, name="tools"),
    path("legales/", views.legal, name="legal"),
    path("ayuda/", views.help_center, name="help_center"),
]
