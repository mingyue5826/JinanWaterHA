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

# ============================================================
# 服务名称常量
# 用于注册自定义服务，用户可在 HA "开发者工具 > 服务" 中调用
# 服务完整名称格式: domain.service_name（如 jinan_water.refresh_data）
# ============================================================

# 手动刷新数据服务
SERVICE_REFRESH_DATA = "refresh_data"
