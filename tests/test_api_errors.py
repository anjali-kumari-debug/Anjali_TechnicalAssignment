"""API error handling: status codes, JSON bodies, no tracebacks (Part 8)."""


def test_malformed_json_is_400(make, client_for):
    response = client_for(make.user()).post("/api/orders", data="{not json", content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["error"]["message"] == "The request body is not valid JSON."


def test_wrong_content_type_is_415(make, client_for):
    response = client_for(make.user()).post("/api/orders", data={"customer_id": "1"})
    assert response.status_code == 415
    assert response.is_json


def test_non_object_body_is_400(make, client_for):
    response = client_for(make.user()).post("/api/orders", json=[1, 2, 3])
    assert response.status_code == 400


def test_unknown_route_and_wrong_method(make, client_for):
    client = client_for(make.user())
    assert client.get("/api/does-not-exist").status_code == 404
    response = client.delete("/api/orders/1")
    assert response.status_code == 405 and response.is_json


def test_internal_errors_do_not_leak_details(app, make, client_for, monkeypatch):
    from app.services import orders

    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(orders, "create_draft", explode)
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    response = client_for(make.user()).post("/api/orders", json={})
    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "secret" not in body and "Traceback" not in body
    assert response.get_json()["error"]["code"] == "INTERNAL_ERROR"


def test_csrf_token_required_for_state_changes(app, make, client_for, monkeypatch):
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    response = client_for(make.user()).post("/api/orders", json={"customer_id": 1, "items": []})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CSRF_FAILED"
