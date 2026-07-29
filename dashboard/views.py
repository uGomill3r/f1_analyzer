import logging

from django.conf import settings
from django.views.generic import TemplateView

from analytics.modules.registry import MODULES
from core.models import Race

logger = logging.getLogger(__name__)

# Página estática (dentro de dashboard/static/dashboard/modules/) asociada a
# cada módulo de analytics registrado. Si un módulo todavía no tiene página
# propia, se usa DEFAULT_MODULE_PAGE como placeholder.
MODULE_PAGES = {
    "pace_by_stint": "dashboard/modules/pace_by_stint.html",
    "laps_in_traffic": "dashboard/modules/laps_in_traffic.html",
}
DEFAULT_MODULE_PAGE = "dashboard/modules/blank.html"

# Etiquetas legibles para el selector de "Funcionalidad" del menú.
MODULE_LABELS = {
    "pace_by_stint": "Ritmo por stint (boxplot)",
    "tyre_degradation_advanced": "Degradación de neumáticos (avanzada)",
    "pace_adjusted": "Pace ajustado",
    "laps_in_traffic": "Vueltas en tráfico (heatmap)",
}


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
        races_payload = [
            {
                "id": race.id,
                "year": race.year,
                "round_number": race.round_number,
                "round_code": race.round_code,
                "gp_name": race.gp_name,
                "session_type": race.session_type,
                "session_type_label": race.get_session_type_display(),
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