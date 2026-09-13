/**
 * 济南水务卡片（jinan-water-card）
 * ============================================================================
 * 与集成 jinan_water 配套的前端卡片：展示水费余额/欠费/违约金、本期用水与费用、
 * 日用水曲线、年用水阶梯、水费日历、订单（账单）列表及费用明细。
 *
 * 设计要点
 * 1. 零依赖单文件：不内联任何图表库，曲线用原生 SVG 手绘（原国家电网卡片内联了 700KB
 *    的 ApexCharts + Lit，这里刻意避开，便于维护和排错）。
 * 2. 数据全部来自集成实体，不做任何接口请求；日用水历史的“补齐”由集成侧持久化完成
 *    （接口只返回近 1 个月，更早的数据由集成写入 config/jinan_water/daily_history.json
 *    后合并进「用水详情」实体）。
 * 3. 实体 id 约定：sensor.jinan_water_<key>_<gs>，可用 entities 覆盖任意一项。
 *
 * 配置示例（YAML）
 * ```yaml
 * type: custom:jinan-water-card
 * gs: "6422376"          # 户号；不填则自动探测第一个 jinan_water 设备
 * title: 济南水务
 * price: 4.20            # 单价覆盖；不填则读「本期水价」实体
 * ladder:                # 年用水阶梯 3 档（不填用默认档位）
 *   - { name: 第一阶梯, from: 0,   to: 96 }
 *   - { name: 第二阶梯, from: 97,  to: 192 }
 *   - { name: 第三阶梯, from: 193, to: null }
 * default_panel: ""      # 默认展开："" | "calendar" | "dayChart" | "orders"
 * ```
 */

const CARD_VERSION = "1.1.2";
const DOMAIN = "jinan_water";

/* ============================================================================
 * 实体 key -> 实体 id 后缀（与 sensor.py / button.py 中的 _sensor_key 一一对应）
 * 实体 id 形如 sensor.jinan_water_<后缀>_<户号>
 * ========================================================================== */
const ENTITY_SUFFIX = {
  balance: "balance",
  pending_fee: "pending_fee",
  penalty_fee: "penalty_fee",
  order_price: "order_price",
  usage: "usage",
  current_fee: "current_fee",
  yearly_usage: "yearly_usage",
  usage_detail: "usage_detail",
  order_detail: "order_detail",
  refresh_time: "refresh_time",
  usage_yesterday: "usage_yesterday",
  meter_yesterday: "meter_yesterday",
  latest_meter_date: "yesterday_meter_reading_date",
  order_meter_date: "order_meter_date",
  order_payment_date: "order_payment_date",
};

/* 各实体用途说明（仅供阅读/排查，不参与 id 拼接） */
const ENTITY_LABELS = {
  balance: "水费余额",
  pending_fee: "欠费金额",
  penalty_fee: "违约金",
  order_price: "本期水价",
  usage: "本期用水量",
  current_fee: "本期水费",
  yearly_usage: "年累计用水量",
  usage_detail: "用水详情（graph=日用水记录）",
  order_detail: "订单详情（graph=账单记录）",
  refresh_time: "上次同步时间",
  usage_yesterday: "昨日用水量",
  meter_yesterday: "昨日表读数",
  latest_meter_date: "最新抄表日期",
  order_meter_date: "本期抄表日期",
  order_payment_date: "本期缴费时间",
};

// 默认年用水阶梯（济南居民阶梯水量档位，可在卡片配置里改）
const DEFAULT_LADDER = [
  { name: "第一阶梯", from: 0, to: 96 },
  { name: "第二阶梯", from: 97, to: 192 },
  { name: "第三阶梯", from: 193, to: null },
];

// 配色（用水=蓝，费用=紫，与原国家电网卡片保持同一视觉语言）
const COLOR_USAGE = "#2f9be0";
const COLOR_COST = "#9575cd";
const COLOR_AVG = "#9e9e9e";
const COLOR_WARN = "#f59e0b";
const COLOR_OK = "#22c55e";

/* ============================================================================
 * 图标（内联 SVG path，避免依赖 ha-icon，预览页也能正常显示）
 * ========================================================================== */
const ICON_PATHS = {
  water: "M12,20A6,6 0 0,1 6,14C6,10 12,3.25 12,3.25C12,3.25 18,10 18,14A6,6 0 0,1 12,20Z",
  wallet:
    "M21,18V19A2,2 0 0,1 19,21H5C3.89,21 3,20.1 3,19V5A2,2 0 0,1 5,3H19A2,2 0 0,1 21,5V6H12C10.89,6 10,6.9 10,8V16A2,2 0 0,0 12,18M12,16H22V8H12M16,13.5A1.5,1.5 0 0,1 14.5,12A1.5,1.5 0 0,1 16,10.5A1.5,1.5 0 0,1 17.5,12A1.5,1.5 0 0,1 16,13.5Z",
  alert:
    "M11,15H13V17H11V15M11,7H13V13H11V7M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20Z",
  gavel: "M1,21H23L12,2L1,21M13,18H11V16H13V18M13,14H11V9H13V14Z",
  calendar:
    "M7,10H12V15H7M19,19H5V8H19M19,3H18V1H16V3H8V1H6V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5A2,2 0 0,0 19,3Z",
  chart:
    "M16,11.78L20.24,4.45L21.97,5.45L16.74,14.5L10.23,10.75L5.46,19H22V21H2V3H4V17.54L9.5,8L16,11.78Z",
  list: "M7,5H21V7H7V5M7,13V11H21V13H7M4,4.5A1.5,1.5 0 0,1 5.5,6A1.5,1.5 0 0,1 4,7.5A1.5,1.5 0 0,1 2.5,6A1.5,1.5 0 0,1 4,4.5M4,10.5A1.5,1.5 0 0,1 5.5,12A1.5,1.5 0 0,1 4,13.5A1.5,1.5 0 0,1 2.5,12A1.5,1.5 0 0,1 4,10.5M7,19V17H21V19H7M4,16.5A1.5,1.5 0 0,1 5.5,18A1.5,1.5 0 0,1 4,19.5A1.5,1.5 0 0,1 2.5,18A1.5,1.5 0 0,1 4,16.5Z",
  bolt: "M11,15H6L13,1V9H18L11,23V15Z",
  chevronDown: "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z",
  chevronUp: "M7.41,15.41L12,10.83L16.59,15.41L18,14L12,8L6,14L7.41,15.41Z",
  arrowLeft: "M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z",
  arrowRight: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
};

/** 生成内联 SVG 图标（默认 16px，跟随文字颜色）。 */
function icon(name, size = 16) {
  const path = ICON_PATHS[name] || ICON_PATHS.water;
  return `<svg class="ico" viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path d="${path}" fill="currentColor"/></svg>`;
}

