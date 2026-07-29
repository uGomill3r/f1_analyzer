import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Driver, Lap, Race, RaceResult, Stint, Team
from core.services.traffic import compute_traffic_by_driver

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

        # -----------------------------
        # Tráfico por vuelta (telemetría): se calcula ANTES de la transacción
        # porque es una operación de solo lectura sobre FastF1 (no toca la
        # base) y puede tardar bastante (arma curvas distancia-tiempo por
        # piloto con toda su telemetría de carrera). Si falla, se sigue
        # cargando el resto de los datos sin tráfico (no es bloqueante).
        # -----------------------------
        self.stdout.write("Calculando % de vuelta en tráfico (telemetría)...")
        try:
            traffic_by_driver = compute_traffic_by_driver(session)
        except Exception:
            logger.exception(
                "load_fastf1: fallo calculando tráfico por telemetría; "
                "se continúa sin traffic_pct/gap_to_front."
            )
            traffic_by_driver = {}

        # Resumen visible por stdout (no solo por logging: si el logger de
        # core.services.traffic no tiene handler configurado en settings.py,
        # sus INFO/WARNING no se ven en consola y un fallo silencioso pasa
        # desapercibido).
        laps_with_traffic = sum(len(v) for v in traffic_by_driver.values())
        if laps_with_traffic == 0:
            self.stdout.write(self.style.WARNING(
                "No se pudo calcular traffic_pct para ninguna vuelta "
                "(telemetría no disponible o fallo silencioso; revisá los logs)."
            ))
        else:
            self.stdout.write(f"Tráfico calculado para {laps_with_traffic} vuelta(s) en total.")

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

                driver_traffic = traffic_by_driver.get(driver_code, {})

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

                    # El chart "Laps in traffic" excluye explícitamente las
                    # vueltas bajo SC/VSC/bandera: aunque se haya podido
                    # calcular el % de tráfico, se descarta acá.
                    is_non_green = bool(track_status) and any(
                        code in Lap.NON_GREEN_TRACK_STATUS_CODES for code in track_status
                    )

                    lap_number = int(lap["LapNumber"])
                    traffic_info = driver_traffic.get(lap_number)

                    traffic_pct = None
                    gap_to_front = None
                    if traffic_info and not is_non_green:
                        traffic_pct = traffic_info["traffic_pct"]
                        gap_to_front = traffic_info["mean_gap"]

                    _, created = Lap.objects.update_or_create(
                        driver=driver,
                        race=race,
                        lap_number=lap_number,
                        defaults={
                            "stint": stint,
                            "lap_time": lap_time,
                            "compound": lap["Compound"] or "",
                            "is_pit": is_pit,
                            "track_status": track_status,
                            "traffic_pct": traffic_pct,
                            "gap_to_front": gap_to_front,
                        },
                    )
                    if created:
                        created_laps += 1
                    else:
                        updated_laps += 1

            # -----------------------------
            # Resultado final (posición de clasificación): se usa para
            # ordenar charts (ej: heatmap de laps_in_traffic) según la
            # llegada real en vez de aproximarla por cantidad de vueltas.
            # Se guarda a partir de session.results (no de laps_df), así
            # que también cubre pilotos sin vueltas registradas (ej: DNS).
            # -----------------------------
            results_df = session.results
            results_saved = 0

            if results_df is None or results_df.empty:
                logger.warning(
                    "load_fastf1: session.results vacío para race_id=%s; "
                    "no se guardó RaceResult (el orden por vueltas quedará como fallback).",
                    race.id,
                )
            else:
                for _, row in results_df.iterrows():
                    driver_code = row.get("Abbreviation")
                    if not driver_code:
                        continue

                    team_name = row.get("TeamName") or "Unknown"
                    team, _ = Team.objects.get_or_create(name=team_name)
                    driver, _ = Driver.objects.get_or_create(
                        code=driver_code, defaults={"team": team}
                    )

                    position_raw = row.get("Position")
                    position = int(position_raw) if pd.notna(position_raw) else None
                    classified_position_raw = str(row.get("ClassifiedPosition") or "")
                    status = str(row.get("Status") or "")

                    RaceResult.objects.update_or_create(
                        driver=driver,
                        race=race,
                        defaults={
                            "position": position,
                            "classified_position_raw": classified_position_raw,
                            "status": status,
                        },
                    )
                    results_saved += 1

                logger.info(
                    "load_fastf1: race_id=%s -> %s resultado(s) de clasificación guardados.",
                    race.id, results_saved,
                )

        logger.info(
            "load_fastf1: finalizado race_id=%s creadas=%s actualizadas=%s",
            race.id, created_laps, updated_laps,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Listo. Vueltas creadas: {created_laps}, actualizadas: {updated_laps}."
        ))