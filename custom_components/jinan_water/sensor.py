"""
济南水务 Home Assistant 集成 - 传感器平台模块
"""

import logging

from homeassistant.components.sensor import (SensorEntity,SensorStateClass,SensorDeviceClass)
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SELECTED_GS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """传感器平台设置入口。"""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        _LOGGER.error("找不到协调器")
        return

    selected_gs = entry.data.get(CONF_SELECTED_GS, [])
    if not selected_gs:
        _LOGGER.warning("selected_gs 为空")
        return

    entities = []
    for gs in selected_gs:
        _LOGGER.info("为户号 %s 创建传感器实体", gs)
        entities.append(WaterBalanceSensor(coordinator, entry, gs))
        entities.append(WaterPriceSensor(coordinator, entry, gs))
        entities.append(WaterAddressSensor(coordinator, entry, gs))
        entities.append(WaterUserNameSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepPhoneSensor(coordinator, entry, gs))
        entities.append(WaterPendingFeeSensor(coordinator, entry, gs))
        entities.append(PenaltyFeeSensor(coordinator, entry, gs))
        entities.append(WaterUsageSensor(coordinator, entry, gs))
        entities.append(WaterCurrentFeeSensor(coordinator, entry, gs))
        entities.append(WaterMeterPrevSensor(coordinator, entry, gs))
        entities.append(WaterMeterCurrSensor(coordinator, entry, gs))
        entities.append(WaterMeterDateSensor(coordinator, entry, gs))
        entities.append(WaterPaymentDateSensor(coordinator, entry, gs))

    _LOGGER.info("创建了 %d 个传感器实体", len(entities))
    async_add_entities(entities)


class JinanWaterBaseSensor(CoordinatorEntity, SensorEntity):
    """济南水务传感器基类。"""

    _sensor_key = None

    def __init__(self, coordinator, entry, gs):
        self._gs = gs

        # 在 super().__init__() 之前设置 entity_id 和 unique_id
        object.__setattr__(self, 'entity_id', f"sensor.{DOMAIN}_{self._sensor_key}_{gs}")
        object.__setattr__(self, '_attr_unique_id', f"{DOMAIN}_{self._sensor_key}_{gs}")

        # 设置设备信息
        data = coordinator.data or {}
        gs_data = data.get(gs, {})
        mp = gs_data.get("mp", "")

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, gs)},
            "name": mp if mp else f"济南水务 - {gs}",
            "manufacturer": "济南水务集团",
            "model": f"户号: {gs}",
        }

        # 调用父类初始化
        super().__init__(coordinator)

    @property
    def gs_data(self):
        """获取当前户号的合并数据。"""
        data = self.coordinator.data or {}
        return data.get(self._gs, {})

    async def async_added_to_hass(self):
        """实体添加到 HA 时，注册监听器并写入初始状态。"""
        await super().async_added_to_hass()
        _LOGGER.info(
            "实体添加: %s, state=%s, available=%s",
            self.entity_id, self.state, self.available
        )
        self.async_write_ha_state()

    def _handle_coordinator_update(self):
        """处理协调器更新。"""
        _LOGGER.info(
            "协调器更新: %s, last_update_success=%s, state=%s, available=%s",
            self.entity_id, self.coordinator.last_update_success, self.state, self.available
        )
        super()._handle_coordinator_update()


# ============================================================
# 账户级传感器
# ============================================================

class WaterBalanceSensor(JinanWaterBaseSensor):
    _sensor_key = "balance"
    _attr_name = "水费余额"
    _attr_native_unit_of_measurement = "元"

    @property
    def native_value(self):
        return self.gs_data.get("yue")


class WaterPriceSensor(JinanWaterBaseSensor):
    _sensor_key = "price"
    _attr_name = "水价"
    _attr_native_unit_of_measurement = "元/m³"

    @property
    def native_value(self):
        return self.gs_data.get("dj")


class WaterAddressSensor(JinanWaterBaseSensor):
    _sensor_key = "address"
    _attr_name = "用水地址"

    @property
    def native_value(self):
        return self.gs_data.get("mp")


class WaterUserNameSensor(JinanWaterBaseSensor):
    _sensor_key = "username"
    _attr_name = "户名"

    @property
    def native_value(self):
        return self.gs_data.get("hm")


class WaterCustomerRepSensor(JinanWaterBaseSensor):
    _sensor_key = "customer_rep"
    _attr_name = "客户代表"

    @property
    def native_value(self):
        return self.gs_data.get("keHuDaiBiao")


class WaterCustomerRepPhoneSensor(JinanWaterBaseSensor):
    _sensor_key = "customer_rep_phone"
    _attr_name = "客户代表电话"

    @property
    def native_value(self):
        """返回客户代表电话（keHuDaiBiaoDH）。"""
        return self.gs_data.get("keHuDaiBiaoDH")


class WaterPendingFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "pending_fee"
    _attr_name = "欠费金额"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        return self.gs_data.get("qfje")


class PenaltyFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "penalty_fee"
    _attr_name = "违约金"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        return self.gs_data.get("wyj")


# ============================================================
# 账单级传感器
# ============================================================

class WaterUsageSensor(JinanWaterBaseSensor):
    _sensor_key = "usage"
    _attr_name = "本期用水量"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    @property
    def native_value(self):
        data = self.gs_data
        return data.get("xzsl", data.get("sl"))


class WaterCurrentFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "current_fee"
    _attr_name = "本期水费"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        data = self.gs_data
        return data.get("xzje", data.get("zje"))

    @property
    def extra_state_attributes(self):
        """返回详细费用信息。"""
        attrs = {}
        mx = self.gs_data.get("mx", [])

        for item in mx:
            name = item.get("xmmc", "")
            xmsl = item.get("xmsl")
            xmdj = item.get("xmdj")
            xmje = item.get("xmje")

            # 映射名称到属性前缀
            if "一阶基本水费" in name:
                prefix = "FirstStage"
            elif "水资源费" in name:
                prefix = "WaterResource"
            elif "污水处理费" in name:
                prefix = "WasteWater"
            else:
                continue

            if xmsl is not None:
                attrs[f"{prefix}Usage"] = xmsl
            if xmdj is not None:
                attrs[f"{prefix}UnitPrice"] = xmdj
            if xmje is not None:
                attrs[f"{prefix}Fee"] = xmje

        return attrs


class WaterMeterPrevSensor(JinanWaterBaseSensor):
    _sensor_key = "meter_prev"
    _attr_name = "上次表数"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        return self.gs_data.get("qd")


class WaterMeterCurrSensor(JinanWaterBaseSensor):
    _sensor_key = "meter_curr"
    _attr_name = "本次表数"
    _attr_icon = "mdi:speedometer-slow"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        return self.gs_data.get("zd")


class WaterMeterDateSensor(JinanWaterBaseSensor):
    _sensor_key = "meter_date"
    _attr_name = "抄表日期"

    @property
    def native_value(self):
        value = self.gs_data.get("r1")
        if not value:
            return None
        try:
            return value[:10]  # "2026-07-01"
        except (TypeError, ValueError, IndexError):
            return str(value) if value else None


class WaterPaymentDateSensor(JinanWaterBaseSensor):
    _sensor_key = "payment_date"
    _attr_name = "缴费时间"

    @property
    def native_value(self):
        value = self.gs_data.get("xzrq")
        if not value:
            return None
        try:
            return value[:19].replace("T", " ")  # "2026-07-22 17:49:12"
        except (TypeError, ValueError, IndexError):
            return str(value) if value else None
