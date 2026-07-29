"""济南水务 Home Assistant 集成 - 初始化模块"""

import json
import logging
import urllib.parse
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_OPENID,
    CONF_UNIONID,
    CONF_USER_NAME,
    CONF_PHONE_NUM,
    CONF_SELECTED_GS,
    APPLICATION_ID,
    API_BASE_URL,
    API_ENDPOINT,
    API_ENDPOINT_FAPIAO,
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
    """济南水务数据更新协调器。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(minutes=60),
        )
        self.entry = entry
        _LOGGER.info("协调器初始化完成")

    def async_update_listeners(self):
        """通知所有监听者更新。"""
        _LOGGER.info("通知 %d 个监听者更新", len(self._listeners))
        super().async_update_listeners()

    def _get_auth_headers(self):
        """构造通用的 API 认证请求头。"""
        data = self.entry.data
        openid = data[CONF_OPENID]
        unionid = data[CONF_UNIONID]
        user_name = data[CONF_USER_NAME]

        user_info = {"UserName": user_name, "ApplicationId": APPLICATION_ID}
        cookie_value = f"UserInfo={urllib.parse.quote(json.dumps(user_info))}"

        return {
            "openid": openid,
            "unionid": unionid,
            "cookie": cookie_value,
            "Content-Type": "application/json",
        }

    async def _call_api(self, session, url, headers):
        """发送 API 请求并返回解析后的 JSON 数据。"""
        async with session.post(url, headers=headers, data="{}") as response:
            if response.status != 200:
                raise UpdateFailed(f"API 请求失败，HTTP 状态码: {response.status}")

            result = await response.json()
            data = result.get("data")
            if data is None:
                state = result.get("state") or result.get("State")
                if not state:
                    raise UpdateFailed(
                        f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}"
                    )
                return []

            return data

    async def async_update_data(self):
        """数据更新方法。"""
        data = self.entry.data
        phone_num = data[CONF_PHONE_NUM]
        selected_gs = data.get(CONF_SELECTED_GS, [])

        session = async_get_clientsession(self.hass)
        headers = self._get_auth_headers()

        try:
            # 步骤 1: 获取账户级数据
            account_url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={phone_num}"
            account_list = await self._call_api(session, account_url, headers)

            # 步骤 2: 过滤出用户选择的户号
            account_data = {}
            for item in account_list:
                gs = item.get("gs")
                if gs in selected_gs:
                    account_data[gs] = item

            # 步骤 3: 获取每个户号的账单级数据
            invoice_data = {}
            for gs in selected_gs:
                try:
                    invoice_url = f"{API_BASE_URL}{API_ENDPOINT_FAPIAO}?GS={gs}"
                    invoice_list = await self._call_api(session, invoice_url, headers)
                    if invoice_list:
                        invoice_data[gs] = invoice_list[0]
                except Exception as error:
                    _LOGGER.warning("获取户号 %s 账单失败: %s", gs, error)

            # 步骤 4: 合并数据
            INVOICE_FIELDS = ["xzsl", "xzje", "zje", "qd", "zd", "r1", "xzrq", "sl", "mx"]

            merged_data = {}
            for gs in selected_gs:
                merged = {}
                if gs in account_data:
                    merged.update(account_data[gs])
                if gs in invoice_data:
                    for key in INVOICE_FIELDS:
                        if key in invoice_data[gs]:
                            merged[key] = invoice_data[gs][key]
                merged_data[gs] = merged

            return merged_data

        except UpdateFailed:
            raise
        except Exception as error:
            raise UpdateFailed(f"获取水务数据时出错: {error}")
