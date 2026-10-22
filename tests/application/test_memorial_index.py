from desktop_calendar.core.memorial import build_memorial_index


def test_build_index_buckets():
    idx = build_memorial_index([
        {"name": "A", "type": "solar", "month": 1, "day": 1,
         "repeat_type": "year", "enabled": True},
        {"name": "B", "type": "solar", "day": 15,
         "repeat_type": "month", "enabled": True},
        {"name": "C", "type": "solar", "day": 3,
         "repeat_type": "week", "enabled": True},
        {"name": "D", "type": "lunar", "month": 8, "day": 15,
         "repeat_type": "year", "enabled": True},
    ])
    assert len(idx["solar_year"][(1, 1)]) == 1
    assert len(idx["solar_month"][15]) == 1
    assert len(idx["solar_week"][3]) == 1
    assert len(idx["lunar_year"][(8, 15, False)]) == 1