import threading
import uuid

import pytest

from neurostate.acquisition.mock_source import run_mock
from neurostate.config import MockConfig


@pytest.fixture
def start_mock():
    """Start mock EEG streams in background threads, each with a unique name."""
    running = []

    def start(**settings) -> MockConfig:
        config = MockConfig(stream_name=f"neurostate-test-{uuid.uuid4().hex[:8]}", **settings)
        stop = threading.Event()
        thread = threading.Thread(
            target=run_mock, args=(config,), kwargs={"stop": stop}, daemon=True
        )
        thread.start()
        running.append((stop, thread))
        return config

    yield start
    for stop, thread in running:
        stop.set()
        thread.join(timeout=5)
