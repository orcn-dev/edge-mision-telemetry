import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "ingest-api" / "app.py"
SPEC = importlib.util.spec_from_file_location("ingest_app", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ingest_app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest_app)


class FakeCursor:
    def __init__(self, fetch_result):
        self.fetch_result = fetch_result
        self.executed_sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.executed_sql = sql
        self.params = params

    def fetchone(self):
        return self.fetch_result


class FakeConnection:
    def __init__(self, fetch_result):
        self.cursor_instance = FakeCursor(fetch_result)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def sample_payload():
    return {
        "device_id": "node-01",
        "seq": 42,
        "ts": 1772490151,
        "temp": 57.7,
        "vibration": 0.635,
    }


def test_first_packet_is_inserted():
    connection = FakeConnection((101,))

    result = ingest_app.insert_event(sample_payload(), lambda: connection)

    assert result == "inserted"
    assert connection.closed is True
    assert "ON CONFLICT (device_id, seq) DO NOTHING" in connection.cursor_instance.executed_sql
    assert connection.cursor_instance.params[0:2] == ("node-01", 42)


def test_duplicate_packet_is_not_inserted_again():
    connection = FakeConnection(None)

    result = ingest_app.insert_event(sample_payload(), lambda: connection)

    assert result == "duplicate"
    assert connection.closed is True
