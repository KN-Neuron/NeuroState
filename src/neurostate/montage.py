"""Montages: which of a cap's channels are EEG, and which brain region each one covers.

Built-in montages live in ``src/neurostate/montages/``. Labels are matched case-insensitively,
since caps differ in how they write them (FP1, Fp1).
"""

from importlib import resources
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

Region = Literal["frontal", "parietal", "occipital"]
REGIONS: tuple[Region, ...] = ("frontal", "parietal", "occipital")


class Regions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontal: list[str] = []
    parietal: list[str] = []
    occipital: list[str] = []


class Montage(BaseModel):
    """A cap's channel layout.

    ``channels`` lists every EEG channel on the cap; the stream's other channels are ignored.
    Leave it out to rely on the channel types the stream reports instead.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    channels: list[str] | None = None
    regions: Regions

    @model_validator(mode="after")
    def _regions_use_known_channels(self) -> Self:
        if self.channels is not None:
            known = {label.lower() for label in self.channels}
            unknown = [
                label
                for region in REGIONS
                for label in getattr(self.regions, region)
                if label.lower() not in known
            ]
            if unknown:
                raise ValueError(f"region channels missing from channels: {', '.join(unknown)}")
        return self

    def region_indices(self, labels: list[str]) -> dict[Region, list[int]]:
        """For each region, the positions in ``labels`` of the channels that cover it."""
        positions = {label.lower(): i for i, label in enumerate(labels)}
        return {
            region: [
                positions[label.lower()]
                for label in getattr(self.regions, region)
                if label.lower() in positions
            ]
            for region in REGIONS
        }


def builtin_montages() -> list[str]:
    folder = resources.files("neurostate") / "montages"
    return sorted(
        item.name.removesuffix(".yaml") for item in folder.iterdir() if item.name.endswith(".yaml")
    )


def load_montage(name_or_path: str) -> Montage:
    """Load a built-in montage by name, or a montage file by path (ending in .yaml or .yml).

    Raises ``ValueError`` for an unknown name, ``OSError`` for an unreadable file,
    ``yaml.YAMLError`` for invalid YAML and ``pydantic.ValidationError`` for wrong contents.
    """
    if Path(name_or_path).suffix in {".yaml", ".yml"}:
        text = Path(name_or_path).read_text(encoding="utf-8")
    elif name_or_path in builtin_montages():
        montage_file = resources.files("neurostate") / "montages" / f"{name_or_path}.yaml"
        text = montage_file.read_text(encoding="utf-8")
    else:
        raise ValueError(
            f"unknown montage '{name_or_path}': use a .yaml file path or one of "
            f"{', '.join(builtin_montages())}"
        )
    return Montage.model_validate(yaml.safe_load(text))
