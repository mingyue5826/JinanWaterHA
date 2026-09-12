"""济南水务 Home Assistant 集成 - 初始化模块"""

import json
import logging
import urllib.parse
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
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
    API_ENDPOINT_GetYiBiaoInfo,
    API_ENDPOINT_GetDataList,
    YIBIAO_DATA_KEY,
    ORDER_DETAIL_KEY,
    SERVICE_REFRESH_DATA,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "button"]

# ============================================================
# 发票（账单）记录字段映射：原字段 -> 新字段（按需求.md 重命名）
# 仅保留下方列出的字段，其余字段（如 b2/bl/zq/bc/fph）会被过滤掉
# ============================================================
INVOICE_FIELD_MAP = {
    "id": "id",                       # 账单记录唯一 ID
    "gs": "gs",                       # 户号
    "bm": "meter_number",             # 原 bm=水表编号（避免与 number 序号混淆）
    "hm": "username",                 # 户名
    "mp": "address",                  # 用水地址
    "jtbz": "is_tiered_price",        # 是否阶梯水价（true/false）
    "sljs": "person_base",            # 人口基数（阶梯水价核算用）
    "dj": "unit_price",               # 水价（元/m³）
    "r1": "read_date",                # 抄表日期（按日统计，保留接口原始值）
    "xzbz": "write_off_num",          # 销账编号
    "xzrq": "write_off_time",         # 销账时间（原 write_off_date；实为时间格式，保留原始值）
    "fpje": "invoice_amount",         # 发票金额（元）
    "wyj": "penalty_fee",             # 违约金（元）
    "xzsl": "write_off_usage",        # 销账水量（m³）（原 xzsl，修正 useage->usage 拼写）
    "xzje": "write_off_amount",       # 销账金额（元）
    "zje": "total_amount",            # 总金额（元）
    "dzfplqrq": "invoice_apply_time", # 发票领取时间（原 invoice_apply_date；保留接口原始值）
    "dzfpzt": "invoice_status",       # 发票状态（如：未开票）
    "ysjlzt": "status",               # 用水记录状态（如：YH=已核）
    "fplx": "invoice_type",           # 发票类型（如：增值税普通电子发票）
    "jffs": "pay_type",               # 缴费方式
    "yyzd": "pay_channel",            # 缴费渠道
    "dzfpdm": "invoice_code",         # 电子发票代码
    "dzfphm": "invoice_num",          # 电子发票号码
    "dzfpjym": "invoice_check_code",  # 电子发票校验码
    "dzfpsqdm": "invoice_apply_code", # 电子发票申请代码
    "fpsqlsh": "invoice_pipeline_num",# 发票申请流水号
    "scye": "balance_last",           # 上期余额（元）
    "bcye": "balance_current",        # 本期余额（元）
    "qd": "read_last",                # 上次表数（m³）
    "zd": "read_current",             # 本次表数（m³）
    "sl": "used_current",             # 本期用水量（m³）
    "smDate": "bill_month",           # 账单月份（如：2026-09）
    "nlsl": "nlsl",                   # TODO: 年累计用水量字段待确认（当前 nlsl 实际并非年累计水量），确认后启用 WaterYearlyUsageSensor 取值
    "yue": "balance",                 # 账户余额（元）
}


# 明细(mx)字段映射：原字段 -> 新字段（费用明细的每一条子项）
INVOICE_MX_FIELD_MAP = {
    "hh": "index",         # 明细序号
    "xmmc": "name",        # 费用项目名称（如：一阶基本水费 / 水资源费 / 污水处理费）
    "dw": "unit",          # 计量单位（如：立方米）
    "xmsl": "total",       # 数量（用量）
    "xmdj": "unit_price",  # 单价（元）
    "xmje": "amount",      # 金额（元）
}

