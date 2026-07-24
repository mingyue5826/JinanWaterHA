"""
济南水务 Home Assistant 集成 - 传感器平台模块

本模块定义了所有传感器实体，负责：
1. 从协调器（Coordinator）中读取数据并展示为传感器
2. 配置实体的属性（名称、单位、设备类、图标等）
3. 通过 CoordinatorEntity 实现数据的自动更新与同步

=== HA 实体（Entity）概述 ===

实体是 HA 中数据展示的基本单位。传感器（Sensor）是最常见的实体类型，
用于展示一个可测量的数值（如温度、湿度、余额等）。

=== 数据更新与同步机制 ===

传统方式：实体内部自己定时拉取数据（polling）
现代方式：实体通过 CoordinatorEntity 订阅 DataUpdateCoordinator 的更新通知

本集成使用现代方式，流程如下：

  Coordinator 每 60 分钟调用 API → 数据存入 coordinator.data
       ↓
  CoordinatorEntity 自动收到更新通知 → 调用 _handle_coordinator_update()
       ↓
  _handle_coordinator_update() 触发 async_write_ha_state()
       ↓
  HA 读取 native_value 属性 → 更新前端显示

传感器只需要定义 native_value 属性，从 coordinator.data 中取出对应字段即可，
无需手动管理更新逻辑。

=== 设备（Device）与实体（Entity）的关系 ===

一个户号 = 一个设备
一个设备下有多个实体（余额、用水量、水价等）

通过 _attr_device_info 中的 identifiers 将实体关联到同一个设备。
HA 会在界面上自动将同一设备的实体分组展示。
"""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SELECTED_GS


async def async_setup_entry(hass, entry, async_add_entities):
    """
    传感器平台设置入口。

    当 __init__.py 调用 async_forward_entry_setups 时，HA 会调用此方法。
    负责根据用户选择的户号创建所有传感器实体。

    :param hass: HomeAssistant 实例
    :param entry: ConfigEntry，包含用户配置数据
    :param async_add_entities: 回调函数，用于向 HA 注册实体
    """
    # 从 hass.data 中取出协调器
    # 协调器在 __init__.py 的 async_setup_entry 中创建并存入 hass.data
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # 获取用户选择的户号列表
    selected_gs = entry.data.get(CONF_SELECTED_GS, [])

    # 为每个户号创建所有传感器实体
    entities = []
    for gs in selected_gs:
        # 每个户号创建 8 个传感器
        entities.append(WaterBalanceSensor(coordinator, entry, gs))
        entities.append(WaterUsageSensor(coordinator, entry, gs))
        entities.append(WaterPriceSensor(coordinator, entry, gs))
        entities.append(WaterCurrentFeeSensor(coordinator, entry, gs))
        entities.append(WaterAddressSensor(coordinator, entry, gs))
        entities.append(WaterUserNameSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepSensor(coordinator, entry, gs))
        entities.append(WaterCustomerRepPhoneSensor(coordinator, entry, gs))

    # 注册所有实体到 HA
    # async_add_entities 会触发实体的初始化和首次状态写入
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

    === 继承 SensorEntity 的作用 ===

    SensorEntity 是 HA 传感器基类，提供：
      - native_value 属性：传感器当前的值
      - native_unit_of_measurement：单位
      - device_class：设备类（影响图标和单位显示）

    === _attr_ 前缀属性的作用 ===

    HA 中以 _attr_ 开头的类属性是"实体属性"的快捷设置方式。
    设置 _attr_name = "水费余额" 等同于在 __init__ 中 self._attr_name = "水费余额"。
    HA 会在内部自动读取这些属性来配置实体。
    """

    # 子类必须定义此属性，用于生成唯一 ID
    _sensor_key = None

    def __init__(self, coordinator, entry, gs):
        """
        初始化传感器。

        :param coordinator: 数据更新协调器
        :param entry: ConfigEntry
        :param gs: 户号，用于区分不同户号的数据
        """
        # 调用父类初始化，传入协调器
        # 这会建立实体与协调器的订阅关系
        super().__init__(coordinator)

        self._entry = entry
        self._gs = gs

        # 唯一标识符，格式: entry_id_户号_传感器类型
        # 例如: abc123_6422376_balance
        # HA 通过 unique_id 判断实体是否已存在，避免重复创建
        self._attr_unique_id = f"{entry.entry_id}_{gs}_{self._sensor_key}"

        # 从协调器数据中获取用水地址作为设备名称
        # 使用 getattr 安全获取，避免 coordinator.data 为 None 时出错
        data = getattr(coordinator, 'data', {}) or {}
        mp = data.get(gs, {}).get("mp", "")

        # 设备信息：将同一户号的所有传感器关联到同一个设备
        # - identifiers: 设备的唯一标识，格式为 (DOMAIN, entry_id, 户号)
        # - name: 设备名称（显示在 HA 设备页面）
        # - manufacturer: 制造商
        # - model: 型号（这里用户号）
        # - via_device: 父设备标识（如果有网关的话）
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
        获取当前户号的数据。

        从 coordinator.data 中取出当前户号的数据字典。
        coordinator.data 的格式为: {户号: {字段: 值, ...}}

        :return: 当前户号的数据字典，如果不存在则返回空字典
        """
        # 安全检查：确保 coordinator.data 不为 None
        data = getattr(self.coordinator, 'data', {}) or {}
        return data.get(self._gs, {})

    @property
    def available(self):
        """
        实体是否可用。

        覆盖父类的 available 属性，额外检查当前户号是否存在于数据中。
        如果 API 返回的数据中不包含此户号（可能已被解绑），
        则标记实体为不可用。

        :return: True 表示可用
        """
        # 安全检查：确保 coordinator.data 不为 None 且是字典类型
        data = getattr(self.coordinator, 'data', {}) or {}
        return super().available and self._gs in data


