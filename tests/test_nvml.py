from __future__ import annotations

from constella.nvml import architecture_label


def test_architecture_label_maps_known_nvml_values() -> None:
    assert architecture_label(9) == "Hopper"
    assert architecture_label(10) == "Blackwell"
    assert architecture_label(0xFFFFFFFF) is None
