from django.contrib import admin

from dashboard.models import Appointment
from dashboard.models import Announcement
from dashboard.models import CalendarEvent
from dashboard.models import Offer
from dashboard.models import ResourceTag
from dashboard.models import SharedResource
from dashboard.models import Task


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "kind", "start_at", "end_at", "all_day")
    list_filter = ("kind", "all_day", "owner")
    search_fields = ("title", "description")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "priority", "due_at", "completed_at")
    list_filter = ("status", "priority", "owner")
    search_fields = ("title", "description")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("subject", "contact_name", "owner", "status", "start_at", "end_at")
    list_filter = ("status", "owner")
    search_fields = ("subject", "contact_name", "location")


@admin.register(SharedResource)
class SharedResourceAdmin(admin.ModelAdmin):
    list_display = ("title", "provider", "resource_type", "is_active", "created_by", "created_at")
    list_filter = ("resource_type", "is_active", "created_by")
    search_fields = ("title", "provider", "description", "video_url")
    filter_horizontal = ("tags",)


@admin.register(ResourceTag)
class ResourceTagAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "media_type", "start_date", "end_date", "is_active", "created_by", "created_at")
    list_filter = ("media_type", "is_active", "start_date", "end_date", "created_by")
    search_fields = ("title", "message", "video_url")


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("title", "media_type", "start_date", "end_date", "is_active", "created_by", "created_at")
    list_filter = ("media_type", "is_active", "start_date", "end_date", "created_by")
    search_fields = ("title", "message", "video_url")
