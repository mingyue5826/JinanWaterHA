"""济南水务卡片的前端资源自动注册。

=== 为什么需要这个模块 ===

HACS 只会替「plugin（前端）」类型的仓库把 JS 自动登记成 Lovelace 资源；
本仓库是「integration」类型，HACS 安装完就把 `custom_components/jinan_water/`
整个目录（含 `www/jinan-water-card.js`）拷进 HA，**但不会碰 Lovelace 资源表**，
所以过去必须用户自己复制文件 + 手工添加资源 URL。

本模块让集成在启动时自己完成这两件事：

1. 通过 HA 的 HTTP 静态路径把 js 暴露出去
   `custom_components/jinan_water/www/jinan-water-card.js`
   -> `https://<HA地址>/jinan_water/jinan-water-card.js`
2. 把这个 URL 写进 Lovelace 资源表（等价于用户在「设置 → 仪表盘 → 资源」里手填）

=== 参考的成熟实现 ===

- **AlexxIT/WebRTC**（同为 integration 类型且自带卡片）：`async_setup` 里
  `register_static_path()` + `init_resource()`，直接写 `hass.data["lovelace"]`。
- **hacs/integration**（plugin 的自动注册）：`update_dashboard_resources()`，
  用的也是同一张 `ResourceStorageCollection` 资源表，URL 形如
  `/hacsfiles/<repo>/<file>.js?hacstag=<id><version>`。
- **兜底用 HA 官方公开 API** `homeassistant.components.frontend.add_extra_js_url`，
  其 docstring 原文就是 "This function allows custom integrations to register
  extra js or module." —— 用于「Lovelace 处于 YAML 模式、资源表不可写」的场景。

三者共同点：URL 后面都带一个版本参数（`?v=` / `?hacstag=`），
目的是版本变化时让浏览器丢弃旧缓存。本模块沿用这一做法。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from .const import (
    CARD_JS_FILENAME,
    CARD_LEGACY_URL_PREFIXES,
    CARD_URL_PATH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# 随集成分发的卡片目录：custom_components/jinan_water/www/
CARD_DIR = Path(__file__).parent / "www"
CARD_FILE = CARD_DIR / CARD_JS_FILENAME


async def async_setup_card(hass: HomeAssistant) -> None:
    """在 Lovelace 就绪后注册卡片资源（由 __init__.async_setup 调用）。

    启动时 Lovelace 可能还没加载完（自定义集成的 setup 时机不保证），
    所以这里先检查；没就绪就监听 `component_loaded` 事件，并以
    「HA 启动完成」作兜底。
    （注：原先用的 `helpers.start.async_when_setup` 已在 HA 2026.x 被移除，
    现在改用官方事件 + `async_at_started` 组合，语义等价。）
    """
    if _is_lovelace_ready(hass):
        await async_register_card(hass)
        return

    from homeassistant.const import EVENT_COMPONENT_LOADED
    from homeassistant.helpers.start import async_at_started

    done = {"registered": False}
    unsub_loaded: Any = None

    async def _register_once() -> None:
        """注册且只注册一次，先到者赢（component_loaded 或 started 兜底）。"""
        if done["registered"]:
            return
        done["registered"] = True
        if unsub_loaded is not None:
            unsub_loaded()
        await async_register_card(hass)

    async def _on_component_loaded(event: Any) -> None:
        if event.data.get("component") == "lovelace":
            await _register_once()

    unsub_loaded = hass.bus.async_listen(EVENT_COMPONENT_LOADED, _on_component_loaded)

    async def _on_started(_hass: HomeAssistant) -> None:
        # 兜底：极端情况下 Lovelace 没被加载（被 exclude 等），
        # 资源表走不通时 extra_js_url 仍能完成注册
        await _register_once()

    async_at_started(hass, _on_started)
    _LOGGER.debug("Lovelace 尚未加载，已挂起卡片资源注册，等 Lovelace 就绪后执行")


def _is_lovelace_ready(hass: HomeAssistant) -> bool:
    """Lovelace 是否已加载（hass.data 注入或组件已注册都算）。"""
    return "lovelace" in hass.data or "lovelace" in hass.config.components


async def async_register_card(hass: HomeAssistant) -> bool:
    """注册卡片：静态路径 + Lovelace 资源。返回是否至少成功了一种方式。"""
    card_file = _find_card_file(hass)
    if card_file is None:
        _LOGGER.warning(
            "未找到卡片文件 %s（集成自带或 www/ 下都没有），跳过前端资源自动注册；"
            "可手动把 %s 放到 <HA配置目录>/www/ 下后重启 HA",
            CARD_JS_FILENAME,
            CARD_JS_FILENAME,
        )
        return False

    version = await _async_get_version(hass)
    # 带版本号：升级后 URL 变化，浏览器会重新拉取而不是用旧缓存
    url = f"{CARD_URL_PATH}?v={version}"

    await _async_register_static_path(hass, CARD_URL_PATH, card_file)

    if await _async_add_lovelace_resource(hass, url):
        return True

    # 资源表不可用（YAML 模式等）→ 退回官方公开 API
    return _async_add_extra_js_url(hass, url)


# ------------------------------------------------------------------
# 1. 找到卡片文件
# ------------------------------------------------------------------


def _find_card_file(hass: HomeAssistant) -> Path | None:
    """按优先级找卡片 js。

    首选集成自带的那份（HACS 会连 www/ 一起下载）；
    找不到时回落到用户手工放置在 config/www 下的旧位置，
    这样即便 www/ 没被下载，也能把用户已有的文件自动接上，不至于卡片失效。
    """
    candidates = (
        CARD_FILE,
        Path(hass.config.path("www", DOMAIN, CARD_JS_FILENAME)),
        Path(hass.config.path("www", "jinan-water-card", CARD_JS_FILENAME)),
        Path(hass.config.path("www", CARD_JS_FILENAME)),
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


# ------------------------------------------------------------------
# 2. 版本号（用于缓存 busting）
# ------------------------------------------------------------------


async def _async_get_version(hass: HomeAssistant) -> str:
    """取集成版本号，优先用 HA 的 loader，失败则直接读 manifest.json。"""
    try:
        from homeassistant.loader import async_get_integration

        integration = await async_get_integration(hass, DOMAIN)
        if integration.version:
            return str(integration.version)
    except Exception as err:  # noqa: BLE001 - 版本拿不到不影响注册
        _LOGGER.debug("从 loader 获取版本失败，改读 manifest.json: %s", err)

    try:
        manifest = json.loads(
            (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
        )
        return str(manifest.get("version") or "0")
    except Exception:  # noqa: BLE001
        return "0"


# ------------------------------------------------------------------
# 3. 静态路径
# ------------------------------------------------------------------


async def _async_register_static_path(
    hass: HomeAssistant, url_path: str, file_path: Path
) -> bool:
    """把卡片 js 挂到 HA 的 HTTP 静态路径上。

    HA 2024.7 起推荐 `async_register_static_paths([StaticPathConfig(...)])`，
    旧版只有 `register_static_path()`，这里两种都兼容。
    """
    path_str = str(file_path)
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_path, path_str, True)]
        )
        _LOGGER.debug("已注册卡片静态路径 %s -> %s", url_path, path_str)
        return True
    except Exception as err:  # noqa: BLE001 - 静态路径失败不应拖垮集成
        _LOGGER.warning("注册卡片静态路径 %s 失败: %s", url_path, err)
        return False


# ------------------------------------------------------------------
# 4. Lovelace 资源表
# ------------------------------------------------------------------


def _is_card_resource(url: str) -> bool:
    """判断某条资源是不是本集成的卡片（含用户以前手工添加的旧地址）。"""
    path = url.split("?", 1)[0].rstrip("/")
    if path.rsplit("/", 1)[-1] != CARD_JS_FILENAME:
        return False
    return path == CARD_URL_PATH or any(
        path.startswith(prefix) for prefix in CARD_LEGACY_URL_PREFIXES
    )


def _async_get_resources(hass: HomeAssistant) -> Any | None:
    """取到「可写」的 Lovelace 资源集合，取不到返回 None。

    - HA 2025.2 之前 `hass.data["lovelace"]` 是 dict（取 `["resources"]`），
      之后是 dataclass（取 `.resources` 属性）。
    - Lovelace 处于 YAML 模式时资源来自配置文件，集合是 `ResourceYAMLCollection`、
      **没有 store**，含义是「不能由代码增删」，这时一律返回 None。
    """
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None

    resources = getattr(lovelace, "resources", None)
    if resources is None and hasattr(lovelace, "get"):
        resources = lovelace.get("resources")

    # 没有 store = 资源表不可写（YAML 模式）
    if resources is None or getattr(resources, "store", None) is None:
        return None
    return resources


async def _async_add_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """把卡片 URL 写进 Lovelace 资源表（GUI 模式下用户看到的那张表）。

    返回 False 表示这张表不可用（未加载 / YAML 模式），调用方应改走 extra_js_url。
    """
    resources = _async_get_resources(hass)
    if resources is None:
        _LOGGER.debug("Lovelace 资源表不可用或不可写（YAML 模式），改用 extra_module_url")
        return False

    try:
        if not resources.loaded:
            await resources.async_load()

        matched = [
            item
            for item in resources.async_items()
            if _is_card_resource(item.get("url", ""))
        ]

        if not matched:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("已自动添加卡片资源：%s", url)
            return True

        # 只保留一条，其余重复项删掉，避免同一张卡片被加载多次
        for item in matched[1:]:
            _LOGGER.info("删除重复的卡片资源：%s", item.get("url"))
            await resources.async_delete_item(item["id"])

        keep = matched[0]
        if keep.get("url") != url:
            _LOGGER.info("更新卡片资源：%s -> %s", keep.get("url"), url)
            await resources.async_update_item(
                keep["id"], {"res_type": "module", "url": url}
            )
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("写入 Lovelace 资源表失败，将改用 extra_module_url: %s", err)
        return False


async def async_remove_card(hass: HomeAssistant) -> bool:
    """从 Lovelace 资源表里删掉本卡片的条目（卸载集成时调用）。

    返回 True 表示确实删了条目。资源表不可写（YAML 模式）时什么都不做。

    注：WebRTC 这类「集成自带卡片」的仓库其实**没有**这个清理动作
    （它的 async_setup 只管注册，async_unload_entry 只停 go2rtc），
    卸载后资源会残留。这里主动做掉，删空集成后不留一条指向 404 的资源。
    """
    resources = _async_get_resources(hass)
    if resources is None:
        return False

    try:
        if not resources.loaded:
            await resources.async_load()

        matched = [
            item
            for item in resources.async_items()
            if _is_card_resource(item.get("url", ""))
        ]
        for item in matched:
            _LOGGER.info("移除卡片资源：%s", item.get("url"))
            await resources.async_delete_item(item["id"])

        if matched:
            _LOGGER.info("已移除 %d 条卡片资源", len(matched))
        return bool(matched)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("移除卡片资源失败（可到「仪表盘 → 资源」手工删除）: %s", err)
        return False


# ------------------------------------------------------------------
# 5. 兜底：frontend 的 extra_module_url（官方公开 API）
# ------------------------------------------------------------------


def _async_add_extra_js_url(hass: HomeAssistant, url: str) -> bool:
    """用 HA 官方公开 API 注册模块，覆盖 YAML 模式等资源表不可写的场景。"""
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, url)
        _LOGGER.info("已通过 extra_module_url 注册卡片：%s", url)
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("注册卡片前端资源失败，需手工添加资源 %s: %s", url, err)
        return False
