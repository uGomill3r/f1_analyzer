from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.modules.registry import get_module


class AnalysisView(APIView):
    """
    GET /api/analysis?module=<nombre>&race_id=<id>&driver=<code>&compound=<c>

    - module: requerido, nombre de un módulo registrado (ver registry.py)
    - race_id: requerido
    - driver, team, compound: opcionales, repetibles (?driver=VER&driver=HAM)
    """

    def get(self, request):
        module_name = request.GET.get("module")
        if not module_name:
            return Response(
                {"error": "El parámetro 'module' es requerido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        module = get_module(module_name)
        if not module:
            return Response(
                {"error": f"Módulo '{module_name}' no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        race_id = request.GET.get("race_id")
        if not race_id:
            return Response(
                {"error": "El parámetro 'race_id' es requerido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filters = {
            "race_id": race_id,
            "driver": request.GET.getlist("driver"),
            "team": request.GET.getlist("team"),
            "compound": request.GET.getlist("compound"),
        }

        try:
            result = module.run(filters)
        except Exception as exc:
            return Response(
                {"error": f"Error al ejecutar el módulo '{module_name}': {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(result)
