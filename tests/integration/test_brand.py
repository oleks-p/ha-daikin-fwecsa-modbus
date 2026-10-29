"""The integration's icon: shipped with it, found by Home Assistant's brands view."""

from __future__ import annotations

import struct
from pathlib import Path

from homeassistant.loader import async_get_integration

from custom_components.daikin_fwecsa_modbus.const import DOMAIN

BRAND = Path(__file__).parents[2] / "custom_components" / DOMAIN / "brand"


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:26]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    assert head[25] == 6, f"{path.name} is not RGBA: the background must be transparent"
    return struct.unpack(">II", head[16:24])


def test_both_icon_sizes_ship():
    # Home Assistant's brand sizes: 256 px, and 512 px for high-density screens.
    assert _png_size(BRAND / "icon.png") == (256, 256)
    assert _png_size(BRAND / "icon@2x.png") == (512, 512)


async def test_home_assistant_finds_the_icon(hass):
    # Without this, the integrations page, Repairs and HACS show "icon not available".
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.has_branding
