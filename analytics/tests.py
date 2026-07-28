from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Driver, Lap, Race, Team


class AnalysisViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.team = Team.objects.create(name="Red Bull")
        self.driver = Driver.objects.create(code="VER", name="Max Verstappen", team=self.team)
        self.race = Race.objects.create(
            year=2026, round_number=13, gp_name="Hungarian Grand Prix", session_type=Race.SESSION_RACE
        )

        for i in range(1, 6):
            Lap.objects.create(
                driver=self.driver, race=self.race,
                lap_number=i, lap_time=80 + i * 0.1, compound="MEDIUM",
            )

    def test_missing_module_returns_400(self):
        response = self.client.get(reverse("analysis"), {"race_id": self.race.id})
        self.assertEqual(response.status_code, 400)

    def test_unknown_module_returns_404(self):
        response = self.client.get(
            reverse("analysis"), {"module": "no_existe", "race_id": self.race.id}
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_race_id_returns_400(self):
        response = self.client.get(reverse("analysis"), {"module": "pace_by_stint"})
        self.assertEqual(response.status_code, 400)

    def test_pace_by_stint_returns_data(self):
        response = self.client.get(
            reverse("analysis"),
            {"module": "pace_by_stint", "race_id": self.race.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["module"], "pace_by_stint")
