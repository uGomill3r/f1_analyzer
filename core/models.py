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
    # Códigos de TrackStatus de FastF1 que indican una condición de pista
    # no representativa del ritmo real (bandera amarilla, SC, VSC, roja).
    # Referencia: FastF1 session.track_status ("1" = pista limpia/verde).
    NON_GREEN_TRACK_STATUS_CODES = {"2", "4", "5", "6", "7"}

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="laps")
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="laps")
    stint = models.ForeignKey(Stint, null=True, blank=True, on_delete=models.SET_NULL, related_name="laps")

    lap_number = models.IntegerField()
    lap_time = models.FloatField(null=True, blank=True)
    compound = models.CharField(max_length=20, blank=True)

    # True si la vuelta es de entrada o salida de pits (PitInTime o PitOutTime
    # presentes en FastF1). No es una "vuelta completa" representativa del ritmo.
    is_pit = models.BooleanField(default=False)

    # Códigos de estado de pista de FastF1 concatenados tal cual vienen
    # (ej: "1", "24", "6"). Vacío si no se pudo determinar.
    track_status = models.CharField(max_length=20, blank=True, default="")

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

    @property
    def outlier_reasons(self):
        """
        Devuelve la lista de motivos por los que esta vuelta podría considerarse
        no representativa del ritmo de carrera. Lista vacía = vuelta "limpia".
        """
        reasons = []

        if self.lap_number == 1:
            reasons.append("first_lap")

        if self.is_pit:
            reasons.append("pit")

        if self.track_status and any(
            code in self.NON_GREEN_TRACK_STATUS_CODES for code in self.track_status
        ):
            reasons.append("track_status")

        return reasons

    @property
    def is_outlier(self):
        """True si la vuelta tiene al menos un motivo para ser excluida del análisis de ritmo."""
        return len(self.outlier_reasons) > 0