class WaterBalanceSensor(JinanWaterBaseSensor):
    """水费余额传感器。"""

    _sensor_key = "balance"
    _attr_name = "水费余额"
    _attr_native_unit_of_measurement = "元"
    # MONETARY 设备类会显示货币图标和格式
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """
        传感器的当前值。

        HA 会周期性读取此属性来更新前端显示。
        从户号数据中取出 yue（余额）字段。

        :return: 水费余额（如 65.6）
        """
        return self.gs_data.get("yue")


class WaterUsageSensor(JinanWaterBaseSensor):
    """累计用水量传感器。"""

    _sensor_key = "usage"
    _attr_name = "累计用水量"
    # 使用 HA 内置的体积单位（立方米）
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    # WATER 设备类会显示水滴图标
    _attr_device_class = SensorDeviceClass.WATER

    @property
    def native_value(self):
        """返回累计用水量（sljs 字段，单位 m³）。"""
        return self.gs_data.get("sljs")


class WaterPriceSensor(JinanWaterBaseSensor):
    """水价传感器。"""

    _sensor_key = "price"
    _attr_name = "水价"
    # 自定义单位（HA 没有内置 元/m³ 的常量）
    _attr_native_unit_of_measurement = "元/m³"

    @property
    def native_value(self):
        """返回水价（dj 字段）。"""
        return self.gs_data.get("dj")


class WaterCurrentFeeSensor(JinanWaterBaseSensor):
    """本期水费传感器。"""

    _sensor_key = "current_fee"
    _attr_name = "本期水费"
    _attr_native_unit_of_measurement = "元"
    _attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        """返回本期水费（qfje 字段）。"""
        return self.gs_data.get("qfje")


class WaterAddressSensor(JinanWaterBaseSensor):
    """用水地址传感器。"""

    _sensor_key = "address"
    _attr_name = "用水地址"

    @property
    def native_value(self):
        """返回用水地址（mp 字段）。"""
        return self.gs_data.get("mp")


class WaterUserNameSensor(JinanWaterBaseSensor):
    """户名传感器。"""

    _sensor_key = "username"
    _attr_name = "户名"

    @property
    def native_value(self):
        """返回户名（hm 字段）。"""
        return self.gs_data.get("hm")


class WaterCustomerRepSensor(JinanWaterBaseSensor):
    """客户代表传感器。"""

    _sensor_key = "customer_rep"
    _attr_name = "客户代表"

    @property
    def native_value(self):
        """返回客户代表姓名（keHuDaiBiao 字段）。"""
        return self.gs_data.get("keHuDaiBiao")


class WaterCustomerRepPhoneSensor(JinanWaterBaseSensor):
    """客户代表电话传感器。"""

    _sensor_key = "customer_rep_phone"
    _attr_name = "客户代表电话"

    @property
    def native_value(self):
        """返回客户代表电话（keHuDaiBiaoDH 字段）。"""
        return self.gs_data.get("keHuDaiBiaoDH")
