"""
济南水务 Home Assistant 集成 - 常量定义模块

本模块集中定义了集成中使用的所有常量，包括：
1. 集成域（DOMAIN）和名称
2. 配置字段名称常量
3. API 相关常量
4. 服务名称常量

=== 为什么使用常量而非硬编码字符串 ===

1. 避免拼写错误：在不同模块间引用同一字符串时，使用常量可以借助 IDE 的类型检查
2. 便于修改：如果需要改名字段，只需改一处
3. 代码可读性：CONF_OPENID 比 "openid" 更能表达意图
"""

# ============================================================
# 集成基本信息
# ============================================================

# 集成域（domain）
# 必须与 manifest.json 中的 domain 和文件夹名一致
# HA 通过 domain 来唯一标识一个集成
DOMAIN = "jinan_water"

# 集成显示名称
NAME = "济南水务"

# ============================================================
# 配置字段名称常量
# 这些常量用于 config_flow.py 和 __init__.py 中，
# 作为配置条目（ConfigEntry.data）的 key
# ============================================================

# 微信小程序 OpenID（用户唯一标识）
CONF_OPENID = "openid"

# 微信小程序 UnionID（跨应用唯一标识）
CONF_UNIONID = "unionid"

# 用户姓名（用于 API Cookie 中的 UserInfo）
CONF_USER_NAME = "user_name"

# 用户手机号（作为 API 请求参数 PhoneNum）
CONF_PHONE_NUM = "phone_num"

# 用户选择的户号列表（配置流第二步中通过复选框选择）
# 这里的值对应 API 返回数据中 data[].gs 字段
CONF_SELECTED_GS = "selected_gs"

# ============================================================
# API 相关常量
# 济南水务微信小程序后端 API 配置
# ============================================================

# 应用 ID（ApplicationId）
# 这是济南水务微信小程序的应用标识，用于 API Cookie 认证
APPLICATION_ID = "67532d903748124e443298ca"

# API 基础地址
API_BASE_URL = "https://yx.jinanwater.cn"

# API 接口路径
# GetBangDingList 接口用于获取用户绑定的所有户号信息（账户级数据）
# 完整请求地址: https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetBangDingList
API_ENDPOINT = "/shoufeizjj3/api/WxProgramApi/GetBangDingList"

# GetFaPiaoList 接口用于获取单个户号的账单/用量详情（本期数据）
# 请求地址: https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetFaPiaoList?GS=户号
API_ENDPOINT_FAPIAO = "/shoufeizjj3/api/WxProgramApi/GetFaPiaoList"

# GetYiBiaoInfo 接口用于获取实时仪表信息（按户号查询，返回 jsonData 指向的数据文件清单）
# 完整请求地址: https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetYiBiaoInfo?Type=SS
API_ENDPOINT_GetYiBiaoInfo = "/shoufeizjj3/api/WxProgramApi/GetYiBiaoInfo?Type=SS"

# GetDataList 接口用于获取仪表数据（日用水明细，需先由 GetYiBiaoInfo 的 jsonData 取得文件标识）
# 完整请求地址: https://yx.jinanwater.cn/shoufeizjj3/api/WxProgramApi/GetDataList
API_ENDPOINT_GetDataList = "/shoufeizjj3/api/WxProgramApi/GetDataList"

# 合并数据中使用的数据键：实时仪表日用水记录列表
YIBIAO_DATA_KEY = "yibiao_data"

# 合并数据中使用的数据键：订单（账单）详情列表（全量记录，已筛选并重命名字段）
ORDER_DETAIL_KEY = "order_detail"

# ============================================================
# 本地持久化（日用水历史）相关常量
# 仪表接口只返回「今天往前 1 个月」的日用水数据，更早的数据需要本地累积，
# 因此每次同步会把接口数据并入 HA 原生存储 Store（见 history.py）。
# ============================================================

# HA 原生存储（homeassistant.helpers.storage.Store）配置
# Store 会把数据写入 <config>/.storage/<STORAGE_KEY>，由 HA 负责把 IO 调度到执行器线程、
# 自带「先写临时文件再替换」的原子写入与 version 版本管理，比手写裸文件更符合规范。
# 关键点：STORAGE_KEY 用「域/文件名」的形式即可让 Store 在 .storage 下创建子目录，
# 最终文件：<config>/.storage/jinan_water/daily_history.json
# （该用法参考既有项目 github.com/mingyue5826/tongwangas_shandong 的写法）
STORAGE_KEY = f"{DOMAIN}/daily_history.json"
STORAGE_VERSION = 1

# 日用水历史最多保留的天数（超出后按日期裁剪最旧的记录）
MAX_HISTORY_DAYS = 730

# ============================================================
# 服务名称常量
# 用于注册自定义服务，用户可在 HA "开发者工具 > 服务" 中调用
# 服务完整名称格式: domain.service_name（如 jinan_water.refresh_data）
# ============================================================

# 手动刷新数据服务
SERVICE_REFRESH_DATA = "refresh_data"

# ============================================================
# 前端卡片（Lovelace 自定义卡片）相关常量
# 卡片随集成分发，由 frontend.py 在集成启动时自动注册，
# 用户无需手动复制 js、也无需手动在「设置 → 仪表盘 → 资源」里添加 URL
# ============================================================

# 卡片 js 文件名（随集成发布在 custom_components/jinan_water/www/ 下）
CARD_JS_FILENAME = "jinan-water-card.js"

# 卡片通过 HA HTTP 静态路径对外暴露的 URL
# 浏览器可直接访问验证：http(s)://<HA地址>/jinan_water/jinan-water-card.js
CARD_URL_PATH = f"/{DOMAIN}/{CARD_JS_FILENAME}"

# 卡片的自定义元素名，仪表盘里写 type: custom:jinan-water-card
CARD_ELEMENT_NAME = "jinan-water-card"

# 旧的手工部署地址前缀
# 用于识别用户此前手动添加到 Lovelace 的资源，自动迁移到新的静态路径，
# 避免同一张卡片被加载两次（表现为卡片行为异常、改动不生效）
CARD_LEGACY_URL_PREFIXES = (
    "/local/community/jinan-water-card/",
    "/local/jinan_water/",
    "/local/jinan-water-card.js",
    "/hacsfiles/jinan-water-card/",
)
