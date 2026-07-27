import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "ai-service" / "ai_service.py"
SPEC = importlib.util.spec_from_file_location("ai_service", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ai_service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ai_service)


class FakeCursor:
    def __init__(self, fetch_results):
        self.fetch_results = list(fetch_results)
        self.executed_sql = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed_sql.append((sql, params))

    def fetchone(self):
        return self.fetch_results.pop(0)


class FakeConnection:
    def __init__(self, fetch_results):
        self.cursor_instance = FakeCursor(fetch_results)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_anomaly_score_is_capped_at_one():
    assert ai_service.detect_anomaly(60.0, 0.95) == 1.0


def test_normal_telemetry_does_not_create_incident():
    connection = FakeConnection([(10, "node-01", 1000, 42.0, 0.2)])

    result = ai_service.process_latest_event(lambda: connection)

    assert result == "normal"
    assert connection.closed is True
    assert len(connection.cursor_instance.executed_sql) == 1


def test_high_risk_event_creates_one_incident():
    connection = FakeConnection(
        [
            (10, "node-01", 1000, 60.0, 0.95),
            (501,),
        ]
    )

    result = ai_service.process_latest_event(lambda: connection)

    assert result == "incident_created"
    assert connection.closed is True
    insert_sql = connection.cursor_instance.executed_sql[1][0]
    assert "ON CONFLICT (telemetry_event_id) DO NOTHING" in insert_sql


def test_replayed_high_risk_event_does_not_create_second_incident():
    connection = FakeConnection(
        [
            (10, "node-01", 1000, 60.0, 0.95),
            None,
        ]
    )

    result = ai_service.process_latest_event(lambda: connection)

    assert result == "duplicate_incident"
    assert connection.closed is True
