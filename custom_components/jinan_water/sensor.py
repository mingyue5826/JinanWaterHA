"""
济南水务 Home Assistant 集成 - 传感器平台模块
"""

import logging
from datetime import datetime

from homeassistant.components.sensor import (SensorEntity,SensorStateClass,SensorDeviceClass)
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_SELECTED_GS, YIBIAO_DATA_KEY, ORDER_DETAIL_KEY

_LOGGER = logging.getLogger(__name__)

# ============================================================
# 字段说明（供前端 UI 设计参考）
# 这些说明会以额外属性的形式附加到「订单详情」实体上，便于在 UI 中理解各字段含义
# ============================================================
ORDER_DETAIL_FIELD_NOTES = {
    "id": "账单记录唯一 ID",
    "gs": "户号",
    "meter_number": "水表编号",
    "username": "户名",
    "address": "用水地址",
    "is_tiered_price": "是否阶梯水价（true/false）",
    "person_base": "人口基数（阶梯水价核算用）",
    "unit_price": "水价（元/m³）",
    "read_date": "抄表日期",
    "write_off_num": "销账编号",
    "write_off_time": "销账时间",
    "invoice_amount": "发票金额（元）",
    "penalty_fee": "违约金（元）",
    "write_off_usage": "销账水量（m³）",
    "write_off_amount": "销账金额（元）",
    "total_amount": "总金额（元）",
    "invoice_apply_time": "发票领取时间",
    "invoice_status": "发票状态（如：未开票）",
    "status": "用水记录状态（如：YH=已核）",
    "invoice_type": "发票类型（如：增值税普通电子发票）",
    "pay_type": "缴费方式",
    "pay_channel": "缴费渠道",
    "invoice_code": "电子发票代码",
    "invoice_num": "电子发票号码",
    "invoice_check_code": "电子发票校验码",
    "invoice_apply_code": "电子发票申请代码",
    "invoice_pipeline_num": "发票申请流水号",
    "balance_last": "上期余额（元）",
    "balance_current": "本期余额（元）",
    "read_last": "上次表数（m³）",
    "read_current": "本次表数（m³）",
    "used_current": "本期用水量（m³）",
    "bill_month": "账单月份（如：2026-09）",
    "nlsl": "待定",
    "balance": "账户余额（元）",
    "detail": "费用明细列表（子项字段见「明细字段说明」）",
}

ORDER_DETAIL_MX_FIELD_NOTES = {
    "index": "明细序号",
    "name": "费用项目名称（如：一阶基本水费 / 水资源费 / 污水处理费）",
    "unit": "计量单位（如：立方米）",
    "total": "数量（用量）",
    "unit_price": "单价（元）",
    "amount": "金额（元）",
}


def _parse_record_date(date_str):
    """将记录中的 date 字段（如 '2026-09-12 00'）解析为 datetime，失败返回 datetime.min 以便取最大值。"""
    if not date_str or not isinstance(date_str, str):
        return datetime.min
    s = date_str[:-3] if date_str.endswith(" 00") else date_str
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return datetime.min


def _is_current_unpaid(xzrq, xzbz):
    """判断本期是否未缴费。

    判定规则（两个字段同时满足才视为未缴费）：
    - xzrq（销账时间）为空字符串 / None / '0001-01-01T00:00:00'
    - xzbz（销账编号）为 None / 空字符串
    """
    xzrq_empty = (
        xzrq is None
        or (isinstance(xzrq, str) and xzrq.strip() in ("", "0001-01-01T00:00:00"))
    )
    xzbz_empty = xzbz is None or (isinstance(xzbz, str) and xzbz.strip() == "")
    return xzrq_empty and xzbz_empty


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
        entities.append(BalanceSensor(coordinator, entry, gs))
        entities.append(PriceSensor(coordinator, entry, gs))
        entities.append(AddressSensor(coordinator, entry, gs))
        entities.append(UserNameSensor(coordinator, entry, gs))
        entities.append(CustomerRepSensor(coordinator, entry, gs))
        entities.append(CustomerRepPhoneSensor(coordinator, entry, gs))
        entities.append(PendingFeeSensor(coordinator, entry, gs))
        entities.append(PenaltyFeeSensor(coordinator, entry, gs))
        entities.append(UsageSensor(coordinator, entry, gs))
        entities.append(YearlyUsageSensor(coordinator, entry, gs))
        entities.append(CurrentFeeSensor(coordinator, entry, gs))
        # 本期/上期订单相关传感器：实体ID前缀统一为 order_，便于在 HA 实体列表中排序相邻
        entities.append(PriceSensor(coordinator, entry, gs))        # 本期水价
        entities.append(MeterReadingStartSensor(coordinator, entry, gs))    # 上期订单表数
        entities.append(MeterReadingEndSensor(coordinator, entry, gs))    # 本期表数
        entities.append(MeterDateSensor(coordinator, entry, gs))    # 本期抄表时间
        entities.append(PaymentDateSensor(coordinator, entry, gs))  # 本期缴费时间
        entities.append(UsageDetailSensor(coordinator, entry, gs))
        entities.append(YesterdayUsageSensor(coordinator, entry, gs))
        entities.append(YesterdayMeterSensor(coordinator, entry, gs))  # 昨日表读数
        entities.append(YesterdayReadingDate(coordinator, entry, gs))
        entities.append(OrderDetailSensor(coordinator, entry, gs))

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
        mp = gs_data.get("mp", "") # 门牌
        hm = gs_data.get("hm", "") # 户名

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, gs)},
            "name": mp if mp else f"济南水务 - {gs}",
            "manufacturer": "济南水务集团",
            "model": f"户号: {hm} - {gs}",
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

