from datetime import date

import pytest

from bima_radar.pipeline import SAMPLES, BimaRadar

TODAY = date(2026, 5, 28)


@pytest.fixture
def radar() -> BimaRadar:
    r = BimaRadar(":memory:")
    r.scan(SAMPLES / "suresh")
    return r


@pytest.fixture
def by_type(radar):
    return {c.type: c for c in radar.covers()}
