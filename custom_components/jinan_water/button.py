"""济南水务 Home Assistant 集成 - 按钮实体模块"""

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SELECTED_GS
from .helpers import build_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """按钮平台设置入口。"""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    selected_gs = entry.data.get(CONF_SELECTED_GS, [])

    entities = []
    for gs in selected_gs:
        entities.append(JinanWaterRefreshButton(coordinator, entry, gs))

    async_add_entities(entities)


class JinanWaterRefreshButton(CoordinatorEntity, ButtonEntity):
    """济南水务手动刷新按钮。"""

    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False

    def __init__(self, coordinator, entry, gs):
        self._gs = gs

        # 在 super().__init__() 之前设置 entity_id 和 unique_id
        object.__setattr__(self, 'entity_id', f"button.{DOMAIN}_refresh_{gs}")
        object.__setattr__(self, '_attr_unique_id', f"{DOMAIN}_refresh_{gs}")
        object.__setattr__(self, '_attr_name', f"刷新数据")

        # 设置设备信息（与 sensor.py 共用同一份构造逻辑）
        data = coordinator.data or {}
        self._attr_device_info = build_device_info(entry, gs, data)

        # 调用父类初始化
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        """按钮始终可用。"""
        return True

    async def async_press(self) -> None:
        """处理按钮按下事件。"""
        _LOGGER.info("按钮按下，开始刷新数据")
        try:
            await self.coordinator.async_refresh()
            _LOGGER.info("按钮触发的刷新已完成")
        except Exception as err:
            _LOGGER.error("按钮触发的刷新失败: %s", err)
