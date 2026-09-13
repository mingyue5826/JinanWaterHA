"""济南水务 Home Assistant 集成 - 初始化模块

本模块只负责集成生命周期（setup / unload / options）与数据协调器的编排；
具体的接口请求与数据清洗已抽离到 api.py（JinanWaterApi）。
"""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import JinanWaterApi
from .history import DailyHistoryStore
from .const import (
    DOMAIN,
    CONF_PHONE_NUM,
    CONF_SELECTED_GS,
    YIBIAO_DATA_KEY,
    ORDER_DETAIL_KEY,
    SERVICE_REFRESH_DATA,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "button"]


async def async_setup(hass: HomeAssistant, config):
    """集成初始化入口。"""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """配置条目设置入口。"""
    coordinator = JinanWaterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def manual_refresh(call):
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_DATA, manual_refresh)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """卸载配置条目。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """选项更新回调。"""
    await hass.config_entries.async_reload(entry.entry_id)


class JinanWaterCoordinator(DataUpdateCoordinator):
    """济南水务数据更新协调器（仅做数据流编排，具体请求见 JinanWaterApi）。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(minutes=60),
        )
        self.entry = entry
        self.api = JinanWaterApi(hass, entry)
        # 日用水历史本地持久化（接口只返回近 1 个月，更早的数据读本地历史）
        self.history = DailyHistoryStore(hass)
        # 最近一次成功同步的时间（UTC，带时区），供「上次同步时间」传感器读取。
        # 自行记录而不依赖 HA 内部属性（不同 HA 版本该属性所在位置不同）。
        self.last_sync_time = None
        _LOGGER.info("协调器初始化完成")

    def async_update_listeners(self):
        """通知所有监听者更新。"""
        _LOGGER.info("通知 %d 个监听者更新", len(self._listeners))
        super().async_update_listeners()

    async def async_update_data(self):
        """数据更新方法（编排各接口数据，组装为按户号索引的合并字典）。"""
        data = self.entry.data
        phone_num = data[CONF_PHONE_NUM]
        selected_gs = data.get(CONF_SELECTED_GS, [])

        try:
            # 步骤 1: 获取账户级数据
            account_list = await self.api.fetch_account_list(phone_num)

            # 步骤 2: 过滤出用户选择的户号
            account_data = {}
            for item in account_list:
                gs = item.get("gs")
                if gs in selected_gs:
                    account_data[gs] = item

            # 步骤 3: 获取每个户号的账单级数据（保留全部记录，供订单详情传感器使用）
            # todo 发票接口返回的是多次结果，其中的 r1 代表本次统计的抄表日期
            invoice_data = {}
            for gs in selected_gs:
                invoice_data[gs] = await self.api.fetch_invoice_list(gs)

            # 步骤 4: 合并数据（现有账单级传感器仍使用第一条记录，保持原有行为）
            # xzsl(sl)     usage        本期用水量
            # xzje(zje)    current_fee  本期水费
            # mx                        明细
            # qd           meter_prev   上次表数
            # zd           meter_curr   本次表数
            # r1           meter_date   抄表日期
            # xzrq         payment_date 缴费时间
            INVOICE_FIELDS = ["xzsl", "xzje", "zje", "qd", "zd", "r1", "xzrq", "sl", "nlsl", "mx"]

            merged_data = {}
            for gs in selected_gs:
                merged = {}
                if gs in account_data:
                    merged.update(account_data[gs])
                invoices = invoice_data.get(gs, [])
                first_invoice = invoices[0] if invoices else {}
                for key in INVOICE_FIELDS:
                    if key in first_invoice:
                        merged[key] = first_invoice[key]
                merged_data[gs] = merged

            # 步骤 5: 获取每个户号的实时仪表日用水数据（用水详情 / 昨日用水量传感器使用）
            # 接口只返回近 1 个月，这里与本地持久化历史合并，得到累积的完整曲线
            for gs in selected_gs:
                records = await self.api.fetch_yibiao_data(gs)
                try:
                    records = await self.history.async_merge(gs, records)
                except Exception as error:  # 持久化失败不应影响本次同步
                    _LOGGER.warning("户号 %s 日用水历史合并失败: %s", gs, error)
                merged_data.setdefault(gs, {})[YIBIAO_DATA_KEY] = records

            # 步骤 6: 订单详情（账单全量记录，筛选并重命名字段）
            for gs in selected_gs:
                records = invoice_data.get(gs, [])
                order_list = self.api.transform_invoice_records(records)
                merged_data.setdefault(gs, {})[ORDER_DETAIL_KEY] = order_list

            # 全部数据获取成功，记录本次同步时间（UTC，带时区）
            self.last_sync_time = dt_util.utcnow()
            return merged_data

        except UpdateFailed:
            raise
        except Exception as error:
            raise UpdateFailed(f"获取水务数据时出错: {error}")