/** 阶梯图标（手绘柱状，避免依赖不确定的 mdi 名称）。 */
function ladderIcon(size = 14) {
  const bars = [
    [1, 13, 3, 8],
    [6, 9, 3, 12],
    [11, 5, 3, 16],
    [16, 1, 3, 20],
  ];
  const rects = bars
    .map(([x, y, w, h]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1"/>`)
    .join("");
  return `<svg class="ico" viewBox="0 0 20 22" width="${size}" height="${size}" aria-hidden="true"><g fill="currentColor">${rects}</g></svg>`;
}

/* ============================================================================
 * 通用工具
 * ========================================================================== */
function num(value, fallback = null) {
  if (value === null || value === undefined || value === "" || value === "unknown" || value === "unavailable") {
    return fallback;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/** 金额格式化：固定两位小数。 */
function money(value, digits = 2) {
  const parsed = num(value, null);
  if (parsed === null) return "--";
  return parsed.toFixed(digits);
}

/** 水量格式化：去掉多余的小数尾巴（4.20 -> 4.2，49 -> 49）。 */
function volume(value, digits = 2) {
  const parsed = num(value, null);
  if (parsed === null) return "--";
  const fixed = parsed.toFixed(digits);
  return fixed.replace(/\.?0+$/, "") || "0";
}

/** 日期规范化：'2026-09-02 00' / '2026-09-02T00:00:00' -> '2026-09-02'。 */
function normalizeDate(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  let text = value.trim();
  if (text.endsWith(" 00")) text = text.slice(0, -3).trim();
  const datePart = text.slice(0, 10);
  const parts = datePart.split("-");
  if (parts.length !== 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  return datePart;
}

/** 把 ISO 时间转成 "YYYY-MM-DD HH:mm"；空值返回 null。 */
function formatDateTime(value) {
  if (!value || typeof value !== "string") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace("T", " ");
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function escapeHtml(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** 平滑曲线路径（Catmull-Rom 转三次贝塞尔），points 为 [{x, y}]。 */
function smoothPath(points) {
  if (!points.length) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }
  return d;
}

/* ============================================================================
 * 配置解析
 * ========================================================================== */
function parseLadder(config) {
  // 1) 优先使用数组形式 ladder: [{name, from, to}, ...]
  if (Array.isArray(config.ladder) && config.ladder.length) {
    return config.ladder.slice(0, 3).map((tier, index) => ({
      name: tier.name || DEFAULT_LADDER[index]?.name || `第${index + 1}阶梯`,
      from: num(tier.from, 0),
      to: num(tier.to, null),
    }));
  }
  // 2) 兼容编辑器写出的扁平字段 ladder1_from / ladder1_to ...
  if (config.ladder1_to !== undefined || config.ladder1_from !== undefined) {
    return [1, 2, 3].map((index) => ({
      name: DEFAULT_LADDER[index - 1].name,
      from: num(config[`ladder${index}_from`], DEFAULT_LADDER[index - 1].from),
      to: num(config[`ladder${index}_to`], DEFAULT_LADDER[index - 1].to),
    }));
  }
  return DEFAULT_LADDER.map((tier) => ({ ...tier }));
}

/** 未缴费判定（与 sensor.py 的 _is_current_unpaid 规则一致）。 */
function isUnpaid(order) {
  const time = order.write_off_time;
  const code = order.write_off_num;
  const timeEmpty =
    time === null || time === undefined || (typeof time === "string" && ["", "0001-01-01T00:00:00"].includes(time.trim()));
  const codeEmpty = code === null || code === undefined || (typeof code === "string" && code.trim() === "");
  return timeEmpty && codeEmpty;
}

/* ============================================================================
 * 卡片主体
 * ========================================================================== */
class JinanWaterCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = null;
    this._gs = null;
    this._ladder = DEFAULT_LADDER.map((tier) => ({ ...tier }));
    this._panel = "";
    this._expanded = new Set();
    this._signature = null;
    this._cal = { year: new Date().getFullYear(), month: new Date().getMonth() + 1 };
    this._onClick = this._onClick.bind(this);
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseLeave = this._onMouseLeave.bind(this);
  }

  /* ---------------------------- HA 卡片接口 ---------------------------- */

  static getStubConfig() {
    return {
      gs: "",
      title: "济南水务",
      ladder: DEFAULT_LADDER.map((tier) => ({ ...tier })),
      default_panel: "",
    };
  }

  static getConfigElement() {
    return document.createElement("jinan-water-card-editor");
  }

  setConfig(config) {
    if (!config) throw new Error("配置不能为空");
    this._config = { ...config };
    this._ladder = parseLadder(config);
    this._panel = config.default_panel || "";
    this._expanded = new Set();
    this._signature = null;
    const today = new Date();
    this._cal = { year: today.getFullYear(), month: today.getMonth() + 1 };
    this._gs = config.gs ? String(config.gs) : null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    if (!this._gs) {
      this._gs = this._detectGs();
      if (!this._gs) {
        this._render();
        return;
      }
    }
    const signature = this._dataSignature();
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    let size = 8;
    if (this._panel === "calendar") size += 7;
    if (this._panel === "dayChart") size += 5;
    if (this._panel === "orders") size += 3 + this._expanded.size * 4;
    return size;
  }

  connectedCallback() {
    this.shadowRoot.addEventListener("click", this._onClick);
    // mousemove 需冒泡，挂在 shadowRoot 上即可（事件跨 shadow 边界会重定向）。
    this.shadowRoot.addEventListener("mousemove", this._onMouseMove);
    // mouseleave 不冒泡：挂在宿主元素上，指针离开整张卡片时收起 tooltip。
    this.addEventListener("mouseleave", this._onMouseLeave);
    if (this._config && this._hass) this._render();
  }

  disconnectedCallback() {
    this.shadowRoot.removeEventListener("click", this._onClick);
    this.shadowRoot.removeEventListener("mousemove", this._onMouseMove);
    this.removeEventListener("mouseleave", this._onMouseLeave);
  }

  /* ------------------------------ 数据读取 ------------------------------ */

  /** 自动探测户号：取第一个 jinan_water 设备的「用水详情」实体后缀。 */
  _detectGs() {
    if (!this._hass) return null;
    const pattern = new RegExp(`^sensor\\.${DOMAIN}_usage_detail_(.+)$`);
    for (const entityId of Object.keys(this._hass.states)) {
      const matched = entityId.match(pattern);
      if (matched) return matched[1];
    }
    return null;
  }

  _entityId(key) {
    const override = this._config?.entities?.[key];
    if (override) return override;
    const suffix = ENTITY_SUFFIX[key] || key;
    return `sensor.${DOMAIN}_${suffix}_${this._gs}`;
  }

  _entity(key) {
    if (!this._hass || !this._gs) return null;
    return this._hass.states[this._entityId(key)] || null;
  }

  _num(key) {
    const entity = this._entity(key);
    return entity ? num(entity.state, null) : null;
  }

  /** 日用水记录（已排序、已规范化），来源为「用水详情」实体的 graph。 */
  _daily() {
    const entity = this._entity("usage_detail");
    const graph = entity?.attributes?.graph;
    if (!Array.isArray(graph)) return [];
    const rows = [];
    for (const record of graph) {
      const date = normalizeDate(record?.date);
      if (!date) continue;
      rows.push({
        date,
        usage: num(record.value, 0),
        reading: num(record.ZhiDu, null),
        average: num(record.value3, null),
      });
    }
    rows.sort((a, b) => a.date.localeCompare(b.date));
    return rows;
  }

  /** 账单（订单）列表（按抄表日期倒序）。 */
  _orders() {
    const entity = this._entity("order_detail");
    const graph = entity?.attributes?.graph;
    if (!Array.isArray(graph)) return [];
    const rows = graph.map((record) => {
      const readDate = normalizeDate(record.read_date) || "";
      return {
        id: String(record.id ?? `${record.bill_month || ""}-${readDate}`),
        billMonth: record.bill_month || (readDate ? readDate.slice(0, 7) : ""),
        readDate,
        amount: num(record.total_amount, 0),
        used: num(record.used_current, 0),
        unitPrice: num(record.unit_price, null),
        readLast: num(record.read_last, null),
        readCurrent: num(record.read_current, null),
        personBase: num(record.person_base, null),
        payChannel: record.pay_channel || record.pay_type || "",
        writeOffTime: record.write_off_time || "",
        unpaid: isUnpaid(record),
        detail: Array.isArray(record.detail) ? record.detail : [],
      };
    });
    rows.sort((a, b) => (b.readDate || "").localeCompare(a.readDate || ""));
    return rows;
  }

  /** 当前使用的单价：配置优先，其次「本期水价」实体。 */
  _unitPrice() {
    const configured = num(this._config?.price, null);
    if (configured !== null && configured > 0) return configured;
    const fromEntity = this._num("order_price");
    if (fromEntity !== null && fromEntity > 0) return fromEntity;
    return 0;
  }

  /** 数据签名：只有与展示相关的状态变化时才重新渲染。 */
  _dataSignature() {
    if (!this._hass) return null;
    const parts = Object.keys(ENTITY_SUFFIX).map((key) => {
      const entity = this._entity(key);
      if (!entity) return `${key}:-`;
      return `${key}:${entity.state}:${entity.last_updated || ""}`;
    });
    return `${this._gs}|${parts.join("|")}`;
  }

  /* ------------------------------ 交互事件 ------------------------------ */

  _onClick(event) {
    const target = event
      .composedPath()
      .find((node) => node instanceof HTMLElement && node.dataset && node.dataset.action);
    if (!target) return;
    event.stopPropagation();
    const action = target.dataset.action;

    switch (action) {
      case "toggle-panel": {
        const panel = target.dataset.panel;
        this._panel = this._panel === panel ? "" : panel;
        break;
      }
      case "toggle-order": {
        const id = target.dataset.id;
        if (this._expanded.has(id)) this._expanded.delete(id);
        else this._expanded.add(id);
        break;
      }
      case "cal-prev-month":
        this._shiftMonth(-1);
        break;
      case "cal-next-month":
        this._shiftMonth(1);
        break;
      case "cal-prev-year":
        this._shiftMonth(-12);
        break;
      case "cal-next-year":
        this._shiftMonth(12);
        break;
      case "cal-today": {
        const now = new Date();
        this._cal = { year: now.getFullYear(), month: now.getMonth() + 1 };
        break;
      }
      default:
        return;
    }
    this._signature = this._dataSignature();
    this._render();
  }

  _shiftMonth(delta) {
    const total = this._cal.year * 12 + (this._cal.month - 1) + delta;
    this._cal = { year: Math.floor(total / 12), month: (total % 12) + 1 };
  }

  _onMouseMove(event) {
    // 注意：图表本体是 <svg>（SVGElement），不是 HTMLElement，故用 dataset 鸭子判断，
    // 不能用 `instanceof HTMLElement`（那样永远匹配不到，hover 会完全失效）。
    const chart = event
      .composedPath()
      .find((node) => node && node.dataset && node.dataset.chart);
    if (!chart) return;
    const points = JSON.parse(chart.dataset.points || "[]");
    if (!points.length) return;
    const rect = chart.getBoundingClientRect();
    if (!rect.width) return;
    const container = chart.closest(".chart-wrap, .usage-spark");
    const tooltip = container ? container.querySelector(".chart-tooltip") : null;
    if (!tooltip) return;

    const viewWidth = Number(chart.dataset.viewWidth) || 640;
    const viewX = ((event.clientX - rect.left) / rect.width) * viewWidth;
    const plotLeft = Number(chart.dataset.plotLeft) || 0;
    const plotWidth = Number(chart.dataset.plotWidth) || 1;
    const step = points.length > 1 ? plotWidth / (points.length - 1) : 0;
    const index = clamp(Math.round(step ? (viewX - plotLeft) / step : 0), 0, points.length - 1);
    const point = points[index];
    if (!point) return;

    const rows = [
      `<div class="tt-row"><span class="tt-dot" style="background:${COLOR_USAGE}"></span>用水量 <b>${volume(point.usage)} m³</b></div>`,
      point.reading === undefined || point.reading === null
        ? ""
        : `<div class="tt-row"><span class="tt-dot" style="background:#8a8a8e"></span>止度 <b>${volume(point.reading)} m³</b></div>`,
      point.cost === undefined
        ? ""
        : `<div class="tt-row"><span class="tt-dot" style="background:${COLOR_COST}"></span>费用 <b>¥${money(point.cost)}</b></div>`,
      point.average === undefined || point.average === null
        ? ""
        : `<div class="tt-row"><span class="tt-dot" style="background:${COLOR_AVG}"></span>日均 <b>${volume(point.average)} m³</b></div>`,
    ]
      .filter(Boolean)
      .join("");

    tooltip.innerHTML = `<div class="tt-date">读表日期 ${escapeHtml(point.date || "--")}</div>${rows}`;
    tooltip.hidden = false;
    const offsetX = (point.x / viewWidth) * rect.width;
    tooltip.style.left = `${clamp(
      offsetX - tooltip.offsetWidth / 2,
      0,
      Math.max(rect.width - tooltip.offsetWidth, 0),
    )}px`;
    tooltip.style.top = "4px";

    const cursor = container.querySelector(".chart-cursor");
    if (cursor) {
      cursor.setAttribute("x1", point.x);
      cursor.setAttribute("x2", point.x);
      cursor.style.opacity = "1";
    }
  }

  _onMouseLeave() {
    this.shadowRoot.querySelectorAll(".chart-tooltip").forEach((element) => {
      element.hidden = true;
    });
    this.shadowRoot.querySelectorAll(".chart-cursor").forEach((element) => {
      element.style.opacity = "0";
    });
  }

  /* ------------------------------- 渲染 ------------------------------- */

  _render() {
    const root = this.shadowRoot;
    if (!this._hass) return;

    if (!this._config) {
      root.innerHTML = `<style>${STYLES}</style><ha-card><div class="empty">请先配置卡片</div></ha-card>`;
      return;
    }

    if (!this._gs) {
      root.innerHTML = `<style>${STYLES}</style><ha-card><div class="empty">
        未找到济南水务设备：请确认集成已添加，或在卡片配置中填写 gs（户号）。</div></ha-card>`;
      return;
    }

    root.innerHTML = `<style>${STYLES}</style>${this._renderMain()}${this._renderPanel()}`;
  }

  /* ---- 主视图（顶部指标 + 本期用水 + 账单小卡 + 阶梯 + 按钮） ---- */
  _renderMain() {
    const balance = this._num("balance");
    const pending = this._num("pending_fee");
    const penalty = this._num("penalty_fee");
    const title = this._config.title || "济南水务";

    const refreshEntity = this._entity("refresh_time");
    const syncTime = formatDateTime(refreshEntity?.state);
    const latestDate = this._entity("latest_meter_date")?.state || "";
    const latestDaily = this._daily().slice(-1)[0];
    const dataDate = normalizeDate(latestDate) || latestDaily?.date || "--";

    const usage = this._num("usage");
    const currentFee = this._num("current_fee");
    const daily = this._daily();
    const recent = daily.slice(-30);

    const orders = this._orders();
    const previousOrder = orders[1] || null;
    const currentYear = String(new Date().getFullYear());
    const yearOrders = orders.filter((order) => (order.billMonth || "").startsWith(currentYear));
    const yearAmount = yearOrders.reduce((sum, order) => sum + order.amount, 0);
    const yearlyUsage = this._num("yearly_usage");

    let delta = "";
    if (previousOrder && previousOrder.used > 0 && usage !== null) {
      const rate = ((usage - previousOrder.used) / previousOrder.used) * 100;
      const up = rate >= 0;
      delta = `<div class="delta" style="color:${up ? "#e05a5a" : COLOR_OK}">
        对比上期账单 ${up ? "↑" : "↓"}${Math.abs(rate).toFixed(0)}%
        <div class="delta-tip">
          <div class="delta-tip-title">上期账单 ${escapeHtml(previousOrder.billMonth || "--")}</div>
          <div>抄表日期：${escapeHtml(previousOrder.readDate || "--")}</div>
          <div>用水量：${volume(previousOrder.used)} m³</div>
          <div>费　用：¥ ${money(previousOrder.amount)}</div>
        </div>
      </div>`;
    }

    return `
      <ha-card class="main-card">
        <div class="card-title-row">
          <span class="card-title">${icon("water", 15)}${escapeHtml(title)}</span>
          <span class="card-meta">
            ${syncTime ? `同步 ${escapeHtml(syncTime)}` : ""}
            ${dataDate !== "--" ? `<br/>数据日期 ${escapeHtml(dataDate)}` : ""}
          </span>
        </div>

        <div class="metrics">
          ${this._renderMetric("水费余额", balance, "wallet", "¥", false)}
          ${this._renderMetric("欠费金额", pending, "alert", "¥", (pending ?? 0) > 0)}
          ${this._renderMetric("违约金", penalty, "gavel", "¥", (penalty ?? 0) > 0)}
        </div>

        <div class="usage-card">
          <div class="section-head">${icon("water", 14)} 本期用水
            <span class="section-sub">抄表日期 ${escapeHtml(dataDate)}</span>
          </div>
          <div class="usage-body">
            <div class="usage-left">
              <div class="usage-value">${usage === null ? "--" : volume(usage)}<small> m³</small></div>
              <div class="usage-cost">¥ ${money(currentFee)}</div>
              ${delta}
            </div>
            <div class="usage-spark" data-action="toggle-panel" data-panel="dayChart" title="点击查看日用水曲线">
              ${this._renderSparkline(recent)}
            </div>
          </div>
        </div>

        ${this._renderLadder(yearlyUsage, yearAmount)}

        <div class="actions">
          ${this._renderAction("calendar", "calendar", "水费日历")}
          ${this._renderAction("dayChart", "chart", "日用水曲线")}
          ${this._renderAction("orders", "list", "订单列表")}
        </div>
      </ha-card>`;
  }

  _renderMetric(label, value, iconName, prefix, warn) {
    const text = value === null ? "--" : money(value);
    return `
      <div class="metric${warn ? " warn" : ""}">
        <div class="metric-label">${icon(iconName, 13)}${escapeHtml(label)}</div>
        <div class="metric-value"><span class="cur">${prefix}</span>${text}</div>
      </div>`;
  }

  _renderAction(panel, iconName, label) {
    const active = this._panel === panel ? " active" : "";
    return `<div class="action${active}" data-action="toggle-panel" data-panel="${panel}">
      ${icon(iconName, 16)}<span>${escapeHtml(label)}</span></div>`;
  }

  /* ---- 日用水 sparkline（近 30 天：用水量 + 日均 双折线，支持 hover） ---- */
  _renderSparkline(rows) {
    if (!rows.length) return `<div class="spark-empty">暂无日用水数据</div>`;
    const width = 300;
    const height = 90;
    const pad = 8;
    // 用水量与日均同为体积量纲，共用同一纵轴比例
    const maxValue = Math.max(
      ...rows.map((row) => Math.max(row.usage, row.average === null ? 0 : row.average)),
      0.1,
    );
    const step = rows.length > 1 ? (width - pad * 2) / (rows.length - 1) : 0;
    const xOf = (index) => pad + index * step;
    const yOf = (value) => height - pad - (value / maxValue) * (height - pad * 2);

    const usagePoints = rows.map((row, index) => ({ x: xOf(index), y: yOf(row.usage) }));
    const avgPoints = rows.map((row, index) => ({
      x: xOf(index),
      y: yOf(row.average === null ? row.usage : row.average),
    }));
    const last = usagePoints[usagePoints.length - 1];

    const chartData = JSON.stringify(
      rows.map((row, index) => ({
        x: xOf(index),
        date: row.date,
        usage: row.usage,
        average: row.average,
      })),
    );

    return `
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" preserveAspectRatio="none"
           data-chart="spark" data-points='${chartData.replace(/'/g, "&#39;")}'
           data-view-width="${width}" data-plot-left="${pad}" data-plot-width="${width - pad * 2}">
        <defs>
          <linearGradient id="jw-spark-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${COLOR_USAGE}" stop-opacity="0.28"/>
            <stop offset="100%" stop-color="${COLOR_USAGE}" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <path d="${smoothPath(usagePoints)} L ${last.x} ${height - pad} L ${usagePoints[0].x} ${height - pad} Z"
              fill="url(#jw-spark-fill)" stroke="none"/>
        <path d="${smoothPath(avgPoints)}" fill="none" stroke="${COLOR_AVG}" stroke-width="1.4"
              stroke-dasharray="4 4"/>
        <path d="${smoothPath(usagePoints)}" fill="none" stroke="${COLOR_USAGE}" stroke-width="2.4"
              stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${last.x}" cy="${last.y}" r="3.2" fill="#fff" stroke="${COLOR_USAGE}" stroke-width="2"/>
        <line class="chart-cursor" x1="0" y1="${pad}" x2="0" y2="${height - pad}"
              stroke="${COLOR_AVG}" stroke-width="1" style="opacity:0"/>
      </svg>
      <div class="chart-tooltip" hidden></div>
      <div class="spark-legend">
        <span><i style="background:${COLOR_USAGE}"></i>用水量</span>
        <span><i class="dashed" style="background:${COLOR_AVG}"></i>日均</span>
      </div>`;
  }

  /* ---- 年用水阶梯（2 行：连续色块进度条 + 区间标签） ---- */
  _renderLadder(yearlyUsage, yearAmount) {
    const value = yearlyUsage === null ? 0 : yearlyUsage;
    const tiers = this._ladder;

    // 计算每档填充比例与当前所处档位
    const fills = [];
    let activeIndex = 0;
    tiers.forEach((tier, index) => {
      const from = tier.from ?? 0;
      const to = tier.to;
      const span = to === null ? (tiers[index - 1] ? (tiers[index - 1].to ?? 100) - (tiers[index - 1].from ?? 0) : 96) : to - from;
      let ratio = 0;
      if (value > from) ratio = clamp((value - from) / Math.max(span, 1), 0, 1);
      if (to !== null && value > to) ratio = 1;
      fills.push(ratio);
      if (value > (to ?? Number.POSITIVE_INFINITY)) activeIndex = index + 1;
    });
    activeIndex = clamp(activeIndex, 0, tiers.length - 1);

    // 闪电标记所在的整体百分比位置（3 档等宽，% = 档位 + 档内进度）
    const segmentWidth = 100 / tiers.length;
    const indicatorLeft = clamp(
      activeIndex * segmentWidth + fills[activeIndex] * segmentWidth,
      2,
      98,
    );

    // 第 1 行：3 个连续色块，档位名居中，内部按进度加深
    const tierBlocks = tiers
      .map(
        (tier, index) => `
        <div class="ladder-tier t${index + 1}">
          <div class="ladder-tier-fill" style="width:${(fills[index] * 100).toFixed(1)}%"></div>
          <span class="ladder-tier-name">${escapeHtml(tier.name)}</span>
        </div>`,
      )
      .join("");

    // 第 2 行：对应的区间标签
    const ranges = tiers
      .map((tier, index) => {
        const from = tier.from ?? 0;
        const range = tier.to === null ? `${from}m³以上` : `${from}-${tier.to}m³`;
        return `<div class="ladder-range t${index + 1}">${range}</div>`;
      })
      .join("");

    return `
      <div class="ladder-block">
        <div class="section-head">${ladderIcon(13)} 年用水阶梯
          <span class="ladder-value"><b class="ladder-strong">年累计</b> ${volume(value)} m³${
            yearlyUsage === null || yearlyUsage === 0 ? "（待接口确认）" : ""
          }<span class="ladder-sep">|</span><span class="ladder-money">¥ ${money(yearAmount)}</span></span>
        </div>
        <div class="ladder-band">
          ${tierBlocks}
          <div class="ladder-bolt" style="left:${indicatorLeft.toFixed(1)}%" title="年累计用水所处位置">
            ${icon("bolt", 15)}
          </div>
        </div>
        <div class="ladder-ranges">${ranges}</div>
      </div>`;
  }

  /* --------------------------- 面板（默认隐藏） --------------------------- */
  _renderPanel() {
    if (this._panel === "calendar") return this._renderCalendarPanel();
    if (this._panel === "dayChart") return this._renderDayChartPanel();
    if (this._panel === "orders") return this._renderOrdersPanel();
    return "";
  }

  /* ---- 水费日历 ---- */
  _renderCalendarPanel() {
    const price = this._unitPrice();
    const dailyMap = new Map(this._daily().map((row) => [row.date, row]));
    const { year, month } = this._cal;
    const daysInMonth = new Date(year, month, 0).getDate();
    const firstWeekday = new Date(year, month - 1, 1).getDay(); // 0=周日
    const leading = firstWeekday === 0 ? 6 : firstWeekday - 1; // 周一为第一列
    const todayIso = new Date().toISOString().slice(0, 10);

    let cells = "";
    for (let i = 0; i < leading; i += 1) cells += `<div class="cal-cell empty"></div>`;
    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const row = dailyMap.get(iso);
      const cost = row ? row.usage * price : null;
      const classes = ["cal-cell"];
      if (row) classes.push("has-data");
      if (iso === todayIso) classes.push("today");
      cells += `
        <div class="${classes.join(" ")}">
          <span class="cal-day">${day}</span>
          ${
            row
              ? `<span class="cal-usage">${volume(row.usage, 2)}</span>
                 <span class="cal-cost">¥${money(cost, 1)}</span>`
              : `<span class="cal-usage placeholder">-</span><span class="cal-cost placeholder">-</span>`
          }
        </div>`;
    }

    const totalUsage = [...dailyMap.entries()]
      .filter(([date]) => date.startsWith(`${year}-${String(month).padStart(2, "0")}`))
      .reduce((sum, [, row]) => sum + row.usage, 0);

    return `
      <ha-card class="panel-card">
        <div class="cal-nav">
          <span class="nav-btn" data-action="cal-prev-year">${icon("arrowLeft", 14)}</span>
          <span class="cal-title">${year}年</span>
          <span class="nav-btn" data-action="cal-next-year">${icon("arrowRight", 14)}</span>
          <span class="nav-btn today-btn" data-action="cal-today">当月</span>
          <span class="nav-btn" data-action="cal-prev-month">${icon("arrowLeft", 14)}</span>
          <span class="cal-title">${month}月</span>
          <span class="nav-btn" data-action="cal-next-month">${icon("arrowRight", 14)}</span>
        </div>
        <div class="cal-week">${["一", "二", "三", "四", "五", "六", "日"]
          .map((day) => `<span>${day}</span>`)
          .join("")}</div>
        <div class="cal-grid">${cells}</div>
        <div class="cal-footer">
          本月合计 ${volume(totalUsage)} m³ / ¥ ${money(totalUsage * price)}
          <span class="cal-note">费用 = 日用水量 × 单价 ${money(price)} 元/m³</span>
        </div>
      </ha-card>`;
  }

  /* ---- 日用水曲线（用水量 + 费用双曲线，含日均曲线） ---- */
  _renderDayChartPanel() {
    const price = this._unitPrice();
    const rows = this._daily();
    if (!rows.length) {
      return `<ha-card class="panel-card"><div class="empty">暂无日用水数据</div></ha-card>`;
    }

    const viewWidth = 640;
    const viewHeight = 260;
    const padLeft = 42;
    const padRight = 46;
    const padTop = 22;
    const padBottom = 34;
    const plotWidth = viewWidth - padLeft - padRight;
    const plotHeight = viewHeight - padTop - padBottom;

    const points = rows.map((row) => ({
      date: row.date,
      usage: row.usage,
      reading: row.reading,
      cost: row.usage * price,
      average: row.average === null ? row.usage : row.average,
    }));

    const maxUsage = Math.max(...points.map((point) => point.usage), 0.1);
    const maxCost = Math.max(...points.map((point) => point.cost), 0.1);
    const step = points.length > 1 ? plotWidth / (points.length - 1) : 0;

    const xOf = (index) => padLeft + index * step;
    const yUsage = (value) => padTop + plotHeight - (value / maxUsage) * plotHeight;
    const yCost = (value) => padTop + plotHeight - (value / maxCost) * plotHeight;

    const usagePoints = points.map((point, index) => ({ x: xOf(index), y: yUsage(point.usage) }));
    const avgPoints = points.map((point, index) => ({ x: xOf(index), y: yUsage(point.average) }));

    // 费用用柱状表达：由于「费用 = 日用水量 × 单价」，费用曲线与用水量曲线形状完全
    // 一致（只是量纲不同），若都画成曲线会完全重叠；柱子 + 曲线的组合既直观又便于区分。
    const baseline = padTop + plotHeight;
    const barWidth = clamp(step * 0.6, 2, 14);
    const costBars = points
      .map((point, index) => {
        const y = yCost(point.cost);
        const height = Math.max(baseline - y, 0);
        if (height <= 0) return "";
        return `<rect x="${(xOf(index) - barWidth / 2).toFixed(2)}" y="${y.toFixed(2)}"
                      width="${barWidth.toFixed(2)}" height="${height.toFixed(2)}" rx="1.5"
                      fill="${COLOR_COST}" fill-opacity="0.28"/>`;
      })
      .join("");

    // 网格与坐标轴刻度
    const gridLines = [0, 1, 2, 3, 4]
      .map((tick) => {
        const ratio = tick / 4;
        const y = padTop + plotHeight * ratio;
        const usageLabel = volume(maxUsage * (1 - ratio), 1);
        const costLabel = money(maxCost * (1 - ratio), 1);
        return `
          <line x1="${padLeft}" y1="${y}" x2="${padLeft + plotWidth}" y2="${y}"
                stroke="var(--jw-border)" stroke-width="1" stroke-dasharray="3 4"/>
          <text x="${padLeft - 6}" y="${y + 3}" text-anchor="end" class="axis-text">${usageLabel}</text>
          <text x="${padLeft + plotWidth + 6}" y="${y + 3}" text-anchor="start" class="axis-text">${costLabel}</text>`;
      })
      .join("");

    const xTicks = points
      .map((point, index) => {
        if (points.length > 8 && index % Math.ceil(points.length / 8) !== 0 && index !== points.length - 1) {
          return "";
        }
        return `<text x="${xOf(index)}" y="${viewHeight - 12}" text-anchor="middle" class="axis-text">
          ${point.date.slice(5)}</text>`;
      })
      .join("");

    const chartData = JSON.stringify(
      points.map((point, index) => ({
        x: xOf(index),
        date: point.date,
        usage: point.usage,
        reading: point.reading,
        cost: point.cost,
        average: point.average,
      })),
    );

    return `
      <ha-card class="panel-card">
        <div class="panel-head">${icon("chart", 15)} 日用水曲线
          <span class="panel-sub">共 ${points.length} 天</span>
        </div>
        <div class="chart-wrap">
          <svg viewBox="0 0 ${viewWidth} ${viewHeight}" width="100%" height="${viewHeight}"
               data-chart="day" data-points='${chartData.replace(/'/g, "&#39;")}'
               data-view-width="${viewWidth}" data-plot-left="${padLeft}" data-plot-width="${plotWidth}">
            <defs>
              <linearGradient id="jw-day-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${COLOR_USAGE}" stop-opacity="0.32"/>
                <stop offset="100%" stop-color="${COLOR_USAGE}" stop-opacity="0.02"/>
              </linearGradient>
            </defs>
            ${gridLines}
            ${xTicks}
            ${costBars}
            <path d="${smoothPath(usagePoints)} L ${usagePoints[usagePoints.length - 1].x} ${padTop + plotHeight} L ${usagePoints[0].x} ${padTop + plotHeight} Z"
                  fill="url(#jw-day-fill)" stroke="none"/>
            <path d="${smoothPath(avgPoints)}" fill="none" stroke="${COLOR_AVG}" stroke-width="1.4"
                  stroke-dasharray="4 4"/>
            <path d="${smoothPath(usagePoints)}" fill="none" stroke="${COLOR_USAGE}" stroke-width="2.4"
                  stroke-linecap="round" stroke-linejoin="round"/>
            ${usagePoints
              .map(
                (point, index) =>
                  `<circle cx="${point.x}" cy="${point.y}" r="4" fill="#fff" stroke="${COLOR_USAGE}" stroke-width="2">
                     <title>${points[index].date} 用水 ${volume(points[index].usage)} m³ / 止度 ${volume(points[index].reading)} m³ / 费用 ¥${money(points[index].cost)}</title>
                   </circle>`,
              )
              .join("")}
            <line class="chart-cursor" x1="0" y1="${padTop}" x2="0" y2="${padTop + plotHeight}"
                  stroke="${COLOR_AVG}" stroke-width="1" style="opacity:0"/>
          </svg>
          <div class="chart-tooltip" hidden></div>
        </div>
        <div class="chart-legend">
          <span><i style="background:${COLOR_USAGE}"></i>用水量 (m³)</span>
          <span><i style="background:${COLOR_COST};opacity:.45"></i>费用 (元，柱)</span>
          <span><i class="dashed" style="background:${COLOR_AVG}"></i>日均用量 (m³)</span>
        </div>
      </ha-card>`;
  }

  /* ---- 订单列表（可展开明细） ---- */
  _renderOrdersPanel() {
    const price = this._unitPrice();
    const orders = this._orders();
    if (!orders.length) {
      return `<ha-card class="panel-card"><div class="empty">暂无订单记录</div></ha-card>`;
    }

    const rows = orders
      .map((order) => {
        const expanded = this._expanded.has(order.id);
        const monthLabel = order.billMonth
          ? `${order.billMonth.slice(0, 4)}年${order.billMonth.slice(5, 7)}月`
          : order.readDate || "--";
        const detailRows = order.detail
          .map(
            (item) => `
            <tr>
              <td class="cell-name">${escapeHtml(item.name || "")}</td>
              <td>${volume(item.total)}</td>
              <td>${money(item.unit_price)}</td>
              <td>${money(item.amount)}</td>
            </tr>`,
          )
          .join("");
        const detailTotal = order.detail.reduce((sum, item) => sum + (num(item.amount, 0) || 0), 0);

        return `
          <div class="order${expanded ? " open" : ""}">
            <div class="order-row" data-action="toggle-order" data-id="${escapeHtml(order.id)}">
              <span class="order-icon">${icon("calendar", 15)}</span>
              <span class="order-main">
                <span class="order-title">${escapeHtml(monthLabel)}</span>
                <span class="order-sub">抄表 ${escapeHtml(order.readDate || "--")}</span>
              </span>
              <span class="order-amount">${money(order.amount)} 元</span>
              <span class="tag ${order.unpaid ? "unpaid" : "paid"}">${order.unpaid ? "未缴费" : "已缴费"}</span>
              <span class="order-chev">${icon(expanded ? "chevronUp" : "chevronDown", 16)}</span>
            </div>
            <div class="order-detail">
              <div class="detail-grid">
                ${this._detailItem("上次表数", `${volume(order.readLast)} m³`)}
                ${this._detailItem("本次表数", `${volume(order.readCurrent)} m³`)}
                ${this._detailItem("抄表日期", order.readDate || "--")}
                ${this._detailItem("综合单价", `${money(order.unitPrice)} 元`)}
                ${this._detailItem("本期用量", `${volume(order.used)} m³`)}
                ${this._detailItem("人口基数", order.personBase === null ? "--" : `${order.personBase} 人`)}
                ${this._detailItem("交费日期", order.unpaid ? "未缴费" : formatDateTime(order.writeOffTime) || "--")}
                ${this._detailItem("交费渠道", order.payChannel || "--")}
              </div>
              <table class="detail-table">
                <thead>
                  <tr><th>项目</th><th>用量</th><th>单价</th><th>金额</th></tr>
                </thead>
                <tbody>${detailRows || `<tr><td colspan="4" class="empty-cell">无费用明细</td></tr>`}</tbody>
                <tfoot>
                  <tr>
                    <td colspan="3" class="total-label">合计</td>
                    <td class="total-value">¥ ${money(detailTotal || order.amount)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>`;
      })
      .join("");

    return `
      <ha-card class="panel-card">
        <div class="panel-head">${icon("list", 15)} 订单列表
          <span class="panel-sub">共 ${orders.length} 笔${
            price ? ` · 单价 ${money(price)} 元/m³` : ""
          }</span>
        </div>
        <div class="order-list">${rows}</div>
      </ha-card>`;
  }

  _detailItem(label, value) {
    return `<div class="detail-item"><span class="detail-k">${escapeHtml(label)}：</span>
      <span class="detail-v">${escapeHtml(value)}</span></div>`;
  }
}

/* ============================================================================
 * 可视化配置编辑器
 * ========================================================================== */
const EDITOR_SCHEMA = [
  { name: "gs", label: "户号（留空自动探测）", selector: { text: {} } },
  { name: "title", label: "卡片标题", selector: { text: {} } },
  {
    name: "price",
    label: "水价单价（元/m³，留空读「本期水价」实体）",
    selector: { number: { min: 0, max: 100, step: 0.01, mode: "box" } },
  },
  {
    name: "",
    type: "grid",
    schema: [
      { name: "ladder1_from", label: "第1档起始水量", selector: { number: { min: 0, mode: "box" } } },
      { name: "ladder1_to", label: "第1档结束水量", selector: { number: { min: 0, mode: "box" } } },
      { name: "ladder2_from", label: "第2档起始水量", selector: { number: { min: 0, mode: "box" } } },
      { name: "ladder2_to", label: "第2档结束水量", selector: { number: { min: 0, mode: "box" } } },
      { name: "ladder3_from", label: "第3档起始水量", selector: { number: { min: 0, mode: "box" } } },
    ],
  },
  {
    name: "default_panel",
    label: "默认展开面板",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "", label: "都不展开" },
          { value: "calendar", label: "水费日历" },
          { value: "dayChart", label: "日用水曲线" },
          { value: "orders", label: "订单列表" },
        ],
      },
    },
  },
];