class BalanceSensor(JinanWaterBaseSensor):
    _sensor_key = "balance"
    _attr_name = "水费余额"
    _attr_icon = "mdi:wallet-outline"
    _attr_native_unit_of_measurement = "元"

    @property
    def native_value(self):
        return self.gs_data.get("yue")


class PriceSensor(JinanWaterBaseSensor):
    _sensor_key = "order_price"
    _attr_name = "本期水价"
    _attr_icon = "mdi:tag-outline"
    _attr_native_unit_of_measurement = "元/m³"

    @property
    def native_value(self):
        return self.gs_data.get("dj")


class AddressSensor(JinanWaterBaseSensor):
    _sensor_key = "address"
    _attr_name = "用水地址"
    _attr_icon = "mdi:map-marker-outline"

    @property
    def native_value(self):
        return self.gs_data.get("mp")


class UserNameSensor(JinanWaterBaseSensor):
    _sensor_key = "username"
    _attr_name = "户名"
    _attr_icon = "mdi:account-outline"

    @property
    def native_value(self):
        return self.gs_data.get("hm")


class CustomerRepSensor(JinanWaterBaseSensor):
    _sensor_key = "customer_rep"
    _attr_name = "客户代表"
    _attr_icon = "mdi:account-tie"

    @property
    def native_value(self):
        return self.gs_data.get("keHuDaiBiao")


class CustomerRepPhoneSensor(JinanWaterBaseSensor):
    _sensor_key = "customer_rep_phone"
    _attr_name = "客户代表电话"
    _attr_icon = "mdi:phone-outline"

    @property
    def native_value(self):
        """返回客户代表电话（keHuDaiBiaoDH）。"""
        return self.gs_data.get("keHuDaiBiaoDH")


class PendingFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "pending_fee"
    _attr_name = "欠费金额"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        return self.gs_data.get("qfje")


class PenaltyFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "penalty_fee"
    _attr_name = "违约金"
    _attr_icon = "mdi:gavel"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        return self.gs_data.get("wyj")


# ============================================================
# 账单级传感器
# ============================================================

class UsageSensor(JinanWaterBaseSensor):
    _sensor_key = "usage"
    _attr_name = "本期用水量"
    _attr_icon = "mdi:water"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    @property
    def native_value(self):
        data = self.gs_data
        return data.get("sl")


class YearlyUsageSensor(JinanWaterBaseSensor):
    """年累计用水量传感器。

    TODO: 年累计用水量的接口字段待确认（当前 nlsl 实际并非年累计水量），
    数据来源暂不确定。待后端确认正确字段后，再从 gs_data 读取真实值；
    当前先固定返回 0 作为占位。
    """

    _sensor_key = "yearly_usage"
    _attr_name = "年累计用水量"
    _attr_icon = "mdi:chart-areaspline"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        # TODO: 年累计用水量字段待确认（nlsl 目前并非年累计水量，返回 0 为占位）。
        # 待接口确认正确字段后，取消注释下方取值逻辑：
        # return self.gs_data.get("nlsl")
        return 0


class CurrentFeeSensor(JinanWaterBaseSensor):
    _sensor_key = "current_fee"
    _attr_name = "本期水费"
    _attr_icon = "mdi:receipt-text-outline"
    _attr_native_unit_of_measurement = "元"
    @property
    def native_value(self):
        data = self.gs_data
        return data.get("zje")

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


class MeterReadingStartSensor(JinanWaterBaseSensor):
    _sensor_key = "order_meter_reading_start"
    _attr_name = "本期初始表数"
    _attr_icon = "mdi:gauge-low"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        return self.gs_data.get("qd")


