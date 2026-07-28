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
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Stint)
class StintAdmin(admin.ModelAdmin):
    list_display = ("driver", "race", "stint_number")
    list_filter = ("race", "driver")


@admin.register(Lap)
class LapAdmin(admin.ModelAdmin):
    list_display = ("race", "driver", "lap_number", "lap_time", "compound", "is_pit", "track_status", "is_outlier")
    list_filter = ("race", "compound", "is_pit")
    search_fields = ("driver__code",)