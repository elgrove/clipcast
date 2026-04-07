from app.services.editor import parse_time_to_ms


def test_parse_time_to_ms_hhmmss():
    assert parse_time_to_ms("1:30:00") == 5400000


def test_parse_time_to_ms_mmss():
    assert parse_time_to_ms("2:30") == 150000


def test_parse_time_to_ms_seconds():
    assert parse_time_to_ms("90.5") == 90500


def test_parse_time_to_ms_integer():
    assert parse_time_to_ms("60") == 60000
