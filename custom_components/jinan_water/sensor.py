"""
济南水务 Home Assistant 集成 - 传感器平台模块

本模块定义了所有传感器实体，负责：
1. 从协调器（Coordinator）中读取数据并展示为传感器
2. 配置实体的属性（名称、单位、设备类、图标等）
3. 通过 CoordinatorEntity 实现数据的自动更新与同步

=== 数据来源 ===

传感器数据来自两个 API 的合并结果（见 __init__.py 中的协调器）：

GetBangDingList（账户级数据）：
  - yue (余额), hm (户名), mp (地址)
  - keHuDaiBiao (客户代表), keHuDaiBiaoDH (客户代表电话)
  - qfje (欠费金额), wyj (违约金), dj (水价)

GetFaPiaoList（账单级数据）：
  - xzsl/sl (本期用量), xzje/zje (本期水费)
  - qd (上次表数), zd (本次表数)
  - r1 (抄表日期), xzrq (缴费时间)
  - mx (费用明细)
"""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SELECTED_GS


def _format_date(value):
    """
    将 ISO 8601 日期字符串格式化为 YYYY-MM-DD。

    输入: "2026-07-01T00:00:00" → 输出: "2026-07-01"

    :param value: ISO 日期字符串
    :return: 格式化后的日期字符串，失败时返回原始值
    """
    if not value:
        return None
    try:
        return value[:10]
    except (TypeError, IndexError):
        return value


def _format_datetime(value):
    """
    将 ISO 8601 日期时间字符串格式化为 YYYY-MM-DD HH:MM:SS。

    输入: "2026-07-22T17:49:12.5" → 输出: "2026-07-22 17:49:12"

    :param value: ISO 日期时间字符串
    :return: 格式化后的日期时间字符串，失败时返回原始值
    """
    if not value:
        return None
    try:
        return value[:19].replace("T", " ")
    except (TypeError, IndexError):
        return value


async def async_setup_entry(hass, entry, async_add_entities):
    """
    传感器平台设置入口。

    当 __init__.py 调用 async_forward_entry_setups 时，HA 会调用此方法。
    负责根据用户选择的户号创建所有传感器实体。

    :param hass: HomeAssistant 实例
    :param entry: ConfigEntry，包含用户配置数据
    :param async_add_entities: 回调函数，用于向 HA 注册实体
    """
    coordinator = hass.data[DOMAIN][entry.entry_id]
    selected_gs = entry.data.get(CONF_SELECTED_GS, [])

    entities = []
    for gs in selected_gs:
        # --- 账户级传感器（来自 GetBangDingList）---
        entities.append(WaterBalanceSensor(coordinator, entry, gs))
        entities.append(WaterPriceSensor(coordinator, entry, gs))
        entities.append(WaterAddressSensor(coordinator, entry, gs))
        entities.append(WaterUserNameSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepPhoneSensor(coordinator, entry, gs))
        entities.append(WaterPendingFeeSensor(coordinator, entry, gs))
        entities.append(PenaltyFeeSensor(coordinator, entry, gs))

        # --- 账单级传感器（来自 GetFaPiaoList）---
        entities.append(WaterUsageSensor(coordinator, entry, gs))
        entities.append(WaterCurrentFeeSensor(coordinator, entry, gs))
        entities.append(WaterMeterPrevSensor(coordinator, entry, gs))
        entities.append(WaterMeterCurrSensor(coordinator, entry, gs))
        entities.append(WaterMeterDateSensor(coordinator, entry, gs))
        entities.append(WaterPaymentDateSensor(coordinator, entry, gs))

    async_add_entities(entities)


class JinanWaterBaseSensor(CoordinatorEntity, SensorEntity):
    """
    济南水务传感器基类。

    所有具体传感器都继承此类，只需定义 _sensor_key、_attr_name 和 native_value 即可。

    === 继承 CoordinatorEntity 的作用 ===

    CoordinatorEntity 提供了自动数据更新机制：
      - 当 coordinator.data 更新后，会自动通知实体
      - 实体调用 async_write_ha_state() 刷新前端显示
      - 无需手动实现 polling 逻辑

    === _attr_ 前缀属性的作用 ===

    HA 中以 _attr_ 开头的类属性是"实体属性"的快捷设置方式。
    设置 _attr_name = "水费余额" 等同于在 __init__ 中 self._attr_name = "水费余额"。
    """

    _sensor_key = None

    def __init__(self, coordinator, entry, gs):
        """
        初始化传感器。

        :param coordinator: 数据更新协调器
        :param entry: ConfigEntry
        :param gs: 户号
        """
        self._entry = entry
        self._gs = gs

        super().__init__(coordinator)

        # 直接设置 entity_id 来控制实体标识符
        # 格式: sensor.域名_传感器类型_户号
        self.entity_id = f"sensor.{DOMAIN}_{self._sensor_key}_{gs}"
        self._attr_unique_id = f"{self._sensor_key}_{gs}"
        # self._attr_name 保持类定义中的原始值不变

        # 从协调器数据中获取用水地址作为设备名称
        data = getattr(coordinator, 'data', {}) or {}
        mp = data.get(gs, {}).get("mp", "")

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, gs)},
            "name": mp if mp else f"济南水务 - {gs}",
            "manufacturer": "济南水务集团",
            "model": f"户号: {gs}",
            "via_device": (DOMAIN, entry.entry_id),
        }

    @property
    def gs_data(self):
        """
        获取当前户号的合并数据（两个 API 的数据已合并）。

        :return: 当前户号的数据字典
        """
        data = getattr(self.coordinator, 'data', {}) or {}
        return data.get(self._gs, {})

    @property
    def available(self):
        """
        实体是否可用。

        :return: True 表示可用（户号数据存在且协调器可用）
        """
        data = getattr(self.coordinator, 'data', {}) or {}
        return super().available and self._gs in data


