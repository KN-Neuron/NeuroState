"""Outputs: the ways apps can receive the published values."""

from typing import Protocol

from neurostate.schema import BrainState


class Output(Protocol):
    key: str  # its section under ``outputs`` in the config

    @property
    def description(self) -> str:
        """Where apps can find it, for the startup message. Complete once started."""
        ...

    async def start(self) -> None: ...

    def publish(self, state: BrainState) -> None:
        """Pass on one update. Must not block: it runs on the service's event loop."""
        ...

    async def close(self) -> None: ...
