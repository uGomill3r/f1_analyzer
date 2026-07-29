import logging

from django.conf import settings
from django.views.generic import TemplateView

from analytics.modules.registry import MODULES
from core.models import Driver, Lap, Race, RaceResult

logger = logging.getLogger(__name__)

# Página estática (dentro de dashboard/static/dashboard/modules/) asociada a
# cada módulo de analytics registrado. Si un módulo todavía no tiene página
# propia, se usa DEFAULT_MODULE_PAGE como placeholder.
MODULE_PAGES = {
    "pace_by_stint": "dashboard/modules/pace_by_stint.html",
    "laps_in_traffic": "dashboard/modules/laps_in_traffic.html",
    "pace_gap_comparison": "dashboard/modules/pace_gap_comparison.html",
    "lap_times_traffic": "dashboard/modules/lap_times_traffic.html",
}
DEFAULT_MODULE_PAGE = "dashboard/modules/blank.html"

# Etiquetas legibles para el selector de "Funcionalidad" del menú.
MODULE_LABELS = {
    "pace_by_stint": "Ritmo por stint",
    "tyre_degradation_advanced": "Degradación de neumáticos",
    "pace_adjusted": "Pace ajustado",
    "laps_in_traffic": "Vueltas en tráfico",
    "pace_gap_comparison": "Comparación de ritmo",
    "lap_times_traffic": "Tiempos de vuelta + tráfico",
}


def _drivers_by_race(races):
    """
    Roster de pilotos por carrera (código + equipo), ordenado por posición
    final real cuando está disponible (mismo criterio que laps_in_traffic).

    Se arma acá, en el frontend base, y no esperando a que el iframe de un
    módulo lo reporte por postMessage (como hace pace_by_stint): el menú de
    "Comparación de ritmo (2 pilotos)" necesita mostrar los chips de pilotos
    ANTES de que exista una selección con la que consultar /api/analysis, así
    que no hay forma de resolver ese roster desde la respuesta de un módulo.

    Nota de rendimiento: hace 2 queries por carrera (N+1). Para la escala
    actual de la app (herramienta de análisis, no alto tráfico) es aceptable;
    si el número de carreras cargadas crece mucho, conviene resolverlo con
    una sola consulta agregada.
    """
    result = {}

    for race in races:
        driver_ids = Lap.objects.filter(race=race).values_list("driver_id", flat=True).distinct()
        drivers = Driver.objects.filter(id__in=driver_ids).select_related("team")
        positions = dict(
            RaceResult.objects.filter(race=race).values_list("driver__code", "position")
        )

        roster = [
            {
                "code": d.code,
                "team": d.team.name,
                "final_position": positions.get(d.code),
            }
            for d in drivers
        ]
        roster.sort(key=lambda d: (d["final_position"] is None, d["final_position"] or 0))

        result[race.id] = [
            {"code": d["code"], "team": d["team"]} for d in roster
        ]

    return result


class DashboardView(TemplateView):
    """
    Frontend base: título + menú oculto con selectores de año, Gran Premio,
    tipo de sesión (Race/Sprint) y funcionalidad (módulo de analytics).

    Según la combinación elegida, resuelve el race_id correspondiente y carga
    en un iframe la página estática del módulo (o una página en blanco si el
    módulo todavía no tiene una).
    """

    template_name = "dashboard/base.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        races = Race.objects.all().order_by("year", "round_number", "session_type")
        drivers_by_race = _drivers_by_race(races)

        races_payload = [
            {
                "id": race.id,
                "year": race.year,
                "round_number": race.round_number,
                "round_code": race.round_code,
                "gp_name": race.gp_name,
                "session_type": race.session_type,
                "session_type_label": race.get_session_type_display(),
                "drivers": drivers_by_race.get(race.id, []),
            }
            for race in races
        ]

        modules_payload = [
            {
                "name": name,
                "label": MODULE_LABELS.get(name, name),
                "page": MODULE_PAGES.get(name, DEFAULT_MODULE_PAGE),
            }
            for name in MODULES.keys()
        ]

        logger.info(
            "dashboard: render base (%s carreras, %s módulos disponibles)",
            len(races_payload), len(modules_payload),
        )

        context["races"] = races_payload
        context["modules"] = modules_payload
        context["static_url"] = settings.STATIC_URL
        context["default_module_page"] = DEFAULT_MODULE_PAGE
        return context