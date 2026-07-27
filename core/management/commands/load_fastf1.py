from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Driver, Lap, Race, Stint, Team


class Command(BaseCommand):
    help = "Descarga una sesión de FastF1 y la carga en la base de datos."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True, help="Ej: 2026")
        parser.add_argument("--race", type=str, required=True, help="Ej: 'Hungarian'")
        parser.add_argument(
            "--session", type=str, default="R",
            help="Sesión FastF1: R, Q, FP1, FP2, FP3, S (default: R)",
        )
        parser.add_argument(
            "--race-name", type=str, default=None,
            help="Nombre a guardar en el modelo Race (default: '<race> <year>')",
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
        session_type = options["session"]
        race_name = options["race_name"] or f"{race_input} {year}"

        self.stdout.write(f"Descargando {race_input} {year} ({session_type})...")

        try:
            session = fastf1.get_session(year, race_input, session_type)
            session.load()
        except Exception as exc:
            raise CommandError(f"No se pudo cargar la sesión de FastF1: {exc}") from exc

        laps_df = session.laps
        if laps_df is None or laps_df.empty:
            raise CommandError("La sesión no tiene datos de vueltas disponibles.")

        created_laps = 0
        updated_laps = 0

        with transaction.atomic():
            race, _ = Race.objects.get_or_create(name=race_name)

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

                    _, created = Lap.objects.update_or_create(
                        driver=driver,
                        race=race,
                        lap_number=int(lap["LapNumber"]),
                        defaults={
                            "stint": stint,
                            "lap_time": lap_time,
                            "compound": lap["Compound"] or "",
                            "is_pit": pd.notna(lap["PitOutTime"]),
                        },
                    )
                    if created:
                        created_laps += 1
                    else:
                        updated_laps += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo. Vueltas creadas: {created_laps}, actualizadas: {updated_laps}."
        ))
