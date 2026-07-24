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
      1. 定期调用济南水务 API 获取用户绑定的户号数据
      2. 过滤出用户选择的户号数据
      3. 将数据缓存并通知所有订阅的传感器实体更新

    === 工作原理 ===

    HA 会按照 update_interval 指定的时间间隔调用 async_update_data()。
    该方法返回的数据会被存储在 self.data 中，
    所有继承了 CoordinatorEntity 的传感器会自动收到通知并刷新。

    数据流程：
      API 响应 → async_update_data() 过滤 → self.data → 传感器 native_value

    === 第三方 API 调用说明 ===

    本集成调用济南水务微信小程序的后端 API：
      - 接口地址: https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetBangDingList
      - 请求方式: POST
      - 认证方式: 通过 openid、unionid 请求头 + Cookie 中的 UserInfo 进行身份验证
      - 返回格式: JSON，data 字段为户号信息列表
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """
        初始化协调器。

        :param hass: HomeAssistant 实例
        :param entry: ConfigEntry，包含用户配置的 openid、unionid 等信息
        """
        # 调用父类初始化
        # - hass: HA 实例
        # - _LOGGER: 日志记录器，协调器内部会用它记录日志
        # - name: 协调器名称，用于日志和调试
        # - update_method: 数据更新方法，HA 会周期性调用它
        # - update_interval: 更新间隔，这里设置为 60 分钟
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(minutes=60),
        )
        # 保存 config entry 引用，用于在 async_update_data 中读取配置数据
        self.entry = entry

    async def async_update_data(self):
        """
        数据更新方法。

        由 DataUpdateCoordinator 按照设定的间隔自动调用。
        负责调用济南水务 API，过滤用户选择的户号数据并返回。

        === 返回值要求 ===

        返回值会被存储在 self.data 中，供传感器实体读取。
        这里返回一个字典，格式为 {户号: 户号数据字典}：
          {
              "6422376": {"gs": "6422376", "hm": "*明月", "yue": 65.6, ...},
              "6422378": {"gs": "6422378", "hm": "张三", "yue": 120.0, ...},
          }

        === 异常处理 ===

        如果 API 调用失败，应抛出 UpdateFailed 异常。
        HA 会捕获此异常并标记实体为不可用，同时按照策略进行重试。

        :return: 过滤后的户号数据字典
        :raises UpdateFailed: 当 API 调用失败时抛出
        """
        # 从 config entry 中读取用户配置的认证信息
        data = self.entry.data
        openid = data[CONF_OPENID]
        unionid = data[CONF_UNIONID]
        user_name = data[CONF_USER_NAME]
        phone_num = data[CONF_PHONE_NUM]
        # 用户在配置流中选择的户号列表
        selected_gs = data.get(CONF_SELECTED_GS, [])

        # 获取 HA 内置的 aiohttp ClientSession
        # 使用 HA 提供的 session 而非自行创建，这样 HA 可以统一管理连接池
        session = async_get_clientsession(self.hass)

        # 构造 API 请求 URL
        # PhoneNum 作为查询参数传入
        url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={phone_num}"

        # 构造 Cookie 中的 UserInfo
        # API 需要 Cookie 中携带 UserInfo，格式为 URL 编码的 JSON
        # 原始 JSON: {"UserName": "用户名", "ApplicationId": "应用ID"}
        user_info = {"UserName": user_name, "ApplicationId": APPLICATION_ID}
        # 使用 urllib.parse.quote 对 JSON 字符串进行 URL 编码
        cookie_value = f"UserInfo={urllib.parse.quote(json.dumps(user_info))}"

        # 构造请求头
        # openid 和 unionid 是微信小程序的身份标识，用于 API 认证
        headers = {
            "openid": openid,
            "unionid": unionid,
            "cookie": cookie_value,
            "Content-Type": "application/json",
        }

        try:
            # 发送 POST 请求
            # data="{}" 是请求体，API 需要一个空的 JSON 对象
            async with session.post(url, headers=headers, data="{}") as response:
                # 检查 HTTP 状态码
                if response.status != 200:
                    raise UpdateFailed(
                        f"API 请求失败，HTTP 状态码: {response.status}"
                    )

                # 解析 JSON 响应
                result = await response.json()

                # 检查业务状态码
                # - state: true 表示请求成功
                # - Code: 1 表示业务处理成功
                if not result.get("state") or result.get("Code") != 1:
                    raise UpdateFailed(
                        result.get("messageText", "API 返回错误")
                    )

                # 获取所有户号数据列表
                all_data = result.get("data", [])

                # 过滤出用户选择的户号
                # API 返回所有绑定的户号，但用户可能只选择了其中几个
                # 过滤后的数据格式: {户号: 户号数据}
                filtered_data = {}
                for item in all_data:
                    gs = item.get("gs")
                    if gs in selected_gs:
                        filtered_data[gs] = item

                return filtered_data

        except UpdateFailed:
            # UpdateFailed 异常直接向上抛出
            raise
        except Exception as error:
            # 其他异常包装为 UpdateFailed
            # 这样 HA 可以正确处理并显示错误状态
            raise UpdateFailed(f"获取水务数据时出错: {error}")
