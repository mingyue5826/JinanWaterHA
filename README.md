# 济南水务（JinanWater）
![济南水务](custom_components/jinan_water/brand/logo.png)

## 安装集成

### 方式一：HACS

[![Open your Home Assistant instance and add this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mingyue5826&repository=JinanWaterHA&category=integration)

点上面的按钮一键添加，或者手动操作：

1. 在 Home Assistant 中打开 **HACS**。
2. 进入 **集成** → 右上角菜单（⋮）→ **自定义仓库**。
3. 添加仓库 `https://github.com/mingyue5826/JinanWaterHA`，类别选 **集成（Integration）**。
4. 在 **济南水务** 卡片中点击 **下载**。
5. 按提示 **重启** Home Assistant。

> 仪表盘卡片**已内置在集成包里**（`jinan-water-card.js`），HACS 下载 release 包时会一并带上，
> 重启后自动注册为 Lovelace 资源，**无需手工复制 js、也无需手工添加资源 URL**。

### 方式二：手动安装

1. 到 [Releases](https://github.com/mingyue5826/JinanWaterHA/releases) 下载 **`jinan_water-manual.zip`**
   （⚠️ 别下 `jinan_water.zip`——那个是给 HACS 专用的平铺包，解压后会多套一层目录）。
2. 解压得到 `jinan_water/` 目录，把它**整个**复制到：

   `config/custom_components/jinan_water/`

   ⚠️ 请确认里面的 `www/` 目录（内含 `jinan-water-card.js`）也一并复制，否则卡片无法自动注册。

3. **重启** Home Assistant。

## 添加设备

1. 打开 **设置** → **设备与服务** → **添加集成**。
2. 搜索 **济南水务**（或 **JinanWater**）并选择。
3. 输入以下信息（信息获取方式见[]()）。
   - openid
   - unionid
   - 微信实名姓名
   - 微信实名手机号
4. 勾选要添加的一个或多个 **户号**，完成向导。

### 信息获取方式

配置信息需要小程序抓包，建议用电脑端微信小程序进行抓包，手机抓包需要root或其他复杂方式

1. 选择适合自己设备的架构和版本下载并安装。[下载链接](https://reqable.com/zh-CN/download/)
2. 启动抓包工具
3. 打开微信小程序，进入济南水务，用微信账号进行登录
4. 在抓包工具中搜索`https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetBangDingList`
5. 双击抓包结果，在右侧找到`请求头`
6. 请求头中就存在`openid`和`unionid`

![抓包截图](Reqable.png)

## 使用仪表盘卡片

卡片随集成分发，**重启 HA 后即自动可用**，无需任何手工配置。

1. 验证资源已注册：**设置 → 仪表盘 → 右上角 ⋮ → 资源**，应能看到一条：
   - URL：`/jinan_water/jinan-water-card.js?v=1.0.0`（`?v=` 是集成版本号，升级后会变）
   - 类型：**JavaScript 模块**
2. 在仪表盘里添加卡片，手动填：

   ```yaml
   type: custom:jinan-water-card
   gs: "6422376"   # 户号；不填会自动探测
   ```

   可选配置：`title`、`price`（单价）、`ladder`（年阶梯三档）、`default_panel`、`entities`。

### 它是怎么自动注册的

集成启动时会做两件事（见 `custom_components/jinan_water/frontend.py`）：

| 步骤 | 做法 |
|---|---|
| 暴露 js | 用 HA 的 HTTP 静态路径把 `www/jinan-water-card.js` 挂到 `/jinan_water/jinan-water-card.js` |
| 登记资源 | 把带版本号的 URL 写进 Lovelace 资源表（等价于在「资源」页面手工添加） |

- URL 带 `?v=<版本号>`：升级集成后版本号变化，浏览器会丢弃旧缓存重新拉取。
- **旧的手工资源会被自动迁移**：如果你之前手工添加过
  `/local/community/jinan-water-card/jinan-water-card.js` 之类的地址，重启后会被改写成新地址，
  重复的多条也会清理成一条，避免同一张卡片被加载两遍。
- **Lovelace 处于 YAML 模式**（`lovelace: mode: yaml`）时资源表不可写，会自动改用 HA 官方的
  `frontend.extra_module_url` 加载卡片，同样不需要手工操作。

### 升级与卸载

**升级**：版本号变化 → 资源 URL 的 `?v=` 跟着变 → 浏览器重新拉取 js。
资源表里**始终只有一条**：旧的那条会被**改写**成新 URL，不会新增第二条。升级后建议 Ctrl+F5。

**卸载**：在 HA 里删除本集成的**最后一个**配置条目时，会自动把卡片资源一并删掉，不留指向 404 的残留。

- 还留着其它配置条目时资源会保留（卡片还要继续用）。
- ⚠️ 若你是用 HACS **直接删文件**、没先在 HA 里删条目：HA 重启后找不到集成代码，这个清理钩子没法执行
  （HA 自身在集成缺失时会跳过 `async_remove_entry`），此时需到「设置 → 仪表盘 → 资源」手动删掉那条
  `/jinan_water/jinan-water-card.js`。**建议先在 HA 里删集成条目，再删文件。**

### 排障

| 现象 | 处理 |
|---|---|
| `Custom element doesn't exist: jinan-water-card` | 浏览器直接访问 `http://<HA地址>/jinan_water/jinan-water-card.js`，能下载到 js 说明静态路径正常；然后 **Ctrl+F5 硬刷新**。仍不行就查日志里 `jinan_water` 是否有「已自动添加卡片资源 / 注册卡片静态路径失败」 |
| 改了 js 但界面没变 | URL 的 `?v=` 只在版本号变化时更新；HACS 升级后记得 **Ctrl+F5** |
| 资源表里出现两条 | 不会，重复的会被自动清理；若手工删过资源，重启 HA 会重新自动添加 |

