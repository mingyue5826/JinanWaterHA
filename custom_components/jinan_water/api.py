"""济南水务 Home Assistant 集成 - API 客户端模块

本模块封装所有济南水务后端接口的认证、HTTP 请求与原始数据清洗（字段重命名/筛选）。
__init__.py 中的协调器只负责编排数据流，不再直接处理 HTTP 细节，可读性、可测试性更好。
"""

import json
import logging
import urllib.parse
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    APPLICATION_ID,
    API_BASE_URL,
    API_ENDPOINT,
    API_ENDPOINT_FAPIAO,
    API_ENDPOINT_GetYiBiaoInfo,
    API_ENDPOINT_GetDataList,
    CONF_OPENID,
    CONF_UNIONID,
    CONF_USER_NAME,
)

_LOGGER = logging.getLogger(__name__)

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


class JinanWaterApi:
    """济南水务 API 客户端。

    封装认证头构造、HTTP 请求发送、以及各业务接口的调用与原始数据解析。
    协调器持有一个该实例，编排数据流时直接调用对应方法。
    """

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        # 接口调用失败记录（供「集成状态」诊断实体读取）。每次协调器更新前会被清空。
        self.failures = []

    def _record_failure(self, interface, gs, error, url=None, body=None):
        """记录一次接口调用失败，供「集成状态」诊断实体聚合展示。

        interface: 接口标识（account_list / invoice_list / yibiao_data）
        gs:        户号；整集成级接口（account_list）传 None
        error:     异常对象，转 str 后存入
        url/body:  显式覆盖请求地址 / 请求体；不传时优先取异常上挂的 request 上下文
                   （_call_api 失败时挂在 error.request），再退化为 None

        记录字段：
            interface / gs / error / time
            method / url / headers / body  —— 请求详情（method 目前恒为 POST）
        """
        # 请求上下文：_call_api 抛的异常上挂着 error.request
        req = getattr(error, "request", None) or {}
        record = {
            "interface": interface,
            "gs": gs,
            "error": str(error),
            "time": dt_util.utcnow(),
            "method": req.get("method", "POST"),
            "url": url if url is not None else req.get("url"),
            "headers": req.get("headers"),
            "body": body if body is not None else req.get("body"),
        }
        self.failures.append(record)

    def _get_auth_headers(self):
        """构造通用的 API 认证请求头。"""
        data = self.entry.data
        openid = data[CONF_OPENID]
        unionid = data[CONF_UNIONID]
        user_name = data[CONF_USER_NAME]

        user_info = {"UserName": user_name, "ApplicationId": APPLICATION_ID}
        cookie_value = f"UserInfo={urllib.parse.quote(json.dumps(user_info))}"
        # 经测试这样传参也是可以的，cookie_value="UserInfo={}"
        return {
            "openid": openid,
            "unionid": unionid,
            "cookie": cookie_value,
            "Content-Type": "application/json",
        }

    async def _call_api(self, url, body="{}", method="POST"):
        """发送 API 请求并返回解析后的 JSON 数据。

        url:    完整请求地址（含 query string）
        body:   已序列化的 JSON 字符串；不传时默认发送空对象 "{}"（兼容既有接口）
        method: 请求方法，默认 POST（当前所有济南水务接口均为 POST）

        请求失败或业务状态异常时抛出 UpdateFailed，异常对象上挂有 request 上下文
        （method / url / headers / body），供「集成状态」诊断实体展示。
        """
        session = async_get_clientsession(self.hass)
        headers = self._get_auth_headers()

        async with session.post(url, headers=headers, data=body) as response:
            if response.status != 200:
                raise self._api_error(
                    f"API 请求失败，HTTP 状态码: {response.status}",
                    method,
                    url,
                    headers,
                    body,
                )

            result = await response.json()

            state = result.get("state") or result.get("State")
            if not state:
                raise self._api_error(
                    f"API 请求失败: {result.get('messageText', result.get('Message', '未知错误'))}",
                    method,
                    url,
                    headers,
                    body,
                )

            return result

    @staticmethod
    def _api_error(message, method, url, headers, body):
        """构造带请求上下文的 UpdateFailed（供诊断实体展示请求详情）。"""
        error = UpdateFailed(message)
        # 挂到属性而非写进 message，保持 error 文案与日志简洁；_record_failure 会按需取出。
        error.request = {
            "method": method,
            "url": url,
            "headers": headers,
            "body": body,
        }
        return error

    async def fetch_account_list(self, phone_num):
        """获取账户级数据（用户绑定的所有户号信息）。

        失败不再整体抛出 UpdateFailed（否则所有实体会变 unavailable）；改为记录失败、
        返回空列表，由「集成状态」实体汇总展示。
        """
        url = f"{API_BASE_URL}{API_ENDPOINT}?PhoneNum={phone_num}"
        try:
            result = await self._call_api(url)
            return result.get("data") or []
        except Exception as error:
            _LOGGER.warning("获取账户列表失败: %s", error)
            self._record_failure("account_list", None, error, url=url)
            return []

    async def fetch_invoice_list(self, gs):
        """获取单个户号的账单级数据（全部记录，供订单详情传感器使用）。

        单户号失败不影响整体，返回空列表并打 warning。
        """
        url = f"{API_BASE_URL}{API_ENDPOINT_FAPIAO}?GS={gs}"
        try:
            result = await self._call_api(url)
            return result.get("data") or []
        except Exception as error:
            _LOGGER.warning("获取户号 %s 账单失败: %s", gs, error)
            self._record_failure("invoice_list", gs, error, url=url)
            return []

    async def fetch_yibiao_data(self, gs):
        """获取指定户号的实时仪表日用水数据。

        流程：
        1. 调用 GetYiBiaoInfo 取得 jsonData（字符串化 JSON 数组，含各数据文件标识）；
        2. 取出 InfoName 为 YibiaoSLInfo 的项；
        3. 以其作为 body 调用 GetDataList，返回 data（字符串化 JSON 数组，即日用水记录）。

        失败返回空列表并打 warning。
        """
        try:
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
            yibiao_body_str = json.dumps(yibiao_body, ensure_ascii=False)
            yibiao_result = await self._call_api(yibiao_url, yibiao_body_str)

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
            yibiao_info_str = json.dumps(yibiao_info, ensure_ascii=False)
            data_result = await self._call_api(data_list_url, yibiao_info_str)

            data = data_result.get("data")
            if not data:
                return []
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, list):
                return []

            return data
        except Exception as error:
            _LOGGER.warning("获取户号 %s 仪表数据失败: %s", gs, error)
            # 两步串行，失败点不固定：请求上下文由 _call_api 挂在异常上；
            # 若异常不带上下文（如 json 解析失败），则回退到实际已发出的最后一个请求。
            last_body = yibiao_info_str if yibiao_info else yibiao_body_str
            last_url = data_list_url if yibiao_info else yibiao_url
            self._record_failure(
                "yibiao_data", gs, error, url=last_url, body=last_body
            )
            return []

    def transform_invoice_records(self, records):
        """将原始账单记录列表筛选/重命名后返回（供订单详情传感器使用）。"""
        return [_transform_invoice_record(rec) for rec in records]
