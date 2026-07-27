from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Driver(models.Model):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=100, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="drivers")

    def __str__(self):
        return self.code


class Race(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Stint(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="stints")
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="stints")
    stint_number = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["driver", "race", "stint_number"],
                name="unique_stint_per_driver_race",
            )
        ]

    def __str__(self):
        return f"{self.driver.code} - {self.race.name} - stint {self.stint_number}"


class Lap(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="laps")
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="laps")
    stint = models.ForeignKey(Stint, null=True, blank=True, on_delete=models.SET_NULL, related_name="laps")

    lap_number = models.IntegerField()
    lap_time = models.FloatField(null=True, blank=True)
    compound = models.CharField(max_length=20, blank=True)

    is_pit = models.BooleanField(default=False)

    # opcional (para el módulo pace_adjusted)
    gap_to_front = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["race", "driver", "lap_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["driver", "race", "lap_number"],
                name="unique_lap_per_driver_race",
            )
        ]
        indexes = [
            models.Index(fields=["race", "driver"]),
            models.Index(fields=["race", "compound"]),
        ]

    def __str__(self):
        return f"{self.driver.code} - {self.race.name} - vuelta {self.lap_number}"
