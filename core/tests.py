from django.db import IntegrityError
from django.test import TestCase

from core.models import Driver, Lap, Race, Team


class LapUniquenessTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Red Bull")
        self.driver = Driver.objects.create(code="VER", name="Max Verstappen", team=self.team)
        self.race = Race.objects.create(
            year=2026, round_number=13, gp_name="Hungarian Grand Prix", session_type=Race.SESSION_RACE
        )

    def test_lap_str(self):
        lap = Lap.objects.create(driver=self.driver, race=self.race, lap_number=1, lap_time=80.5)
        self.assertIn("VER", str(lap))

    def test_duplicate_lap_is_rejected(self):
        Lap.objects.create(driver=self.driver, race=self.race, lap_number=1, lap_time=80.5)
        with self.assertRaises(IntegrityError):
            Lap.objects.create(driver=self.driver, race=self.race, lap_number=1, lap_time=81.0)
