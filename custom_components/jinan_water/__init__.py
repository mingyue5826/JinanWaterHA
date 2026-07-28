"""
济南水务 Home Assistant 集成 - 初始化模块

本模块是整个集成的入口点，负责：
1. 集成的初始化和卸载
2. 数据更新协调器（DataUpdateCoordinator）的定义
3. 第三方 API 的调用逻辑
4. 自定义服务的注册

=== HA 集成初始化流程概述 ===

当用户在 HA 中添加一个集成时，HA 会依次调用：

  1. async_setup()          ← 集成首次被加载时调用（ YAML 配置方式，现已不常用）
  2. async_setup_entry()   ← 用户通过 UI 配置流添加集成时调用（主要入口）
     ├── 创建 DataUpdateCoordinator（数据协调器）
     ├── 执行首次数据拉取
     ├── 将协调器存入 hass.data 供其他模块使用
     ├── 转发设置到各平台（sensor、binary_sensor 等）
     └── 注册自定义服务
  3. async_unload_entry()  ← 用户移除集成时调用，负责清理资源

=== DataUpdateCoordinator 的作用 ===

DataUpdateCoordinator 是 HA 的核心工具类，负责：
  - 定期从第三方 API 拉取数据
  - 将数据分发给所有订阅了它的实体（Entity）
  - 统一处理刷新间隔、失败重试等逻辑

实体（Entity）只需继承 CoordinatorEntity 并传入 coordinator，
就能自动在 coordinator 更新数据后收到通知并刷新界面。
"""

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

# 创建日志记录器，所有日志通过 _LOGGER 输出
# 在 HA 日志中会显示为 custom_components.jinan_water
_LOGGER = logging.getLogger(__name__)

# 本集成支持的平台列表
# 目前只支持 sensor（传感器）平台
# 如果将来要支持 binary_sensor、switch 等，在这里添加
PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config):
    """
    集成初始化入口（YAML 配置方式）。

    现代集成主要通过 UI 配置流添加，此方法通常只需初始化数据结构即可。
    hass.data[DOMAIN] 是一个字典，用于在整个集成生命周期中共享数据。

    :param hass: HomeAssistant 实例，集成的全局上下文
    :param config: YAML 配置（本集成不使用 YAML 配置）
    :return: True 表示初始化成功
    """
    # setdefault 确保 hass.data[DOMAIN] 存在且为字典
    # 不同 ConfigEntry 的数据会以 entry_id 为 key 存储
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """
    配置条目设置入口（UI 配置流方式）。

    这是集成的核心方法，当用户通过配置流完成设置后，HA 会调用此方法。
    负责创建协调器、转发平台设置、注册服务。

    执行顺序：
      1. 创建 JinanWaterCoordinator 实例
      2. 执行首次数据拉取（async_config_entry_first_refresh）
      3. 将 coordinator 存入 hass.data 供 sensor 平台读取
      4. 转发到 sensor 平台（调用 sensor.py 的 async_setup_entry）
      5. 注册"手动刷新"服务
      6. 注册选项更新监听器

    :param hass: HomeAssistant 实例
    :param entry: ConfigEntry 对象，包含用户在配置流中输入的数据
                 entry.data 是一个只读字典，存储配置流中收集的数据
    :return: True 表示设置成功
    """
    # 1. 创建数据协调器，传入 hass 和 config entry
    coordinator = JinanWaterCoordinator(hass, entry)

    # 2. 执行首次数据拉取
    #    这会调用 coordinator.async_update_data() 并等待结果
    #    如果首次拉取失败，会抛出异常并阻止集成加载
    await coordinator.async_config_entry_first_refresh()

    # 3. 将协调器存入 hass.data
    #    key 为 entry_id（每个配置条目的唯一标识）
    #    sensor.py 的 async_setup_entry 会通过这个 key 取出 coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # 4. 转发到各平台
    #    HA 会调用 sensor.py 中的 async_setup_entry(hass, entry, async_add_entities)
    #    这是 HA 的平台转发机制
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 5. 注册自定义服务：jinan_water.refresh_data
    #    用户可以在 HA 中通过 "开发者工具 > 服务" 调用此服务
    #    调用后会立即触发数据刷新，而不必等待下一个更新周期
    async def manual_refresh(call):
        """手动刷新服务的处理函数。"""
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH_DATA, manual_refresh)

    # 6. 注册选项更新监听器
    #    当用户通过"配置 > 集成 > 济南水务 > 设置"修改选项时触发
    #    这里会重新加载整个集成条目，使新配置生效
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """
    卸载配置条目。

    当用户从 HA 中移除集成时调用，负责清理资源：
      1. 卸载所有平台（sensor 等）
      2. 从 hass.data 中删除协调器数据

    :param hass: HomeAssistant 实例
    :param entry: 要卸载的 ConfigEntry
    :return: True 表示卸载成功
    """
    # 卸载所有平台
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # 卸载成功后，清理 hass.data 中的数据
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry):
    """
    选项更新回调。

    当用户通过"设置"按钮修改配置时，此方法会被调用。
    这里直接重新加载整个集成条目，使新配置生效。

    :param hass: HomeAssistant 实例
    :param entry: 被更新的 ConfigEntry
    """
    await hass.config_entries.async_reload(entry.entry_id)


