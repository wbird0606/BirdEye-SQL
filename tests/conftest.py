import pytest
import os
from birdeye.runner import BirdEyeRunner


@pytest.fixture(scope="session")
def global_runner():
    """
    全域 Runner Fixture。
    在測試 Session 開始時初始化一次，並載入真實元數據。
    """
    runner = BirdEyeRunner()
    csv_path = os.path.join("data", "output.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            runner.load_metadata_from_csv(f)
    return runner


@pytest.fixture
def flask_client():
    from web.app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
