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
    """
    Representa una sesión de tipo Race o Sprint de un Gran Premio.

    Se identifica de forma única por año + número de ronda del campeonato +
    tipo de sesión, ya que un mismo fin de semana "sprint" puede tener tanto
    una sesión Race como una Sprint (ambas con datos de vueltas relevantes
    para el análisis de ritmo).

    El número de ronda (round_number) y el nombre corto del Gran Premio
    (gp_name) se obtienen de FastF1 (session.event.RoundNumber /
    session.event.EventName). A partir de round_number se construye la
    nomenclatura "Rxx" usada en toda la app (ver la propiedad round_code).
    """

    SESSION_RACE = "R"
    SESSION_SPRINT = "S"
    SESSION_TYPE_CHOICES = [
        (SESSION_RACE, "Race"),
        (SESSION_SPRINT, "Sprint"),
    ]

    year = models.PositiveSmallIntegerField(
        help_text="Temporada del campeonato (ej: 2026)."
    )
    round_number = models.PositiveSmallIntegerField(
        help_text="Número de ronda dentro de la temporada (1, 2, 3, ...), según FastF1."
    )
    gp_name = models.CharField(
        max_length=100,
        help_text="Nombre corto del Gran Premio (FastF1 EventName), ej: 'Hungarian Grand Prix'.",
    )
    session_type = models.CharField(
        max_length=1, choices=SESSION_TYPE_CHOICES, default=SESSION_RACE
    )

    class Meta:
        ordering = ["year", "round_number", "session_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "round_number", "session_type"],
                name="unique_race_session_per_round",
            )
        ]

    @property
    def round_code(self):
        """Nomenclatura Rxx de la ronda dentro de la temporada (ej: R01, R13)."""
        return f"R{self.round_number:02d}"

    round_code.fget.short_description = "Ronda"

    def __str__(self):
        return f"{self.year} {self.round_code} - {self.gp_name} ({self.get_session_type_display()})"


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
        return f"{self.driver.code} - {self.race} - stint {self.stint_number}"


class Lap(models.Model):
    # Códigos de TrackStatus de FastF1 que indican una condición de pista
    # no representativa del ritmo real (bandera amarilla, SC, VSC, roja).
    # Referencia: FastF1 session.track_status ("1" = pista limpia/verde).
    NON_GREEN_TRACK_STATUS_CODES = {"2", "4", "5", "6", "7"}

    # Umbral del chart "Laps in traffic": un piloto se considera "en tráfico"
    # si pasó más de este % de la vuelta a menos de TRAFFIC_GAP_THRESHOLD_SECONDS
    # (ver core/services/traffic.py) del auto de adelante.
    IN_TRAFFIC_THRESHOLD_PCT = 33.0

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

    # Gap promedio (segundos) al auto de adelante durante la vuelta, calculado
    # a partir de telemetría (ver core/services/traffic.py). None si no se
    # pudo calcular (sin telemetría, vuelta bajo SC/VSC, o piloto sin auto
    # adelante en ese tramo).
    gap_to_front = models.FloatField(null=True, blank=True)

    # % de la vuelta en que el gap al auto de adelante estuvo por debajo del
    # umbral de tráfico. None con el mismo criterio que gap_to_front (y en
    # particular: FastF1 / la especificación del chart excluye explícitamente
    # las vueltas completadas bajo SC o VSC).
    traffic_pct = models.FloatField(null=True, blank=True)

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
        return f"{self.driver.code} - {self.race} - vuelta {self.lap_number}"

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

    @property
    def in_traffic(self):
        """
        True/False si el piloto pasó más de IN_TRAFFIC_THRESHOLD_PCT de la
        vuelta a menos de 2s del auto de adelante. None si no hay dato
        (traffic_pct no calculado, ej: vuelta bajo SC/VSC).
        """
        if self.traffic_pct is None:
            return None
        return self.traffic_pct > self.IN_TRAFFIC_THRESHOLD_PCT