class JinanWaterCoordinator(DataUpdateCoordinator):
    """
    济南水务数据更新协调器。

    继承自 DataUpdateCoordinator，负责：
      1. 调用 GetBangDingList API 获取账户级数据（余额、户名、地址等）
      2. 调用 GetFaPiaoList API 获取账单级数据（本期用量、水费、抄表数等）
      3. 合并两个 API 的数据，返回 {户号: 合并数据} 字典
      4. 通知所有订阅的传感器实体更新

    === 数据来源说明 ===

    | 字段 | 来源 | 说明 |
    |------|------|------|
    | yue (余额) | GetBangDingList | 账户级数据 |
    | hm (户名) | GetBangDingList | 账户级数据 |
    | mp (地址) | GetBangDingList | 账户级数据 |
    | keHuDaiBiao (客户代表) | GetBangDingList | 账户级数据 |
    | keHuDaiBiaoDH (客户代表电话) | GetBangDingList | 账户级数据 |
    | qfje (欠费金额) | GetBangDingList | 账户级数据 |
    | wyj (违约金) | GetBangDingList | 账户级数据 |
    | xzsl/sl (本期用量) | GetFaPiaoList | 账单级数据 |
    | xzje/zje (本期水费) | GetFaPiaoList | 账单级数据 |
    | qd (上次表数) | GetFaPiaoList | 账单级数据 |
    | zd (本次表数) | GetFaPiaoList | 账单级数据 |
    | r1 (抄表日期) | GetFaPiaoList | 账单级数据 |
    | xzrq (缴费时间) | GetFaPiaoList | 账单级数据 |
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """
        初始化协调器。

        :param hass: HomeAssistant 实例
        :param entry: ConfigEntry，包含用户配置的 openid、unionid 等信息
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(minutes=60),
        )
        self.entry = entry

    def _get_auth_headers(self):
        """
        构造通用的 API 认证请求头。

        两个 API 都需要相同的认证信息：
        - openid / unionid: 微信小程序身份标识
        - cookie: 包含 URL 编码的 UserInfo JSON

        :return: 请求头字典
        """
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
        """
        发送 API 请求并返回解析后的 JSON 数据。

        :param session: aiohttp ClientSession
        :param url: 请求 URL
        :param headers: 请求头
        :return: 响应 data 字段内容
        :raises UpdateFailed: 当请求失败时抛出
        """
        async with session.post(url, headers=headers, data="{}") as response:
            if response.status != 200:
                raise UpdateFailed(f"API 请求失败，HTTP 状态码: {response.status}")

            result = await response.json()

            # 检查 data 字段是否存在且不为 null
            data = result.get("data")
            if data is None:
                # 兼容大小写 State / state
                state = result.get("state") or result.get("State")
                if not state:
                    raise UpdateFailed(
                        f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}"
                    )
                _LOGGER.debug("API 返回 data=null，URL: %s", url.split("?")[0])
                return []

            return data

    async def _fetch_account_data(self, session, phone_num, headers):
        """
        调用 GetBangDingList API 获取账户级数据。

        返回所有绑定户号的基本信息。

        :param session: aiohttp ClientSession
        :param phone_num: 手机号
        :param headers: 请求头
        :return: 户号列表 [{gs, hm, mp, yue, ...}, ...]
        """
        url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={phone_num}"
        return await self._call_api(session, url, headers)

    async def _fetch_invoice_data(self, session, gs, headers):
        """
        调用 GetFaPiaoList API 获取单个户号的账单级数据。

        返回该户号最新一期的账单详情。

        :param session: aiohttp ClientSession
        :param gs: 户号
        :param headers: 请求头
        :return: 账单列表 [{gs, xzsl, xzje, qd, zd, r1, xzrq, ...}, ...]
        """
        url = f"{API_BASE_URL}{API_ENDPOINT_FAPIAO}?GS={gs}"
        return await self._call_api(session, url, headers)

    async def async_update_data(self):
        """
        数据更新方法。

        按以下步骤获取数据并合并：
          1. 调用 GetBangDingList 获取所有账户数据
          2. 过滤出用户选择的户号
          3. 对每个选择的户号调用 GetFaPiaoList 获取账单数据
          4. 合并账户数据和账单数据

        === 返回数据格式 ===

        {
            "6422376": {
                # 来自 GetBangDingList 的字段
                "hm": "*明月", "mp": "地址", "yue": 65.6,
                "qfje": 0.0, "wyj": 0.0, "dj": 4.2,
                "keHuDaiBiao": "李明辉", "keHuDaiBiaoDH": "186****1826",
                # 来自 GetFaPiaoList 的字段
                "xzsl": 32, "xzje": 134.4, "zje": 134.4,
                "qd": 93, "zd": 125,
                "r1": "2026-07-01T00:00:00",
                "xzrq": "2026-07-22T17:49:12.5",
                "mx": [...]  # 费用明细
            },
            ...
        }

        :return: 合并后的户号数据字典
        :raises UpdateFailed: 当 API 调用失败时抛出
        """
        data = self.entry.data
        phone_num = data[CONF_PHONE_NUM]
        selected_gs = data.get(CONF_SELECTED_GS, [])

        session = async_get_clientsession(self.hass)
        headers = self._get_auth_headers()

        try:
            # 步骤 1: 获取账户级数据（所有绑定户号）
            account_list = await self._fetch_account_data(session, phone_num, headers)

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
                    invoice_list = await self._fetch_invoice_data(session, gs, headers)
                    if invoice_list:
                        invoice_data[gs] = invoice_list[0]
                        _LOGGER.debug("户号 %s 账单: xzsl=%s, xzje=%s", 
                                     gs, invoice_list[0].get("xzsl"), invoice_list[0].get("xzje"))
                except Exception as error:
                    _LOGGER.warning("获取户号 %s 账单失败: %s", gs, error)

            # 步骤 4: 合并数据（只提取账单级字段，避免覆盖账户级字段如 yue）
            # 账户级字段：yue, hm, mp, dj, qfje, wyj, keHuDaiBiao, keHuDaiBiaoDH
            # 账单级字段：xzsl, xzje, zje, qd, zd, r1, xzrq, sl, mx
            INVOICE_FIELDS = ["xzsl", "xzje", "zje", "qd", "zd", "r1", "xzrq", "sl", "mx"]
            
            merged_data = {}
            for gs in selected_gs:
                merged = {}
                if gs in account_data:
                    merged.update(account_data[gs])
                if gs in invoice_data:
                    # 只提取账单级字段，避免覆盖 yue 等账户级字段
                    for key in INVOICE_FIELDS:
                        if key in invoice_data[gs]:
                            merged[key] = invoice_data[gs][key]
                merged_data[gs] = merged

            return merged_data

        except UpdateFailed:
            raise
        except Exception as error:
            raise UpdateFailed(f"获取水务数据时出错: {error}")
