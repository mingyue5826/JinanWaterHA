"""
济南水务 Home Assistant 集成 - 配置流模块

本模块定义了用户添加集成时的交互流程（Config Flow）。

=== 配置流的概念 ===

配置流（Config Flow）是 HA 的 UI 配置向导机制。
当用户在 HA 中点击"添加集成"并搜索到"济南水务"后，
HA 会创建一个 ConfigFlow 实例并逐步调用其中的 async_step_xxx 方法。

每个 async_step_xxx 方法对应一个 UI 表单页面，流程如下：

  用户输入信息 → async_step_user()     → 表单验证
       ↓ (成功)
  调用 API 获取户号列表 → async_step_select_gs() → 复选框选择户号
       ↓ (成功)
  调用 async_create_entry() → 创建 ConfigEntry → HA 调用 __init__.py 的 async_setup_entry()

=== Options Flow 的概念 ===

Options Flow（选项流）是配置完成后的"修改设置"功能。
用户可以在 HA 的集成页面点击"配置"按钮来修改之前的设置。
流程与 Config Flow 类似，但操作的是已有的 ConfigEntry。
"""

import json
import urllib.parse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    NAME,
    CONF_OPENID,
    CONF_UNIONID,
    CONF_USER_NAME,
    CONF_PHONE_NUM,
    CONF_SELECTED_GS,
    APPLICATION_ID,
    API_BASE_URL,
    API_ENDPOINT,
)


class JinanWaterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    济南水务配置流。

    继承自 config_entries.ConfigFlow，domain 参数指定集成的域名。
    HA 通过这个类来管理用户添加集成的整个交互流程。

    === 配置流的工作机制 ===

    HA 的工作流程：
      1. 用户在 HA 界面点击 "添加集成"，选择 "济南水务"
      2. HA 实例化此类，调用 async_step_user()
      3. async_step_user() 返回一个表单给用户填写
      4. 用户提交表单后，HA 再次调用 async_step_user() 并传入 user_input
      5. 如果数据有效，调用下一个 step（如 async_step_select_gs）
      6. 所有步骤完成后，调用 async_create_entry() 创建配置条目

    === VERSION 的含义 ===

    VERSION 是配置流的版本号。如果将来修改了配置流的数据结构
    （比如增加/删除字段），需要递增版本号并在 async_migrate_entry 中处理迁移。
    """

    VERSION = 1

    def __init__(self):
        """初始化配置流，保存各步骤的临时数据。"""
        # 以下属性用于在多个 step 之间传递数据
        # 例如：async_step_user 收集的信息需要传给 async_step_select_gs 使用
        self._openid = None
        self._unionid = None
        self._user_name = None
        self._phone_num = None
        # 从 API 获取的户号绑定列表，用于在 select_gs 步骤中生成复选框
        self._bangding_list = []

    async def async_step_user(self, user_input=None):
        """
        配置流第一步：用户输入账号信息。

        这是配置流的入口步骤，HA 会首先调用此方法。

        === user_input 参数的机制 ===

        - 当 user_input 为 None 时：表示这是第一次进入此步骤，需要展示表单
        - 当 user_input 不为 None 时：表示用户已提交表单，需要处理输入

        :param user_input: 用户提交的表单数据（字典），首次调用时为 None
        :return: ShowForm（展示表单）或 CreateEntry（创建配置条目）或跳转到下一步
        """
        errors = {}

        if user_input is not None:
            # 用户已提交表单，保存输入的数据
            self._openid = user_input[CONF_OPENID]
            self._unionid = user_input[CONF_UNIONID]
            self._user_name = user_input[CONF_USER_NAME]
            self._phone_num = user_input[CONF_PHONE_NUM]

            # 调用 API 获取绑定的户号列表
            # 这一步会验证用户输入的认证信息是否有效
            try:
                self._bangding_list = await self._fetch_bangding_list()
            except Exception:
                # API 调用失败，显示错误信息
                errors["base"] = "api_connection_failed"
            else:
                # API 调用成功，但未获取到任何户号数据
                if not self._bangding_list:
                    errors["base"] = "no_bangding_data"
                else:
                    # 成功获取到户号列表，跳转到户号选择步骤
                    return await self.async_step_select_gs()

        # 定义表单的数据结构（Schema）
        # vol.Required 表示必填字段
        # 每个字段对应一个表单输入框
        schema = vol.Schema(
            {
                vol.Required(CONF_OPENID): str,
                vol.Required(CONF_UNIONID): str,
                vol.Required(CONF_USER_NAME): str,
                vol.Required(CONF_PHONE_NUM): str,
            }
        )

        # 展示表单给用户
        # step_id 对应 strings.json 中 config.step.user 的翻译
        # errors 中的 key 对应 strings.json 中 config.error 的翻译
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_gs(self, user_input=None):
        """
        配置流第二步：选择户号。

        用户在第一步输入账号信息后，API 返回绑定的户号列表。
        此步骤将户号列表以复选框形式展示，让用户选择要添加的户号。

        :param user_input: 用户选择的户号列表，首次调用时为 None
        :return: ShowForm（展示表单）或 CreateEntry（创建配置条目）
        """
        errors = {}

        if user_input is not None:
            # 用户已提交选择
            selected_gs = user_input.get(CONF_SELECTED_GS, [])
            if not selected_gs:
                # 未选择任何户号，显示错误
                errors["base"] = "no_gs_selected"
            else:
                # 选择完成，创建配置条目
                # title 会显示在 HA 的集成列表中
                # data 包含所有配置数据，会在 __init__.py 的 async_setup_entry 中使用
                title = f"{NAME} ({self._phone_num})"
                data = {
                    CONF_OPENID: self._openid,
                    CONF_UNIONID: self._unionid,
                    CONF_USER_NAME: self._user_name,
                    CONF_PHONE_NUM: self._phone_num,
                    CONF_SELECTED_GS: selected_gs,
                }
                return self.async_create_entry(title=title, data=data)

        # 构造户号选择选项
        # 格式: {户号值: "户名 - 地址"}，用于复选框的显示和值
        gs_options = {}
        for item in self._bangding_list:
            gs = item["gs"]
            hm = item.get("hm", "未知户名")
            mp = item.get("mp", "未知地址")
            gs_options[gs] = f"{hm} - {mp}"

        # cv.multi_select 会渲染为复选框列表，支持多选
        # gs_options 的 key 是选项值，value 是显示文本
        data_schema = vol.Schema(
            {
                vol.Required(CONF_SELECTED_GS): cv.multi_select(gs_options),
            }
        )

        return self.async_show_form(
            step_id="select_gs",
            data_schema=data_schema,
            errors=errors,
        )

    async def _fetch_bangding_list(self):
        """
        调用济南水务 API 获取绑定的户号列表。

        此方法在配置流第一步中调用，用于：
          1. 验证用户输入的认证信息是否有效
          2. 获取用户绑定的所有户号，供第二步选择

        === 与 Coordinator 中的 API 调用的区别 ===

        配置流中的 API 调用和 Coordinator 中的调用逻辑相同，
        但区别在于：
          - 配置流中：如果失败则显示错误，不创建配置条目
          - Coordinator 中：如果失败则抛出 UpdateFailed，HA 会标记实体不可用并重试

        :return: 户号数据列表
        :raises Exception: 当 API 调用失败时抛出
        """
        session = async_get_clientsession(self.hass)
        url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={self._phone_num}"

        # 构造 Cookie 中的 UserInfo（与 Coordinator 中相同）
        user_info = {"UserName": self._user_name, "ApplicationId": APPLICATION_ID}
        cookie_value = f"UserInfo={urllib.parse.quote(json.dumps(user_info))}"

        headers = {
            "openid": self._openid,
            "unionid": self._unionid,
            "cookie": cookie_value,
            "Content-Type": "application/json",
        }

        async with session.post(url, headers=headers, data="{}") as response:
            if response.status != 200:
                raise Exception(f"API 请求失败，状态码: {response.status}")

            result = await response.json()

            # 检查 data 字段是否存在且不为 null
            data = result.get("data")
            if data is None:
                # 兼容大小写 State / state
                state = result.get("state") or result.get("State")
                if not state:
                    raise Exception(
                        f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}"
                    )
                return []

            return data

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """
        创建选项流实例。

        此方法是 HA 的约定接口，当用户点击集成页面上的"配置"按钮时，
        HA 会调用此方法获取 OptionsFlow 实例。

        :param config_entry: 当前的配置条目
        :return: OptionsFlow 实例
        """
        return JinanWaterOptionsFlow(config_entry)


class JinanWaterOptionsFlow(config_entries.OptionsFlow):
    """
    济南水务选项流。

    继承自 OptionsFlow，用于在集成添加后修改配置。
    流程与 ConfigFlow 类似，但操作的是已有的 ConfigEntry。

    === Options Flow 与 Config Flow 的区别 ===

    - ConfigFlow: 创建新的配置条目（entry.data 是新建的）
    - OptionsFlow: 修改已有配置条目（通过 async_update_entry 更新 entry.data）

    用户通过 HA 界面 "设置 > 设备与服务 > 济南水务 > 配置" 触发。
    """

    def __init__(self, config_entry):
        """
        初始化选项流。

        :param config_entry: 当前的配置条目，包含已有的配置数据
        """
        self.config_entry = config_entry
        self._bangding_list = []
        # 临时存储第一步收集的数据，传给第二步使用
        self._temp_data = {}

    async def async_step_init(self, user_input=None):
        """
        选项流第一步：修改账号信息。

        与 ConfigFlow 的 async_step_user 类似，但会预填当前配置的值。
        用户修改后需要重新调用 API 验证并获取户号列表。

        :param user_input: 用户提交的表单数据，首次调用时为 None
        :return: ShowForm 或跳转到 select_gs 步骤
        """
        errors = {}

        if user_input is not None:
            # 保存用户修改的账号信息到临时变量
            self._temp_data = {
                CONF_OPENID: user_input[CONF_OPENID],
                CONF_UNIONID: user_input[CONF_UNIONID],
                CONF_USER_NAME: user_input[CONF_USER_NAME],
                CONF_PHONE_NUM: user_input[CONF_PHONE_NUM],
            }

            # 重新调用 API 获取户号列表
            try:
                session = async_get_clientsession(self.hass)
                url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={self._temp_data[CONF_PHONE_NUM]}"

                user_info = {
                    "UserName": self._temp_data[CONF_USER_NAME],
                    "ApplicationId": APPLICATION_ID,
                }
                cookie_value = f"UserInfo={urllib.parse.quote(json.dumps(user_info))}"

                headers = {
                    "openid": self._temp_data[CONF_OPENID],
                    "unionid": self._temp_data[CONF_UNIONID],
                    "cookie": cookie_value,
                    "Content-Type": "application/json",
                }

                async with session.post(url, headers=headers, data="{}") as response:
                    if response.status != 200:
                        raise Exception(f"API 请求失败，状态码: {response.status}")
                    result = await response.json()
                    data = result.get("data")
                    if data is None:
                        state = result.get("state") or result.get("State")
                        if not state:
                            raise Exception(
                                f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}"
                            )
                        self._bangding_list = []
                    else:
                        self._bangding_list = data
            except Exception:
                errors["base"] = "api_connection_failed"
            else:
                if not self._bangding_list:
                    errors["base"] = "no_bangding_data"
                else:
                    return await self.async_step_select_gs()

        # 读取当前配置数据，作为表单的默认值（预填功能）
        current_data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_OPENID, default=current_data.get(CONF_OPENID, "")): str,
                vol.Required(CONF_UNIONID, default=current_data.get(CONF_UNIONID, "")): str,
                vol.Required(CONF_USER_NAME, default=current_data.get(CONF_USER_NAME, "")): str,
                vol.Required(CONF_PHONE_NUM, default=current_data.get(CONF_PHONE_NUM, "")): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_select_gs(self, user_input=None):
        """
        选项流第二步：重新选择户号。

        与 ConfigFlow 的 select_gs 类似，但会预选当前已选的户号。
        用户修改选择后，通过 async_update_entry 更新配置条目数据。

        :param user_input: 用户选择的户号列表
        :return: ShowForm 或完成选项流
        """
        errors = {}

        if user_input is not None:
            selected_gs = user_input.get(CONF_SELECTED_GS, [])
            if not selected_gs:
                errors["base"] = "no_gs_selected"
            else:
                # 更新配置条目的数据
                # 将第一步的临时数据和第二步选择的户号合并后写入
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        **self._temp_data,
                        CONF_SELECTED_GS: selected_gs,
                    },
                )
                # 选项流完成时调用 async_create_entry
                # 注意：OptionsFlow 中 title 和 data 通常留空
                return self.async_create_entry(title="", data={})

        # 构造户号选择选项（与 ConfigFlow 中相同）
        gs_options = {}
        for item in self._bangding_list:
            gs = item["gs"]
            hm = item.get("hm", "未知户名")
            mp = item.get("mp", "未知地址")
            gs_options[gs] = f"{hm} - {mp}"

        # 获取当前已选的户号，作为复选框的默认勾选状态
        current_selected = self.config_entry.data.get(CONF_SELECTED_GS, [])

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SELECTED_GS, default=current_selected): cv.multi_select(gs_options),
            }
        )

        return self.async_show_form(
            step_id="select_gs",
            data_schema=data_schema,
            errors=errors,
        )
