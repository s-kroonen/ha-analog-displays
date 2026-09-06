"""The integration's services.

Everything is addressed by device, because a preset is a device-level scene.
``export_yaml`` is a response service so it can be run straight from Developer
Tools and the YAML read off the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_EXPORT_YAML,
    SERVICE_NEXT_PRESET,
    SERVICE_PREVIOUS_PRESET,
    SERVICE_REFRESH,
    SERVICE_SET_PRESET,
)

if TYPE_CHECKING:
    from .controller import DeviceRuntime

ATTR_PRESET = "preset"

_DEVICE_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string})
_SET_PRESET_SCHEMA = _DEVICE_SCHEMA.extend(
    {vol.Required(ATTR_PRESET): vol.Any(cv.positive_int, cv.string)}
)


def _runtime(hass: HomeAssistant, device_id: str) -> DeviceRuntime:
    """Resolve a device id to a loaded runtime, or explain why it cannot be."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_device",
            translation_placeholders={"device_id": device_id},
        )

    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                    translation_placeholders={"device_id": device_id},
                )
            runtime: DeviceRuntime = entry.runtime_data
            return runtime

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_device",
        translation_placeholders={"device_id": device_id},
    )


def _resolve_preset(runtime: DeviceRuntime, preset: Any) -> int:
    """Turn a preset index or label into an index."""
    labels = [item.label for item in runtime.device.presets]

    if isinstance(preset, int):
        index = preset
    elif preset in labels:
        index = labels.index(preset)
    elif str(preset).isdigit():
        index = int(preset)
    else:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_preset",
            translation_placeholders={"preset": str(preset)},
        )

    if not 0 <= index < len(labels):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_preset",
            translation_placeholders={"preset": str(preset)},
        )
    return index


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register every service, once, for the whole integration."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_PRESET):
        return

    async def set_preset(call: ServiceCall) -> None:
        """Switch a device to a preset by index or label."""
        runtime = _runtime(hass, call.data[ATTR_DEVICE_ID])
        await runtime.async_set_preset(_resolve_preset(runtime, call.data[ATTR_PRESET]))

    async def next_preset(call: ServiceCall) -> None:
        """Advance a device to its next preset, wrapping around."""
        runtime = _runtime(hass, call.data[ATTR_DEVICE_ID])
        await runtime.async_set_preset(runtime.active_preset_index + 1)

    async def previous_preset(call: ServiceCall) -> None:
        """Step a device back to its previous preset, wrapping around."""
        runtime = _runtime(hass, call.data[ATTR_DEVICE_ID])
        await runtime.async_set_preset(runtime.active_preset_index - 1)

    async def refresh(call: ServiceCall) -> None:
        """Force a device to re-read its sources and rewrite its displays."""
        runtime = _runtime(hass, call.data[ATTR_DEVICE_ID])
        if runtime.coordinator is not None:
            await runtime.coordinator.async_refresh()
        await runtime.async_refresh()

    async def export_yaml(call: ServiceCall) -> ServiceResponse:
        """Regenerate the ESPHome YAML for a device set up with the wizard."""
        from .wizard import request_from_profile  # noqa: PLC0415
        from .yaml_gen import generate_yaml  # noqa: PLC0415

        runtime = _runtime(hass, call.data[ATTR_DEVICE_ID])
        profile = runtime.device.hardware_profile
        if profile is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_hardware_profile",
                translation_placeholders={"device": runtime.device.name},
            )

        return {"yaml": generate_yaml(request_from_profile(runtime.device, profile))}

    hass.services.async_register(
        DOMAIN, SERVICE_SET_PRESET, set_preset, schema=_SET_PRESET_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_NEXT_PRESET, next_preset, schema=_DEVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PREVIOUS_PRESET, previous_preset, schema=_DEVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, refresh, schema=_DEVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_YAML,
        export_yaml,
        schema=_DEVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
