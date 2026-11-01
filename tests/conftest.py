import pytest
from fastapi.testclient import TestClient

from opal_look.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c
