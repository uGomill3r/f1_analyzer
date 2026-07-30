# analytics/management/commands/dump_pace_correction.py
import csv
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.services.pace_correction import compute_pace_corrections
from core.models import Lap

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Exporta a CSV el desglose de la corrección de ritmo (raw, fuel_corrected, "
        "tyre_corrected, track_delta, track_corrected) por piloto/vuelta. Pensado "
        "para diagnosticar valores inesperados de corrected_time (ej: cercanos a 0 "
        "o negativos), ver docstring de analytics/services/pace_correction.py."
    )

    def add_arguments(self, parser):
        parser.add_argument("--race-id", type=int, required=True, help="ID de la carrera (Race.id).")
        parser.add_argument("--driver", action="append", default=None, help="Código de piloto (repetible).")
        parser.add_argument("--team", action="append", default=None, help="Nombre de equipo (repetible).")
        parser.add_argument("--compound", action="append", default=None, help="Compuesto (repetible).")
        parser.add_argument(
            "--exclude-traffic",
            action="store_true",
            help=(
                "Excluir del ajuste las vueltas en tráfico (mismo criterio que "
                "pace_adjusted). Por defecto NO se excluyen (mismo criterio que "
                "lap_times_traffic)."
            ),
        )
        parser.add_argument(
            "--output", default="pace_correction_debug.csv", help="Ruta del CSV de salida."
        )

    def handle(self, *args, **options):
        race_id = options["race_id"]

        qs = Lap.objects.select_related(
            "driver", "driver__team", "race", "stint"
        ).filter(
            race_id=race_id,
            lap_time__isnull=False,
        )

        if options["driver"]:
            qs = qs.filter(driver__code__in=options["driver"])
        if options["team"]:
            qs = qs.filter(driver__team__name__in=options["team"])
        if options["compound"]:
            qs = qs.filter(compound__in=options["compound"])

        if not qs.exists():
            raise CommandError(f"No hay vueltas para race_id={race_id} con esos filtros.")

        per_driver_data = compute_pace_corrections(
            qs,
            fuel_coef=settings.FUEL_CORRECTION_PER_LAP,
            exclude_traffic=options["exclude_traffic"],
        )

        if not per_driver_data:
            raise CommandError(
                "compute_pace_corrections no devolvió datos (ver logs WARNING arriba: "
                "probablemente ningún piloto llega al mínimo de vueltas tras los filtros)."
            )

        rows = []
        for driver_code, data in per_driver_data.items():
            for i in range(len(data["lap_numbers"])):
                tyre_corrected = float(data["tyre_corrected"][i])
                track_corrected = float(data["track_corrected"][i])
                rows.append({
                    "driver": driver_code,
                    "lap": int(data["lap_numbers"][i]),
                    "raw": round(float(data["raw"][i]), 3),
                    "fuel_corrected": round(float(data["fuel_corrected"][i]), 3),
                    "tyre_corrected": round(tyre_corrected, 3),
                    # track_delta = lo que restó el ajuste de evolución de pista
                    # (polyval(track_model, lap_number)); se reconstruye acá
                    # porque compute_pace_corrections no lo expone por separado.
                    "track_delta": round(tyre_corrected - track_corrected, 3),
                    "track_corrected": round(track_corrected, 3),
                })

        rows.sort(key=lambda r: (r["driver"], r["lap"]))

        with open(options["output"], "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "driver", "lap", "raw", "fuel_corrected",
                "tyre_corrected", "track_delta", "track_corrected",
            ])
            writer.writeheader()
            writer.writerows(rows)

        logger.info(
            "dump_pace_correction: race_id=%s -> %s fila(s) exportadas a %s",
            race_id, len(rows), options["output"]
        )
        self.stdout.write(self.style.SUCCESS(
            f"OK: {len(rows)} vuelta(s) exportadas a {options['output']}"
        ))
