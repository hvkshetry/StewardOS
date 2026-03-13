"""Shared test infrastructure for plane-mcp tests."""

import os
import sys
from pathlib import Path
from typing import Any
import pytest

# Add server source to path for imports
server_src = str(Path(__file__).resolve().parents[1] / "src")
if server_src not in sys.path:
    sys.path.insert(0, server_src)

# Add repo root for test_support
repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Set governance env vars before any imports
os.environ["PLANE_HOME_WORKSPACE"] = "test-workspace"
os.environ["PLANE_BASE_URL"] = "http://test:8082"
os.environ["PLANE_API_TOKEN"] = "test-token"

from test_support.mcp import FakeMCP


# ---------------------------------------------------------------------------
# Mock Plane client
# ---------------------------------------------------------------------------

class _MockNamespace:
    """A mock namespace that records calls and returns canned data.

    Supports both explicitly defined methods (list, create, retrieve, update)
    and dynamic method calls via __getattr__ for SDK methods like search(),
    add_work_items(), get_members(), etc.

    Sub-namespaces (e.g., work_items.comments) can be set as attributes
    after construction and will be found via normal attribute lookup.
    """

    def __init__(self, canned: dict[str, Any] | None = None):
        self._canned = canned or {}
        self._calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, method: str, **kwargs: Any) -> Any:
        self._calls.append((method, kwargs))
        return self._canned.get(method, {})

    def list(self, **kwargs: Any) -> Any:
        return self._record("list", **kwargs)

    def create(self, **kwargs: Any) -> Any:
        return self._record("create", **kwargs)

    def retrieve(self, **kwargs: Any) -> Any:
        return self._record("retrieve", **kwargs)

    def update(self, **kwargs: Any) -> Any:
        return self._record("update", **kwargs)

    def set_canned(self, method: str, value: Any) -> None:
        self._canned[method] = value

    def __getattr__(self, name: str) -> Any:
        # Only triggered when normal attribute lookup fails.
        # Covers SDK methods not explicitly defined above (search,
        # add_work_items, remove_work_item, get_members, archive, etc.)
        if name.startswith("_"):
            raise AttributeError(name)

        def dynamic_method(**kwargs: Any) -> Any:
            return self._record(name, **kwargs)

        return dynamic_method


class MockPlaneClient:
    """Mock PlaneClient that returns canned responses for testing."""

    def __init__(self):
        self.workspaces = _MockNamespace()
        self.projects = _MockNamespace()
        self.work_items = _MockNamespace()
        self.states = _MockNamespace()
        self.labels = _MockNamespace()
        self.cycles = _MockNamespace()
        self.modules = _MockNamespace()
        self.pages = _MockNamespace()
        self.intake = _MockNamespace()

        # Work item sub-resources
        self.work_items.comments = _MockNamespace()
        self.work_items.links = _MockNamespace()
        self.work_items.attachments = _MockNamespace()
        self.work_items.activities = _MockNamespace()

    def configure_workspaces(self, data: Any) -> None:
        self.workspaces.set_canned("list", data)

    def configure_projects(
        self,
        list_data: Any = None,
        create_data: Any = None,
        retrieve_data: Any = None,
    ) -> None:
        if list_data is not None:
            self.projects.set_canned("list", list_data)
        if create_data is not None:
            self.projects.set_canned("create", create_data)
        if retrieve_data is not None:
            self.projects.set_canned("retrieve", retrieve_data)

    def configure_work_items(
        self,
        list_data: Any = None,
        create_data: Any = None,
        retrieve_data: Any = None,
        update_data: Any = None,
    ) -> None:
        if list_data is not None:
            self.work_items.set_canned("list", list_data)
        if create_data is not None:
            self.work_items.set_canned("create", create_data)
        if retrieve_data is not None:
            self.work_items.set_canned("retrieve", retrieve_data)
        if update_data is not None:
            self.work_items.set_canned("update", update_data)

    def configure_states(self, list_data: Any = None) -> None:
        if list_data is not None:
            self.states.set_canned("list", list_data)

    def configure_labels(
        self,
        list_data: Any = None,
        create_data: Any = None,
    ) -> None:
        if list_data is not None:
            self.labels.set_canned("list", list_data)
        if create_data is not None:
            self.labels.set_canned("create", create_data)

    def configure_cycles(
        self,
        list_data: Any = None,
        create_data: Any = None,
        retrieve_data: Any = None,
    ) -> None:
        if list_data is not None:
            self.cycles.set_canned("list", list_data)
        if create_data is not None:
            self.cycles.set_canned("create", create_data)
        if retrieve_data is not None:
            self.cycles.set_canned("retrieve", retrieve_data)

    def configure_modules(
        self,
        list_data: Any = None,
        create_data: Any = None,
    ) -> None:
        if list_data is not None:
            self.modules.set_canned("list", list_data)
        if create_data is not None:
            self.modules.set_canned("create", create_data)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_mcp():
    return FakeMCP()


@pytest.fixture
def mock_client():
    return MockPlaneClient()


@pytest.fixture
def get_client(mock_client):
    def _get_client():
        return mock_client
    return _get_client