class MeterReadingEndSensor(JinanWaterBaseSensor):
    _sensor_key = "order_meter_reading_end"
    _attr_name = "本期截止表数"
    _attr_icon = "mdi:gauge"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        return self.gs_data.get("zd")


class MeterDateSensor(JinanWaterBaseSensor):
    _sensor_key = "order_meter_date"
    _attr_name = "本期抄表日期"
    _attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self):
        value = self.gs_data.get("r1")
        if not value:
            return None
        try:
            return value[:10]  # "2026-07-01"
        except (TypeError, ValueError, IndexError):
            return str(value) if value else None


class PaymentDateSensor(JinanWaterBaseSensor):
    _sensor_key = "order_payment_date"
    _attr_name = "本期缴费时间"
    _attr_icon = "mdi:cash-check"

    @property
    def native_value(self):
        xzrq = self.gs_data.get("xzrq")
        xzbz = self.gs_data.get("xzbz")
        # 本期未缴费时，缴费时间展示为「未缴费」
        if _is_current_unpaid(xzrq, xzbz):
            return "未缴费"
        if not xzrq:
            return None
        try:
            return xzrq[:19].replace("T", " ")  # "2026-07-22 17:49:12"
        except (TypeError, ValueError, IndexError):
            return str(xzrq) if xzrq else None


# ============================================================
# 实时仪表传感器（数据来源：GetYiBiaoInfo + GetDataList）
# ============================================================

class UsageDetailSensor(JinanWaterBaseSensor):
    """用水详情传感器：固定值「图表」，明细列表存放于 graph 属性（真实列表对象）。"""

    _sensor_key = "usage_detail"
    _attr_name = "用水详情"
    _attr_icon = "mdi:chart-line"

    @property
    def native_value(self):
        return "图表"

    @property
    def extra_state_attributes(self):
        records = self.gs_data.get(YIBIAO_DATA_KEY, [])
        if not records:
            return {}

        graph_records = []
        for rec in records:
            item = dict(rec)
            date_val = item.get("date")
            if isinstance(date_val, str) and date_val.endswith(" 00"):
                item["date"] = date_val[:-3]
            graph_records.append(item)

        if not graph_records:
            return {}

        # 返回真实列表对象，Home Assistant 会以结构化列表（开发中工具/前端）形式展示
        return {"graph": graph_records}


class YesterdayUsageSensor(JinanWaterBaseSensor):
    """昨日用水量传感器：取日用水记录中日期最新一条的 value。"""

    _sensor_key = "usage_yesterday"
    _attr_name = "昨日用水量"
    _attr_icon = "mdi:water-outline"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        records = self.gs_data.get(YIBIAO_DATA_KEY, [])
        if not records:
            return None
        latest = max(records, key=lambda r: _parse_record_date(r.get("date", "")))
        return latest.get("value")


class YesterdayMeterSensor(JinanWaterBaseSensor):
    """昨日表读数传感器：取日用水记录中日期最新一条的 ZhiDu（表读数）。"""

    _sensor_key = "meter_yesterday"
    _attr_name = "昨日表读数"
    _attr_icon = "mdi:gauge"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    @property
    def native_value(self):
        records = self.gs_data.get(YIBIAO_DATA_KEY, [])
        if not records:
            return None
        latest = max(records, key=lambda r: _parse_record_date(r.get("date", "")))
        return latest.get("ZhiDu")

class YesterdayReadingDate(JinanWaterBaseSensor):
    """最新读表日期"""
    _sensor_key = "yesterday_meter_reading_date"
    _attr_name = "最新抄表日期"
    _attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self):
        records = self.gs_data.get(YIBIAO_DATA_KEY, [])
        if not records:
            return None
        latest = max(records, key=lambda r: _parse_record_date(r.get("date", "")))
        date = latest.get("date")
        if isinstance(date, str) and date.endswith(" 00"):
            date = date[:-3]
        return date

class OrderDetailSensor(JinanWaterBaseSensor):
    """订单详情传感器：固定值「图表」，全部账单记录（已筛选/重命名）存放于 graph 属性（真实列表）。"""

    _sensor_key = "order_detail"
    _attr_name = "订单详情"
    _attr_icon = "mdi:file-document-outline"

    @property
    def native_value(self):
        return "图表"

    @property
    def extra_state_attributes(self):
        records = self.gs_data.get(ORDER_DETAIL_KEY, [])
        if not records:
            return {}
        # 返回真实列表对象，Home Assistant 以结构化列表形式展示
        # 同时附带字段说明，方便前端 UI 设计理解每个字段含义
        return {
            "graph": records,
            "字段说明": ORDER_DETAIL_FIELD_NOTES,
            "明细字段说明": ORDER_DETAIL_MX_FIELD_NOTES,
        }