# ============================================================
# 账户级传感器（数据来自 GetBangDingList）
# ============================================================

class WaterBalanceSensor(JinanWaterBaseSensor):
    """水费余额传感器（账户级）。"""

    _sensor_key = "balance"
    _attr_name = "水费余额"
    _attr_native_unit_of_measurement = "元"
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """返回水费余额（yue）。"""
        return self.gs_data.get("yue")


class WaterPriceSensor(JinanWaterBaseSensor):
    """水价传感器（账户级）。"""

    _sensor_key = "price"
    _attr_name = "水价"
    _attr_native_unit_of_measurement = "元/m³"

    @property
    def native_value(self):
        """返回水价（dj）。"""
        return self.gs_data.get("dj")


class WaterAddressSensor(JinanWaterBaseSensor):
    """用水地址传感器（账户级）。"""

    _sensor_key = "address"
    _attr_name = "用水地址"

    @property
    def native_value(self):
        """返回用水地址（mp）。"""
        return self.gs_data.get("mp")


class WaterUserNameSensor(JinanWaterBaseSensor):
    """户名传感器（账户级）。"""

    _sensor_key = "username"
    _attr_name = "户名"

    @property
    def native_value(self):
        """返回户名（hm）。"""
        return self.gs_data.get("hm")


class WaterCustomerRepSensor(JinanWaterBaseSensor):
    """客户代表传感器（账户级）。"""

    _sensor_key = "customer_rep"
    _attr_name = "客户代表"

    @property
    def native_value(self):
        """返回客户代表姓名（keHuDaiBiao）。"""
        return self.gs_data.get("keHuDaiBiao")


class WaterCustomerRepPhoneSensor(JinanWaterBaseSensor):
    """客户代表电话传感器（账户级）。"""

    _sensor_key = "customer_rep_phone"
    _attr_name = "客户代表电话"

    @property
    def native_value(self):
        """返回客户代表电话（keHuDaiBiaoDH）。"""
        return self.gs_data.get("keHuDaiBiaoDH")


class WaterPendingFeeSensor(JinanWaterBaseSensor):
    """欠费金额传感器（账户级）。"""

    _sensor_key = "pending_fee"
    _attr_name = "欠费金额"
    _attr_native_unit_of_measurement = "元"
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """返回欠费金额（qfje）。"""
        return self.gs_data.get("qfje")


class PenaltyFeeSensor(JinanWaterBaseSensor):
    """违约金传感器（账户级）。"""

    _sensor_key = "penalty_fee"
    _attr_name = "违约金"
    _attr_native_unit_of_measurement = "元"
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """返回违约金（wyj）。"""
        return self.gs_data.get("wyj")


# ============================================================
# 账单级传感器（数据来自 GetFaPiaoList）
# ============================================================

class WaterUsageSensor(JinanWaterBaseSensor):
    """本期用水量传感器（账单级）。"""

    _sensor_key = "usage"
    _attr_name = "本期用水量"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER

    @property
    def native_value(self):
        """
        返回本期用水量。

        优先使用 xzsl，回退到 sl。
        """
        data = self.gs_data
        return data.get("xzsl", data.get("sl"))


class WaterCurrentFeeSensor(JinanWaterBaseSensor):
    """本期水费传感器（账单级）。"""

    _sensor_key = "current_fee"
    _attr_name = "本期水费"
    _attr_native_unit_of_measurement = "元"
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """
        返回本期水费。

        优先使用 xzje，回退到 zje。
        """
        data = self.gs_data
        return data.get("xzje", data.get("zje"))

    @property
    def extra_state_attributes(self):
        """
        返回费用明细属性（从 mx 数组提取）。

        属性映射：
          一阶基本水费 -> FirstStage
          水资源费 -> WaterResource
          污水处理费 -> WasteWater
        """
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
    """上次表数传感器（账单级）。"""

    _sensor_key = "meter_prev"
    _attr_name = "上次表数"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        """返回上次表数（qd）。"""
        return self.gs_data.get("qd")


class WaterMeterCurrSensor(JinanWaterBaseSensor):
    """本次表数传感器（账单级）。"""

    _sensor_key = "meter_curr"
    _attr_name = "本次表数"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        """返回本次表数（zd）。"""
        return self.gs_data.get("zd")


class WaterMeterDateSensor(JinanWaterBaseSensor):
    """抄表日期传感器（账单级）。"""

    _sensor_key = "meter_date"
    _attr_name = "抄表日期"

    @property
    def native_value(self):
        """返回抄表日期（r1），格式化为 YYYY-MM-DD。"""
        return _format_date(self.gs_data.get("r1"))


class WaterPaymentDateSensor(JinanWaterBaseSensor):
    """缴费时间传感器（账单级）。"""

    _sensor_key = "payment_date"
    _attr_name = "缴费时间"

    @property
    def native_value(self):
        """返回缴费时间（xzrq），格式化为 YYYY-MM-DD HH:MM:SS。"""
        return _format_datetime(self.gs_data.get("xzrq"))