def _transform_invoice_record(raw):
    """将单条原始账单记录筛选并重命名为对外暴露的结构（list[dict] 的元素）。"""
    result = {}
    for src, dst in INVOICE_FIELD_MAP.items():
        if src not in raw:
            continue
        result[dst] = raw[src]

    mx = raw.get("mx")
    if isinstance(mx, list):
        result["detail"] = [
            {dst: item.get(src) for src, dst in INVOICE_MX_FIELD_MAP.items() if src in item}
            for item in mx
        ]
    return result


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

    async def _call_api(self, session, url, headers, body="{}"):
        """发送 API 请求并返回解析后的 JSON 数据。

        body 为已序列化的 JSON 字符串；不传时默认发送空对象 "{}"（兼容既有接口）。
        """
        async with session.post(url, headers=headers, data=body) as response:
            if response.status != 200:
                raise UpdateFailed(f"API 请求失败，HTTP 状态码: {response.status}")

            result = await response.json()

            state = result.get("state") or result.get("State")
            if not state:
                raise UpdateFailed(
                    f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}"
                )

            return result

    async def _fetch_yibiao_data(self, session, headers, gs):
        """获取指定户号的实时仪表日用水数据。

        流程：
        1. 调用 GetYiBiaoInfo 取得 jsonData（字符串化 JSON 数组，含各数据文件标识）；
        2. 取出 InfoName 为 YibiaoSLInfo 的项；
        3. 以其作为 body 调用 GetDataList，返回 data（字符串化 JSON 数组，即日用水记录）。
        """
        today = datetime.now()
        month_ago = today - relativedelta(months=1)

        yibiao_body = {
            "WhereList": [
                {
                    "WhereName": "GS",
                    "Comparison": 0,
                    "Value": gs,
                    "GroupName": "Group1",
                }
            ],
            "Index": 0,
            "PageRecordCount": 3000,
            "isPage": False,
            "OrderBy": [""],
            "KaiShiRQ": month_ago.strftime("%Y-%m-%d"),
            "JieShuRQ": today.strftime("%Y-%m-%d"),
            "SumColunms": ["LiuLiang"],
            "GroupBy": [""],
            "PageToken": "",
        }

        yibiao_url = f"{API_BASE_URL}{API_ENDPOINT_GetYiBiaoInfo}"
        yibiao_result = await self._call_api(
            session, yibiao_url, headers, json.dumps(yibiao_body, ensure_ascii=False)
        )

        json_data = yibiao_result.get("jsonData")
        if not json_data:
            return []
        if isinstance(json_data, str):
            json_data = json.loads(json_data)
        if not isinstance(json_data, list):
            return []

        yibiao_info = next(
            (x for x in json_data if x.get("InfoName") == "YibiaoSLInfo"), None
        )
        if not yibiao_info:
            return []

        data_list_url = f"{API_BASE_URL}{API_ENDPOINT_GetDataList}"
        data_result = await self._call_api(
            session, data_list_url, headers, json.dumps(yibiao_info, ensure_ascii=False)
        )

        data = data_result.get("data")
        if not data:
            return []
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
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
            account_list = account_list.get("data")

            # 步骤 2: 过滤出用户选择的户号
            account_data = {}
            for item in account_list:
                gs = item.get("gs")
                if gs in selected_gs:
                    account_data[gs] = item

            # 步骤 3: 获取每个户号的账单级数据（保留全部记录，供订单详情传感器使用）
            invoice_data = {}
            for gs in selected_gs:
                try:
                    invoice_url = f"{API_BASE_URL}{API_ENDPOINT_FAPIAO}?GS={gs}"
                    invoice_list = await self._call_api(session, invoice_url, headers)
                    invoice_list = invoice_list.get("data") or []
                    # todo 发票接口返回的是多次结果，其中的r1代表本次统计的抄表日期
                    invoice_data[gs] = invoice_list
                except Exception as error:
                    _LOGGER.warning("获取户号 %s 账单失败: %s", gs, error)
                    invoice_data[gs] = []

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
            for gs in selected_gs:
                try:
                    records = await self._fetch_yibiao_data(session, headers, gs)
                except Exception as error:
                    _LOGGER.warning("获取户号 %s 仪表数据失败: %s", gs, error)
                    records = []
                merged_data.setdefault(gs, {})[YIBIAO_DATA_KEY] = records

            # 步骤 6: 订单详情（账单全量记录，筛选并重命名字段）
            for gs in selected_gs:
                records = invoice_data.get(gs, [])
                order_list = [_transform_invoice_record(rec) for rec in records]
                merged_data.setdefault(gs, {})[ORDER_DETAIL_KEY] = order_list

            return merged_data

        except UpdateFailed:
            raise
        except Exception as error:
            raise UpdateFailed(f"获取水务数据时出错: {error}")
