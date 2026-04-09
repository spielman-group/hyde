from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Option:
    value: Any
    label: str


@dataclass
class Feature:
    name: str
    type: type
    default: Any = None
    options: list[Option] = field(default_factory=list)
    range: tuple | None = None
    label: str = ""
    group: str = ""
    tab: str = ""
    command_key: str = ""
    command_format: str = "{}"


class FeatureRegistry:
    features: dict[str, Feature] = {}

    @classmethod
    def get(cls, name: str) -> Feature | None:
        return cls.features.get(name)

    @classmethod
    def get_by_group(cls, group: str) -> list[Feature]:
        return [f for f in cls.features.values() if f.group == group]

    @classmethod
    def get_by_tab(cls, tab: str) -> list[Feature]:
        return [f for f in cls.features.values() if f.tab == tab]

    @classmethod
    def register(cls, feature: Feature):
        cls.features[feature.name] = feature

    @classmethod
    def build_command(cls, **kwargs) -> str:
        parts = []
        for name, value in kwargs.items():
            if value is None:
                continue
            feature = cls.features.get(name)
            if feature and feature.command_key:
                key = feature.command_key
            else:
                key = name
            if feature and feature.command_format and feature.command_format != "{}":
                parts.append(f"{key}={feature.command_format.format(value)!r}")
            else:
                parts.append(f"{key}={value!r}")
        return ", ".join(parts)


class FeatureDialogMixin:
    """Mixin for dialogs to build commands from feature registry."""

    registry: type[FeatureRegistry]

    @classmethod
    def build_command(cls, figure_id: str, **kwargs) -> str:
        cmd_parts = cls.registry.build_command(**kwargs)
        return f"edit_figure({figure_id!r}, {cmd_parts})"

    @classmethod
    def get_feature_options(cls, feature_name: str) -> list[Option]:
        feature = cls.registry.get(feature_name)
        return feature.options if feature else []


def register_all_features():
    from hyde.features.matplotlib_features import MatplotlibFeatures
    from hyde.features.lmfit_features import LmfitFeatures

    MatplotlibFeatures.register_all()
    LmfitFeatures.register_all()


# Import feature classes for convenience
from hyde.features.matplotlib_features import MatplotlibFeatures
from hyde.features.lmfit_features import LmfitFeatures