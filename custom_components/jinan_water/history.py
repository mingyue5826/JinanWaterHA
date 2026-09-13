"""济南水务 Home Assistant 集成 - 日用水历史本地持久化模块

=== 为什么需要本地持久化 ===

仪表接口（GetYiBiaoInfo / GetDataList）只返回「今天往前 1 个月」的日用水记录，
更早的数据接口不再返回。因此每次同步时把接口数据并入本地历史文件，
即可让「用水详情」的 graph 随着时间推移累积成完整的历史曲线。

=== 落盘位置 ===

    <config>/jinan_water/daily_history.json

放在 HA 配置目录下可见的 jinan_water 文件夹、且使用 .json 后缀，
用户可以直接打开查看 / 备份，比 .storage 里的隐藏无扩展名文件方便得多。
文件采用「先写临时文件再原子替换」的方式写入，避免写入中断导致文件损坏。

=== 文件结构 ===

```json
{
  "version": 1,
  "accounts": {
    "<户号>": {
      "2026-09-02": { "date": "2026-09-02", "value": 0.03, "ZhiDu": 9.63, ... },
      ...
    }
  }
}
```

=== 合并规则 ===

1. 以日期（YYYY-MM-DD）为主键，接口返回的记录写入/覆盖本地对应日期；
2. 接口偶尔会返回 0 值的占位记录，此时不覆盖本地已有的非 0 值（避免历史被抹掉）；
3. 超过 MAX_HISTORY_DAYS 天的旧记录自动裁剪（按日期保留最新的 N 条）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from .const import (
    HISTORY_DIR,
    HISTORY_FILENAME,
    HISTORY_FORMAT_VERSION,
    MAX_HISTORY_DAYS,
)

_LOGGER = logging.getLogger(__name__)

# 参与「零值保护」的字段：接口若返回 0，而本地已有非 0 值，则保留本地的值
_ZERO_GUARD_FIELDS = ("value", "ZhiDu", "value3")


def normalize_record_date(value):
    """把接口返回的日期规范化为 YYYY-MM-DD。

    接口会返回形如 "2026-09-02 00" 的字符串（末尾带 " 00" 后缀），
    这里统一去掉后缀并截取日期部分；无法识别时返回 None。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(" 00"):
        text = text[:-3].strip()
    if len(text) < 10:
        return None
    date_part = text[:10]
    # 简单校验：YYYY-MM-DD
    parts = date_part.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return date_part


def _is_zero(value):
    """判断数值是否为 0（None / 非数字 / 0 均视为「空值」）。"""
    if value is None:
        return True
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return True


class DailyHistoryStore:
    """日用水历史的本地持久化存储器。

    协调器每次同步时调用 async_merge()：
    传入接口返回的原始记录列表，拿回「本地历史 ∪ 接口数据」的完整记录列表。

    落盘文件：<config>/jinan_water/daily_history.json
    """

    def __init__(self, hass):
        self.hass = hass
        self._path = hass.config.path(HISTORY_DIR, HISTORY_FILENAME)
        self._data = None
        self._lock = None

    @property
    def path(self):
        """返回历史文件的绝对路径（供日志 / 诊断使用）。"""
        return self._path

    def _get_lock(self):
        """惰性创建 asyncio.Lock（必须在事件循环内创建）。"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # 磁盘读写（同步 IO，由 HA 放到执行器线程里跑，避免阻塞事件循环）
    # ------------------------------------------------------------------

    def _read_file(self):
        """从磁盘读取历史文件；文件不存在或损坏时返回空字典。"""
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError, ValueError) as error:
            _LOGGER.warning(
                "读取日用水历史文件失败，将重建（%s）：%s", self._path, error
            )
            return {}

        if isinstance(payload, dict):
            accounts = payload.get("accounts")
            if isinstance(accounts, dict):
                return accounts
            # 兼容早期「直接是 户号 -> 记录 字典」的旧结构
            return payload
        return {}

    def _write_file(self, accounts):
        """原子写入历史文件（先写 .tmp 再替换），并确保目录存在。"""
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        payload = {"version": HISTORY_FORMAT_VERSION, "accounts": accounts}
        tmp_path = f"{self._path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self._path)

    # ------------------------------------------------------------------
    # 对外异步接口
    # ------------------------------------------------------------------

    async def async_load(self):
        """读取存储内容（首次调用时从磁盘加载，之后走内存缓存）。"""
        if self._data is None:
            self._data = await self.hass.async_add_executor_job(self._read_file)
        return self._data

    async def async_merge(self, gs, records):
        """把接口返回的日用水记录并入本地历史。

        :param gs: 户号
        :param records: 接口返回的原始日用水记录列表（可能为空）
        :return: 合并后的完整记录列表，按日期升序排列
        """
        lock = self._get_lock()
        async with lock:
            data = await self.async_load()

            bucket = data.get(gs)
            if not isinstance(bucket, dict):
                bucket = {}
                data[gs] = bucket

            changed = False

            for record in records or []:
                if not isinstance(record, dict):
                    continue
                key = normalize_record_date(record.get("date"))
                if not key:
                    continue

                item = dict(record)
                item["date"] = key
                previous = bucket.get(key)

                if previous is None:
                    bucket[key] = item
                    changed = True
                    continue

                merged = {**previous, **item}
                # 零值保护：接口返回 0 时不覆盖本地已有的非 0 值
                for field in _ZERO_GUARD_FIELDS:
                    if _is_zero(item.get(field)) and not _is_zero(previous.get(field)):
                        merged[field] = previous.get(field)

                if merged != previous:
                    bucket[key] = merged
                    changed = True

            # 裁剪超期记录（按日期保留最新的 MAX_HISTORY_DAYS 条）
            if len(bucket) > MAX_HISTORY_DAYS:
                for stale_key in sorted(bucket)[:-MAX_HISTORY_DAYS]:
                    bucket.pop(stale_key, None)
                changed = True

            if changed:
                await self.hass.async_add_executor_job(self._write_file, data)
                _LOGGER.debug(
                    "户号 %s 日用水历史已更新并写入 %s，累计 %d 条记录",
                    gs,
                    self._path,
                    len(bucket),
                )

            return [bucket[key] for key in sorted(bucket)]

    async def async_history_count(self, gs):
        """返回本地已保存的记录条数（供日志/诊断使用）。"""
        data = await self.async_load()
        bucket = data.get(gs) or {}
        return len(bucket) if isinstance(bucket, dict) else 0
