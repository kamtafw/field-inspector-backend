from django.contrib import admin
from .models import InspectionTemplate, Inspection


@admin.register(InspectionTemplate)
class InspectionTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ["facility_name", "status", "inspector", "created_at"]
    list_filter = ["status"]
    search_fields = ["facility_name", "facility_address"]
    readonly_fields = ["id", "created_at", "updated_at", "version"]
