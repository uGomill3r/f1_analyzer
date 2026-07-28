import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Driver, Lap, Race, Stint, Team

logger = logging.getLogger(__name__)

# Mapeo de session.name (FastF1) al session_type interno de Race.
# Solo se soportan sesiones "de carrera" (Race / Sprint): son las únicas que
# tienen datos de vueltas relevantes para los módulos de ritmo de carrera.
# Nota: en 2021 FastF1 llamó "Sprint Qualifying" a lo que hoy es la Sprint.
SESSION_NAME_TO_TYPE = {
    "Race": Race.SESSION_RACE,
    "Sprint": Race.SESSION_SPRINT,
    "Sprint Qualifying": Race.SESSION_SPRINT,
}


class Command(BaseCommand):
    help = "Descarga una sesión de FastF1 (Race o Sprint) y la carga en la base de datos."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Ej: 2026")
        parser.add_argument("--race", type=str, required=True, help="Ej: 'Hungarian'")
        parser.add_argument(
            "--session", type=str, default="R",
            help="Identificador de sesión FastF1: 'R' (Race) o 'S' (Sprint). Default: R",
        )
        parser.add_argument(
            "--gp-name", type=str, default=None,
            help="Nombre a guardar como gp_name (default: session.event.EventName de FastF1)",
        )

    def handle(self, *args, **options):
        try:
            import fastf1
            import pandas as pd
        except ImportError as exc:
            raise CommandError(
                "fastf1 y pandas son requeridos para este comando. "
                "Instala las dependencias con: pip install -r requirements.txt"
            ) from exc

        fastf1.Cache.enable_cache(settings.FASTF1_CACHE_DIR)

        year = options["year"]
        race_input = options["race"]
        session_identifier = options["session"]

        self.stdout.write(f"Descargando {race_input} {year} ({session_identifier})...")
        logger.info(
            "load_fastf1: iniciando descarga year=%s race=%s session=%s",
            year, race_input, session_identifier,
        )

        try:
            session = fastf1.get_session(year, race_input, session_identifier)
            session.load()
        except Exception as exc:
            logger.exception("load_fastf1: fallo al cargar la sesión de FastF1")
            raise CommandError(f"No se pudo cargar la sesión de FastF1: {exc}") from exc

        # -----------------------------
        # Resolver año / ronda (Rxx) / tipo de sesión a partir de FastF1
        # -----------------------------

        session_type = SESSION_NAME_TO_TYPE.get(session.name)
        if session_type is None:
            raise CommandError(
                f"Tipo de sesión '{session.name}' no soportado por este comando. "
                "Solo se admiten sesiones de tipo Race o Sprint (ritmo de carrera)."
            )

        round_number = int(session.event.RoundNumber)
        gp_name = options["gp_name"] or session.event.EventName

        laps_df = session.laps
        if laps_df is None or laps_df.empty:
            raise CommandError("La sesión no tiene datos de vueltas disponibles.")

        created_laps = 0
        updated_laps = 0

        with transaction.atomic():
            # Idempotente: si la ronda + tipo de sesión ya existe, se actualiza
            # el gp_name en vez de duplicar el registro.
            race, race_created = Race.objects.update_or_create(
                year=year,
                round_number=round_number,
                session_type=session_type,
                defaults={"gp_name": gp_name},
            )

            self.stdout.write(
                f"{'Creado' if race_created else 'Actualizado'} registro de carrera: "
                f"{race} (ronda {race.round_code})"
            )
            logger.info(
                "load_fastf1: race id=%s year=%s round=%s (%s) session_type=%s creada=%s",
                race.id, race.year, race.round_number, race.round_code,
                race.session_type, race_created,
            )

            for driver_code in laps_df["Driver"].unique():
                driver_laps = laps_df.pick_drivers(driver_code) if hasattr(
                    laps_df, "pick_drivers"
                ) else laps_df.pick_driver(driver_code)

                team_name = driver_laps["Team"].iloc[0]
                team, _ = Team.objects.get_or_create(name=team_name)
                driver, _ = Driver.objects.get_or_create(
                    code=driver_code, defaults={"team": team}
                )
                if driver.team_id != team.id:
                    driver.team = team
                    driver.save(update_fields=["team"])

                for _, lap in driver_laps.iterrows():
                    stint_number = int(lap["Stint"]) if not pd.isna(lap["Stint"]) else 0
                    stint, _ = Stint.objects.get_or_create(
                        driver=driver, race=race, stint_number=stint_number
                    )

                    lap_time = (
                        lap["LapTime"].total_seconds()
                        if pd.notna(lap["LapTime"])
                        else None
                    )

                    # una vuelta es "de pits" si entra o sale del pit lane en ella
                    is_pit = pd.notna(lap.get("PitInTime")) or pd.notna(lap.get("PitOutTime"))

                    # TrackStatus puede venir como NaN o como string de códigos (ej: "1", "24")
                    track_status_raw = lap.get("TrackStatus")
                    track_status = (
                        str(track_status_raw) if pd.notna(track_status_raw) else ""
                    )

                    _, created = Lap.objects.update_or_create(
                        driver=driver,
                        race=race,
                        lap_number=int(lap["LapNumber"]),
                        defaults={
                            "stint": stint,
                            "lap_time": lap_time,
                            "compound": lap["Compound"] or "",
                            "is_pit": is_pit,
                            "track_status": track_status,
                        },
                    )
                    if created:
                        created_laps += 1
                    else:
                        updated_laps += 1

        logger.info(
            "load_fastf1: finalizado race_id=%s creadas=%s actualizadas=%s",
            race.id, created_laps, updated_laps,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Listo. Vueltas creadas: {created_laps}, actualizadas: {updated_laps}."
        ))
