"""Small wrapper around the Invoice Intake API. Adds the login token to every call."""

import os
from typing import Any

import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TIMEOUT = 30


class ApiError(Exception):
    def __init__(self, status: int, detail: Any) -> None:
        self.status = status
        self.detail = detail
        super().__init__(self.message)

    @property
    def message(self) -> str:
        d = self.detail
        if isinstance(d, dict):
            return d.get("message") or str(d)
        if isinstance(d, list):  # FastAPI validation errors
            return "; ".join(e.get("msg", str(e)) for e in d)
        return str(d)

    @property
    def reasons(self) -> list[str]:
        return self.detail.get("reasons", []) if isinstance(self.detail, dict) else []


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            r = requests.request(
                method, f"{self.base_url}{path}", headers=headers, timeout=TIMEOUT, **kwargs
            )
        except requests.RequestException as exc:
            raise ApiError(0, f"Cannot reach the server ({type(exc).__name__})") from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ApiError(r.status_code, detail)
        return r

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, path, **kwargs).json()

    # auth
    def login(self, email: str, password: str) -> dict[str, Any]:
        data = self._json("POST", "/auth/login", json={"email": email, "password": password})
        self.token = data["token"]
        return data

    # documents
    def upload(self, files: list[tuple[str, bytes, str]]) -> list[dict[str, Any]]:
        payload = [("files", (name, data, mime)) for name, data, mime in files]
        return self._json("POST", "/documents", files=payload)

    def list_documents(self, **params: Any) -> list[dict[str, Any]]:
        return self._json("GET", "/documents", params={k: v for k, v in params.items() if v})

    def get_document(self, document_id: str) -> dict[str, Any]:
        return self._json("GET", f"/documents/{document_id}")

    def page_image(self, document_id: str, page: int) -> bytes:
        return self._request("GET", f"/documents/{document_id}/pages/{page}").content

    def retry(self, document_id: str) -> dict[str, Any]:
        return self._json("POST", f"/documents/{document_id}/retry")

    # review
    def queue(self) -> list[dict[str, Any]]:
        return self._json("GET", "/review/queue")

    def correct(
        self, document_id: str, changes: list[dict[str, Any]], delete_lines: list[int]
    ) -> dict[str, Any]:
        body = {"changes": changes, "delete_lines": delete_lines}
        return self._json("PATCH", f"/review/{document_id}/fields", json=body)

    def approve(self, document_id: str, note: str | None = None) -> dict[str, Any]:
        return self._json("POST", f"/review/{document_id}/approve", json={"note": note})

    def reject(self, document_id: str, reason: str) -> dict[str, Any]:
        return self._json("POST", f"/review/{document_id}/reject", json={"reason": reason})

    # manager
    def dashboard(self) -> dict[str, Any]:
        return self._json("GET", "/dashboard/metrics")

    def get_settings(self) -> dict[str, Any]:
        return self._json("GET", "/settings")

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        return self._json("PUT", "/settings", json=changes)

    def vendors(self) -> list[dict[str, Any]]:
        return self._json("GET", "/vendors")

    def create_vendor(self, vendor: dict[str, Any]) -> dict[str, Any]:
        return self._json("POST", "/vendors", json=vendor)

    def update_vendor(self, vendor_id: str, vendor: dict[str, Any]) -> dict[str, Any]:
        return self._json("PUT", f"/vendors/{vendor_id}", json=vendor)
