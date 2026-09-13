"""济南水务 Home Assistant 集成 - 公共辅助函数

集中放置被多个平台（sensor / button）复用的纯函数，避免跨文件复制粘贴。
"""

from .const import DOMAIN


def build_device_info(entry, gs, data):
    """根据户号构造 HA 设备信息（identifiers 用于把多个实体归入同一设备卡片）。

    entry: ConfigEntry（用于取 entry_id 作为设备标识的一部分）
    gs:    户号
    data:  协调器当前数据（coordinator.data），用于取该户号的门牌/户名
    """
    gs_data = data.get(gs, {})
    mp = gs_data.get("mp", "")  # 门牌
    hm = gs_data.get("hm", "")  # 户名

    return {
        "identifiers": {(DOMAIN, entry.entry_id, gs)},
        "name": mp if mp else f"济南水务 - {gs}",
        "manufacturer": "济南水务集团",
        "model": f"户号: {hm} - {gs}",
    }