/** 配置 <-> 扁平表单字段互转。 */
function configToFormData(config) {
  const ladder = parseLadder(config);
  const data = {
    gs: config.gs || "",
    title: config.title || "济南水务",
    default_panel: config.default_panel || "",
  };
  if (config.price !== undefined) data.price = config.price;
  [0, 1, 2].forEach((index) => {
    data[`ladder${index + 1}_from`] = ladder[index]?.from ?? DEFAULT_LADDER[index].from;
    if (index < 2) data[`ladder${index + 1}_to`] = ladder[index]?.to ?? DEFAULT_LADDER[index].to;
  });
  return data;
}

function formDataToConfig(data, base) {
  const ladder = [1, 2, 3].map((index) => ({
    name: DEFAULT_LADDER[index - 1].name,
    from: num(data[`ladder${index}_from`], DEFAULT_LADDER[index - 1].from),
    to: index === 3 ? null : num(data[`ladder${index}_to`], DEFAULT_LADDER[index - 1].to),
  }));
  const config = { ...base, ladder };
  config.gs = data.gs || "";
  config.title = data.title || "";
  config.default_panel = data.default_panel || "";
  if (num(data.price, null) !== null) config.price = num(data.price, null);
  else delete config.price;
  return config;
}

class JinanWaterCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
    } else {
      this._render();
    }
  }

  _valueChanged(value) {
    const config = formDataToConfig(value, this._config);
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  }

  _render() {
    const data = configToFormData(this._config);
    if (customElements.get("ha-form")) {
      const form = document.createElement("ha-form");
      form.hass = this._hass;
      form.data = data;
      form.schema = EDITOR_SCHEMA;
      form.computeLabel = (schema) => schema.label || schema.name;
      form.addEventListener("value-changed", (event) => this._valueChanged(event.detail.value));
      this._form = form;
      this.shadowRoot.innerHTML = `<div class="editor"></div>`;
      this.shadowRoot.querySelector(".editor").appendChild(form);
      return;
    }

    // 无 HA 前端（如本地预览页）时的降级编辑器：原生输入框
    this._form = null;
    const fields = [
      ["gs", "户号", "text"],
      ["title", "卡片标题", "text"],
      ["price", "单价(元/m³)", "number"],
      ["ladder1_from", "第1档起始", "number"],
      ["ladder1_to", "第1档结束", "number"],
      ["ladder2_from", "第2档起始", "number"],
      ["ladder2_to", "第2档结束", "number"],
      ["ladder3_from", "第3档起始", "number"],
    ];
    const html = fields
      .map(
        ([name, label, type]) => `
        <label class="row">
          <span>${label}</span>
          <input type="${type}" data-field="${name}" value="${
            data[name] === undefined || data[name] === null ? "" : escapeHtml(data[name])
          }"/>
        </label>`,
      )
      .join("");
    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 8px 0; font-family: var(--paper-font-body1_-_font-family, sans-serif); }
        .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 0; }
        .row span { font-size: 13px; color: var(--primary-text-color, #333); }
        input { flex: 0 0 130px; padding: 4px 6px; font-size: 13px; }
      </style>
      <div class="editor">${html}</div>`;
    this.shadowRoot.querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        const values = {};
        this.shadowRoot.querySelectorAll("input").forEach((item) => {
          values[item.dataset.field] = item.value;
        });
        this._valueChanged(values);
      });
    });
  }
}

/* ============================================================================
 * 样式
 * ========================================================================== */
const STYLES = `
  :host { display: block; --jw-border: #e6e8eb; }
  * { box-sizing: border-box; }
  .ico { vertical-align: -2px; }

  ha-card {
    background: var(--ha-card-background, var(--card-background-color, #fff));
    color: var(--primary-text-color, #1c1c1e);
    border-radius: var(--ha-card-border-radius, 12px);
  }
  .main-card { padding: 12px 12px 10px; }
  .panel-card { padding: 12px; margin-top: 10px; }
  .empty { padding: 18px; text-align: center; color: var(--secondary-text-color, #8a8a8e); font-size: 13px; }

  /* ---------- 顶部：标题 + 同步时间 ---------- */
  .card-title-row { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 10px; }
  .card-title { font-size: 14px; font-weight: 600; display: inline-flex; align-items: center; gap: 5px; }
  .card-meta { font-size: 11px; line-height: 1.45; color: var(--secondary-text-color, #8a8a8e); text-align: right; }

  /* ---------- 三个平行指标 ---------- */
  .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .metric {
    background: var(--secondary-background-color, rgba(0,0,0,0.04));
    border-radius: 10px; padding: 9px 10px; min-width: 0;
  }
  .metric-label { font-size: 11.5px; color: var(--secondary-text-color, #8a8a8e); display: flex; align-items: center; gap: 4px; }
  .metric-value { font-size: 20px; font-weight: 700; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .metric-value .cur { font-size: 11px; margin-right: 1px; font-weight: 500; }
  .metric.warn .metric-value { color: ${COLOR_WARN}; }

  /* ---------- 本期用水 ---------- */
  .usage-card {
    margin-top: 10px; border-radius: 12px; padding: 10px 12px;
    border: 1px solid var(--jw-border);
    background: var(--ha-card-background, #fff);
  }
  .section-head {
    font-size: 12.5px; font-weight: 600; display: flex; align-items: center; gap: 5px;
    color: var(--primary-text-color, #1c1c1e);
  }
  .usage-body { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
  .usage-left { flex: 1 1 46%; min-width: 0; }
  .usage-value { font-size: 24px; font-weight: 700; line-height: 1.15; }
  .usage-value small { font-size: 12px; font-weight: 500; color: var(--secondary-text-color, #8a8a8e); }
  .usage-cost { font-size: 14px; font-weight: 600; margin-top: 2px; }
  .delta {
    font-size: 11.5px; margin-top: 3px; position: relative; display: inline-block;
    cursor: help; border-bottom: 1px dashed currentColor;
  }
  .delta-tip {
    display: none; position: absolute; left: 0; top: calc(100% + 6px); z-index: 6;
    background: rgba(255,255,255,0.98); color: #1c1c1e; border: 1px solid var(--jw-border);
    border-radius: 8px; padding: 6px 9px; box-shadow: 0 4px 14px rgba(0,0,0,.14);
    font-size: 11px; line-height: 1.55; white-space: nowrap; text-align: left;
  }
  .delta:hover .delta-tip { display: block; }
  .delta-tip-title { font-weight: 700; margin-bottom: 2px; }
  .usage-spark { flex: 1 1 54%; cursor: pointer; position: relative; }
  .spark-empty { font-size: 11px; color: var(--secondary-text-color, #8a8a8e); text-align: center; padding: 20px 0; }
  .spark-legend { display: flex; justify-content: center; gap: 10px; margin-top: 2px; font-size: 10px; color: var(--secondary-text-color, #8a8a8e); }
  .spark-legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; vertical-align: -1px; }
  .spark-legend i.dashed { height: 3px; border-radius: 2px; }

  /* ---------- 本期用水卡头部的小字（抄表日期） ---------- */
  .section-sub { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--secondary-text-color, #8a8a8e); }

  /* ---------- 年用水阶梯（2 行：连续色块进度条 + 区间） ---------- */
  .ladder-block { margin-top: 12px; }
  .ladder-value { margin-left: auto; font-size: 11px; font-weight: 400; color: var(--secondary-text-color, #8a8a8e); white-space: nowrap; }
  .ladder-strong { font-weight: 700; color: var(--primary-text-color, #1c1c1e); }
  .ladder-sep { margin: 0 5px; opacity: .55; }
  .ladder-money { font-weight: 400; color: var(--primary-text-color, #1c1c1e); }
  .ladder-band { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 8px; }
  .ladder-tier {
    position: relative; height: 30px; overflow: hidden;
    display: flex; align-items: center; justify-content: center;
  }
  .ladder-tier:first-child { border-top-left-radius: 7px; border-bottom-left-radius: 7px; }
  .ladder-tier:last-child { border-top-right-radius: 7px; border-bottom-right-radius: 7px; }
  .ladder-tier.t1 { background: #dcecf8; }
  .ladder-tier.t2 { background: #e7e3f8; }
  .ladder-tier.t3 { background: #f7e6f2; }
  .ladder-tier-fill { position: absolute; left: 0; top: 0; bottom: 0; width: 0; transition: width .35s ease; }
  .ladder-tier.t1 .ladder-tier-fill { background: #5aa9e0; }
  .ladder-tier.t2 .ladder-tier-fill { background: #8f83db; }
  .ladder-tier.t3 .ladder-tier-fill { background: #c57fc6; }
  .ladder-tier-name { position: relative; z-index: 1; font-size: 11.5px; font-weight: 700; color: #26445c; }
  .ladder-bolt {
    position: absolute; top: 50%; transform: translate(-50%, -50%); z-index: 2;
    color: #123c5c; display: flex; pointer-events: none;
    filter: drop-shadow(0 0 2px rgba(255,255,255,.95));
    transition: left .35s ease;
  }
  .ladder-ranges { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 4px; }
  .ladder-range { text-align: center; font-size: 11px; padding: 4px 0; font-weight: 600; }
  .ladder-range.t1 { background: #eaf5fd; color: #1b6fa8; border-top-left-radius: 7px; border-bottom-left-radius: 7px; }
  .ladder-range.t2 { background: #efeefb; color: #4b3f9e; }
  .ladder-range.t3 { background: #fbeef8; color: #8a3b83; border-top-right-radius: 7px; border-bottom-right-radius: 7px; }

  /* ---------- 按钮 ---------- */
  .actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 12px; }
  .action {
    display: flex; align-items: center; justify-content: center; gap: 4px;
    height: 38px; border-radius: 8px; cursor: pointer; font-size: 12.5px; font-weight: 500;
    background: var(--secondary-background-color, rgba(0,0,0,0.04));
    border: 1px solid transparent; transition: all .18s ease; user-select: none;
  }
  .action:hover { border-color: ${COLOR_USAGE}; }
  .action.active { background: #d7ecfb; border-color: ${COLOR_USAGE}; color: #1b6fa8; font-weight: 700; }

  /* ---------- 面板通用 ---------- */
  .panel-head { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; margin-bottom: 8px; }
  .panel-sub { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--secondary-text-color, #8a8a8e); }

  /* ---------- 日历 ---------- */
  .cal-nav { display: grid; grid-template-columns: 26px 1fr 26px 54px 26px 1fr 26px; align-items: center; gap: 2px; }
  .cal-title { text-align: center; font-size: 13px; font-weight: 600; }
  .nav-btn {
    display: flex; align-items: center; justify-content: center; height: 26px;
    border-radius: 6px; cursor: pointer; color: var(--secondary-text-color, #6b7280);
    user-select: none;
  }
  .nav-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
  .today-btn { font-size: 11.5px; }
  .cal-week, .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
  .cal-week { margin: 8px 0 4px; }
  .cal-week span { text-align: center; font-size: 11px; color: var(--secondary-text-color, #8a8a8e); }
  .cal-cell {
    min-height: 52px; border-radius: 7px; padding: 4px 2px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
    background: transparent;
  }
  .cal-cell.empty { background: transparent; }
  .cal-cell.has-data { background: #eaf5fd; }
  .cal-day { font-size: 13.5px; font-weight: 600; }
  .cal-usage { font-size: 10px; color: ${COLOR_USAGE}; }
  .cal-cost { font-size: 10px; color: ${COLOR_COST}; }
  .cal-usage.placeholder, .cal-cost.placeholder { visibility: hidden; }
  .cal-cell.today { outline: 2px solid ${COLOR_USAGE}; outline-offset: -2px; }
  .cal-footer { margin-top: 8px; font-size: 11.5px; color: var(--secondary-text-color, #6b7280); display: flex; flex-wrap: wrap; gap: 6px; }
  .cal-note { opacity: .8; }

  /* ---------- 图表 ---------- */
  .chart-wrap { position: relative; }
  .axis-text { font-size: 10px; fill: var(--secondary-text-color, #8a8a8e); }
  .chart-tooltip {
    position: absolute; z-index: 5; pointer-events: none;
    background: rgba(255,255,255,0.97); color: #1c1c1e;
    border: 1px solid var(--jw-border); border-radius: 8px; padding: 6px 8px;
    box-shadow: 0 4px 14px rgba(0,0,0,.12); font-size: 11px; line-height: 1.5; min-width: 108px;
  }
  .tt-date { font-weight: 600; margin-bottom: 2px; }
  .tt-row { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
  .tt-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
  .chart-legend { display: flex; justify-content: center; gap: 12px; margin-top: 6px; font-size: 11px; color: var(--secondary-text-color, #6b7280); }
  .chart-legend i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; }
  .chart-legend i.dashed { height: 3px; border-radius: 2px; }

  /* ---------- 订单列表 ---------- */
  .order-list { display: flex; flex-direction: column; gap: 7px; }
  .order { border-radius: 10px; overflow: hidden; background: #eef6fb; }
  .order-row {
    display: flex; align-items: center; gap: 8px; padding: 9px 10px; cursor: pointer;
    user-select: none;
  }
  .order-icon {
    width: 26px; height: 26px; border-radius: 50%; background: #2f9be0; color: #fff;
    display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
  }
  .order-main { display: flex; flex-direction: column; min-width: 0; }
  .order-title { font-size: 13.5px; font-weight: 600; white-space: nowrap; }
  .order-sub { font-size: 10.5px; color: var(--secondary-text-color, #8a8a8e); }
  .order-amount { margin-left: auto; font-size: 14px; font-weight: 700; white-space: nowrap; }
  .tag {
    font-size: 11px; padding: 3px 9px; border-radius: 6px; color: #fff; white-space: nowrap;
    font-weight: 600;
  }
  .tag.unpaid { background: ${COLOR_WARN}; }
  .tag.paid { background: #12b76a; }
  .order-chev { color: var(--secondary-text-color, #8a8a8e); display: flex; align-items: center; }
  .order-detail { display: none; padding: 0 10px 10px; background: var(--ha-card-background, #fff); }
  .order.open .order-detail { display: block; }
  .order.open { background: #e6f2fa; }
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; padding: 8px 0 10px; }
  .detail-item { font-size: 12px; display: flex; gap: 2px; }
  .detail-k { color: var(--secondary-text-color, #8a8a8e); white-space: nowrap; }
  .detail-v { font-weight: 500; }
  .detail-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .detail-table th, .detail-table td { padding: 5px 4px; text-align: right; }
  .detail-table th { color: var(--secondary-text-color, #8a8a8e); font-weight: 500; border-bottom: 1px solid var(--jw-border); }
  .detail-table th:first-child, .detail-table td:first-child { text-align: left; }
  .detail-table tbody tr + tr td { border-top: 1px solid rgba(0,0,0,0.04); }
  .empty-cell { text-align: center !important; color: var(--secondary-text-color, #8a8a8e); }
  .detail-table tfoot td { border-top: 1px solid var(--jw-border); padding-top: 7px; }
  .total-label { text-align: right !important; font-weight: 600; }
  .total-value { font-weight: 700; font-size: 13.5px; white-space: nowrap; }

  @media (max-width: 380px) {
    .metric-value { font-size: 17px; }
    .usage-value { font-size: 21px; }
  }
`;

/* ============================================================================
 * 注册
 * ========================================================================== */
if (!customElements.get("jinan-water-card")) {
  customElements.define("jinan-water-card", JinanWaterCard);
}
if (!customElements.get("jinan-water-card-editor")) {
  customElements.define("jinan-water-card-editor", JinanWaterCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "jinan-water-card")) {
  window.customCards.push({
    type: "jinan-water-card",
    name: "济南水务水费卡片",
    description: "水费余额/欠费/违约金、本期用水、日用水曲线、年用水阶梯、水费日历与订单明细",
    preview: true,
    documentationURL: "https://github.com/",
  });
}

console.info(
  `%c济南水务%c jinan-water-card %cv${CARD_VERSION} %c已就绪`,
  "background:#2f9be0;color:#fff;padding:4px 10px;border-radius:6px;font-weight:600;",
  "background:rgba(47,155,224,.15);color:#1b6fa8;padding:4px 8px;border-radius:6px;margin-left:6px;",
  "background:rgba(47,155,224,.15);color:#1b6fa8;padding:4px 8px;border-radius:6px;margin-left:6px;",
  "color:#4caf50;margin-left:6px;",
);
