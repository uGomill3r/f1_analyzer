from django.contrib import admin

from core.models import Driver, Lap, Race, Stint, Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "team")
    list_filter = ("team",)
    search_fields = ("code", "name")


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    # year, round_code (Rxx), tipo de sesión (Sprint/Race) y nombre del Gran Premio.
    list_display = ("year", "round_code", "get_session_type_display", "gp_name")
    list_filter = ("year", "session_type")
    search_fields = ("gp_name",)
    ordering = ("year", "round_number", "session_type")

    @admin.display(description="Sesión")
    def get_session_type_display(self, obj):
        return obj.get_session_type_display()


@admin.register(Stint)
class StintAdmin(admin.ModelAdmin):
    list_display = ("driver", "race", "stint_number")
    list_filter = ("race", "driver")


@admin.register(Lap)
class LapAdmin(admin.ModelAdmin):
    # is_pit sigue siendo válido acá: list_display admite properties/atributos
    # calculados del modelo, no solo campos de DB.
    list_display = ("race", "driver", "lap_number", "lap_time", "compound", "is_pit", "track_status", "is_outlier")
    # list_filter, en cambio, exige campos reales (o un SimpleListFilter):
    # is_pit ya no es un campo desde que se separó en is_pit_in/is_pit_out.
    list_filter = ("race", "compound", "is_pit_in", "is_pit_out")
    search_fields = ("driver__code",)