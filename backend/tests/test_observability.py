from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability.metrics import configure_metrics, frames_processed_total
from app.observability.middleware import REQUEST_ID_HEADER, RequestContextMiddleware


def _build_app():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise ValueError("something broke")

    return app


def test_request_id_is_generated_and_echoed_back():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.get("/ping")
    assert response.status_code == 200
    assert REQUEST_ID_HEADER in response.headers
    assert len(response.headers[REQUEST_ID_HEADER]) > 0


def test_incoming_request_id_is_reused_not_replaced():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.get("/ping", headers={REQUEST_ID_HEADER: "caller-supplied-id-123"})
    assert response.headers[REQUEST_ID_HEADER] == "caller-supplied-id-123"


def test_different_requests_get_different_ids():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    r1 = client.get("/ping")
    r2 = client.get("/ping")
    assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]


def test_middleware_logs_and_reraises_on_exception():
    client = TestClient(_build_app(), raise_server_exceptions=False)
    response = client.get("/boom")
    # No exception handler registered in this minimal app -- Starlette's
    # default converts the unhandled error to a 500; the important thing
    # is the middleware didn't swallow it or crash itself.
    assert response.status_code == 500


def test_metrics_endpoint_exposes_custom_counters():
    app = FastAPI()
    configure_metrics(app, enabled=True)

    frames_processed_total.labels(scene_id="test-scene-metrics").inc(3)

    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "continuity_agent_frames_processed_total" in response.text
    assert "http_requests_total" in response.text or "http_request_duration" in response.text


def test_metrics_endpoint_absent_when_disabled():
    app = FastAPI()
    configure_metrics(app, enabled=False)

    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 404


def test_readiness_reports_ok_when_clickhouse_reachable(mocker):
    import app.main as m

    mock_client = mocker.Mock()
    mocker.patch("app.main.get_clickhouse_client", return_value=mock_client)

    client = TestClient(m.app)
    response = client.get("/api/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["clickhouse"] == "ok"
    mock_client.ping.assert_called_once()


def test_readiness_reports_degraded_when_clickhouse_unreachable(mocker):
    import app.main as m

    mocker.patch("app.main.get_clickhouse_client", side_effect=ConnectionError("no route to host"))

    client = TestClient(m.app)
    response = client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "no route to host" in body["checks"]["clickhouse"]


def test_liveness_never_touches_clickhouse(mocker):
    import app.main as m

    mock_get_client = mocker.patch("app.main.get_clickhouse_client")
    client = TestClient(m.app)

    response = client.get("/api/health/live")

    assert response.status_code == 200
    mock_get_client.assert_not_called()
