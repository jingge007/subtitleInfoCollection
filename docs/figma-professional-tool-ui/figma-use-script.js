// Figma use_figma script for:
// subtitleInfoCollection - Professional Tool UI
// Target file key: 97LLcGvppgQ4lhh0NCbUt5
//
// Run with skillNames: "figma-use,figma-generate-design".
// This script intentionally does not call figma.closePlugin() or figma.notify().

const createdNodeIds = [];
const mutatedNodeIds = [];

const colors = {
  page: "#F5F7FB",
  shell: "#EEF3F8",
  surface: "#FFFFFF",
  surfaceAlt: "#F8FAFC",
  line: "#D7DEE8",
  lineSoft: "#E6EBF2",
  text: "#0F172A",
  textMuted: "#64748B",
  textSoft: "#94A3B8",
  primary: "#2563EB",
  primarySoft: "#E8F0FE",
  primaryDark: "#1D4ED8",
  green: "#15803D",
  greenSoft: "#EAF7EF",
  orange: "#B45309",
  orangeSoft: "#FFF4E5",
  red: "#DC2626",
  redSoft: "#FEECEC",
  violet: "#6D5DD3",
  logBg: "#0B1220",
  logText: "#D8E3F0",
};

const fontState = {};

function hexToRgb(hex) {
  const clean = hex.replace("#", "");
  const value = parseInt(clean, 16);
  return {
    r: ((value >> 16) & 255) / 255,
    g: ((value >> 8) & 255) / 255,
    b: (value & 255) / 255,
  };
}

function solid(hex, opacity = 1) {
  return { type: "SOLID", color: hexToRgb(hex), opacity };
}

function pushNode(node) {
  createdNodeIds.push(node.id);
  return node;
}

async function resolveFonts() {
  const fonts = await figma.listAvailableFontsAsync();
  const byFamily = new Map();
  for (const item of fonts) {
    const list = byFamily.get(item.fontName.family) || [];
    list.push(item.fontName);
    byFamily.set(item.fontName.family, list);
  }
  const family =
    ["Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Source Han Sans SC", "Arial", "Inter"]
      .find(name => byFamily.has(name)) || fonts[0].fontName.family;

  function styleOf(targets) {
    const list = byFamily.get(family) || fonts.map(item => item.fontName);
    for (const target of targets) {
      const found = list.find(font => font.style.toLowerCase() === target.toLowerCase());
      if (found) return found;
    }
    return list[0];
  }

  fontState.regular = styleOf(["Regular", "Normal"]);
  fontState.medium = styleOf(["Medium", "Semi Bold", "Semibold", "Regular", "Normal"]);
  fontState.bold = styleOf(["Bold", "Semi Bold", "Semibold", "Medium", "Regular"]);
  fontState.mono = byFamily.has("JetBrains Mono")
    ? byFamily.get("JetBrains Mono")[0]
    : byFamily.has("Consolas")
      ? byFamily.get("Consolas")[0]
      : fontState.regular;

  await figma.loadFontAsync(fontState.regular);
  await figma.loadFontAsync(fontState.medium);
  await figma.loadFontAsync(fontState.bold);
  await figma.loadFontAsync(fontState.mono);
}

function setFrameBase(node, options = {}) {
  node.fills = [solid(options.fill || colors.surface)];
  node.strokes = options.stroke === false ? [] : [solid(options.stroke || colors.line)];
  node.strokeWeight = options.strokeWeight || 1;
  node.cornerRadius = options.radius ?? 8;
  if (options.effects) {
    node.effects = options.effects;
  }
  return node;
}

function frame(parent, name, x, y, w, h, options = {}) {
  const node = pushNode(figma.createFrame());
  node.name = name;
  node.x = x;
  node.y = y;
  node.resize(w, h);
  node.clipsContent = options.clipsContent ?? false;
  setFrameBase(node, options);
  if (parent) parent.appendChild(node);
  return node;
}

function autoFrame(parent, name, x, y, w, h, options = {}) {
  const node = frame(parent, name, x, y, w, h, options);
  node.layoutMode = options.layoutMode || "VERTICAL";
  node.primaryAxisSizingMode = options.primaryAxisSizingMode || "AUTO";
  node.counterAxisSizingMode = options.counterAxisSizingMode || "FIXED";
  node.itemSpacing = options.gap ?? 8;
  node.paddingTop = options.pt ?? options.p ?? 0;
  node.paddingRight = options.pr ?? options.p ?? 0;
  node.paddingBottom = options.pb ?? options.p ?? 0;
  node.paddingLeft = options.pl ?? options.p ?? 0;
  node.primaryAxisAlignItems = options.primaryAxisAlignItems || "MIN";
  node.counterAxisAlignItems = options.counterAxisAlignItems || "MIN";
  return node;
}

async function label(parent, text, x, y, w, options = {}) {
  const node = pushNode(figma.createText());
  node.name = options.name || `Text / ${text.slice(0, 24)}`;
  node.x = x;
  node.y = y;
  node.resize(w, options.h || 24);
  node.textAutoResize = options.autoResize || "HEIGHT";
  node.fontName = options.font || (options.weight === "bold" ? fontState.bold : options.weight === "medium" ? fontState.medium : fontState.regular);
  node.fontSize = options.size || 14;
  node.lineHeight = { unit: "PIXELS", value: options.lineHeight || Math.round((options.size || 14) * 1.45) };
  node.letterSpacing = { unit: "PIXELS", value: 0 };
  node.fills = [solid(options.color || colors.text)];
  node.characters = text;
  if (options.align) node.textAlignHorizontal = options.align;
  if (parent) parent.appendChild(node);
  return node;
}

function rect(parent, name, x, y, w, h, options = {}) {
  const node = pushNode(figma.createRectangle());
  node.name = name;
  node.x = x;
  node.y = y;
  node.resize(w, h);
  node.fills = [solid(options.fill || colors.surface)];
  node.strokes = options.stroke === false ? [] : [solid(options.stroke || colors.line)];
  node.strokeWeight = options.strokeWeight || 1;
  node.cornerRadius = options.radius ?? 6;
  if (parent) parent.appendChild(node);
  return node;
}

async function badge(parent, text, x, y, tone = "green", w = 86) {
  const toneMap = {
    green: [colors.greenSoft, colors.green],
    orange: [colors.orangeSoft, colors.orange],
    red: [colors.redSoft, colors.red],
    blue: [colors.primarySoft, colors.primary],
    gray: [colors.surfaceAlt, colors.textMuted],
  };
  const [fill, fg] = toneMap[tone] || toneMap.gray;
  const box = rect(parent, `Badge / ${text}`, x, y, w, 26, { fill, stroke: false, radius: 6 });
  await label(parent, text, x + 10, y + 5, w - 20, { size: 12, lineHeight: 16, color: fg, weight: "medium", align: "CENTER" });
  return box;
}

async function button(parent, text, x, y, w, options = {}) {
  const kind = options.kind || "primary";
  const fill = kind === "primary" ? colors.primary : kind === "danger" ? colors.red : colors.surfaceAlt;
  const fg = kind === "primary" || kind === "danger" ? "#FFFFFF" : colors.text;
  const stroke = kind === "primary" || kind === "danger" ? false : colors.line;
  rect(parent, `Button / ${text}`, x, y, w, 34, { fill, stroke, radius: 6 });
  await label(parent, text, x + 12, y + 8, w - 24, { size: 13, lineHeight: 16, color: fg, weight: "medium", align: "CENTER" });
}

async function sectionTitle(parent, title, subtitle, x, y, w) {
  await label(parent, title, x, y, w, { size: 22, lineHeight: 30, weight: "bold" });
  if (subtitle) {
    await label(parent, subtitle, x, y + 34, w, { size: 13, lineHeight: 19, color: colors.textMuted });
  }
}

async function metricCard(parent, title, value, detail, x, y, w = 214) {
  frame(parent, `Metric / ${title}`, x, y, w, 92, { fill: colors.surface, radius: 8 });
  await label(parent, value, x + 16, y + 14, w - 32, { size: 24, lineHeight: 28, weight: "bold" });
  await label(parent, title, x + 16, y + 48, w - 32, { size: 13, lineHeight: 18, color: colors.textMuted, weight: "medium" });
  await label(parent, detail, x + 16, y + 68, w - 32, { size: 11, lineHeight: 14, color: colors.textSoft });
}

async function statusCard(parent, title, state, detail, tone, x, y, w = 250, h = 108) {
  frame(parent, `Status Card / ${title}`, x, y, w, h, { fill: colors.surface, radius: 8 });
  await label(parent, title, x + 14, y + 12, w - 28, { size: 14, lineHeight: 18, weight: "bold" });
  await badge(parent, state, x + 14, y + 38, tone, 82);
  await label(parent, detail, x + 14, y + 70, w - 28, { size: 12, lineHeight: 17, color: colors.textMuted });
}

async function table(parent, name, x, y, w, columns, rows, options = {}) {
  const rowH = options.rowH || 36;
  const headerH = 38;
  const h = headerH + rows.length * rowH;
  frame(parent, name, x, y, w, h, { fill: colors.surface, radius: 8, clipsContent: true });
  rect(parent, `${name} / Header`, x, y, w, headerH, { fill: "#F1F5F9", stroke: false, radius: 8 });
  let cx = x;
  for (const column of columns) {
    await label(parent, column.label, cx + 12, y + 10, column.w - 24, { size: 12, lineHeight: 16, color: colors.text, weight: "bold" });
    cx += column.w;
  }
  for (let r = 0; r < rows.length; r += 1) {
    const yy = y + headerH + r * rowH;
    rect(parent, `${name} / Row ${r + 1}`, x, yy, w, rowH, { fill: r % 2 ? colors.surfaceAlt : colors.surface, stroke: false, radius: 0 });
    rect(parent, `${name} / Row Line ${r + 1}`, x, yy, w, 1, { fill: colors.lineSoft, stroke: false, radius: 0 });
    cx = x;
    for (let c = 0; c < columns.length; c += 1) {
      const value = String(rows[r][c] ?? "");
      await label(parent, value, cx + 12, yy + 9, columns[c].w - 24, {
        size: 12,
        lineHeight: 16,
        color: c === 0 ? colors.text : colors.textMuted,
        weight: c === 0 ? "medium" : "regular",
      });
      cx += columns[c].w;
    }
  }
}

async function logPanel(parent, name, x, y, w, h, lines) {
  frame(parent, name, x, y, w, h, { fill: colors.logBg, stroke: "#1F2937", radius: 8, clipsContent: true });
  await label(parent, "日志流", x + 14, y + 12, w - 28, { size: 13, lineHeight: 18, color: "#F8FAFC", weight: "bold" });
  for (let i = 0; i < lines.length; i += 1) {
    await label(parent, lines[i], x + 14, y + 42 + i * 22, w - 28, {
      size: 12,
      lineHeight: 16,
      color: colors.logText,
      font: fontState.mono,
    });
  }
}

async function sidebar(parent, active) {
  rect(parent, "App Chrome / Sidebar", 0, 0, 220, 840, { fill: colors.surface, stroke: colors.line, radius: 0 });
  await label(parent, "字幕采集工具", 22, 24, 170, { size: 18, lineHeight: 24, weight: "bold" });
  await label(parent, "专业数据运维台", 22, 52, 170, { size: 12, lineHeight: 18, color: colors.textMuted });
  const nav = ["工作台", "采集任务", "字幕解析", "历史记录", "设置与维护"];
  for (let i = 0; i < nav.length; i += 1) {
    const y = 96 + i * 44;
    const isActive = nav[i] === active;
    rect(parent, `Navigation / ${nav[i]}`, 14, y, 192, 36, {
      fill: isActive ? colors.primarySoft : colors.surface,
      stroke: false,
      radius: 6,
    });
    if (isActive) rect(parent, `Navigation / ${nav[i]} Active Rail`, 14, y, 3, 36, { fill: colors.primary, stroke: false, radius: 2 });
    await label(parent, nav[i], 30, y + 9, 150, {
      size: 13,
      lineHeight: 16,
      weight: "medium",
      color: isActive ? colors.primaryDark : colors.text,
    });
  }
  await label(parent, "密钥仅从本机 .env 读取", 22, 778, 176, { size: 12, lineHeight: 18, color: colors.textMuted });
}

function screenFrame(page, name, x, y) {
  const root = frame(page, name, x, y, 1320, 840, { fill: colors.shell, radius: 0, stroke: colors.line });
  rect(root, "Implementation Safe Size / 1320x840", 0, 0, 1320, 840, { fill: colors.shell, stroke: false, radius: 0 });
  return root;
}

async function buildDashboard(page, x, y, variant) {
  const root = screenFrame(page, `工作台 / ${variant}`, x, y);
  await sidebar(root, "工作台");
  await sectionTitle(root, "任务工作台", "集中查看配置状态、近期任务、输出位置和常用操作。", 248, 26, 620);
  await badge(root, variant === "配置可用" ? "配置可用" : "配置缺失", 1130, 30, variant === "配置可用" ? "green" : "orange", 96);
  await button(root, "开始采集", 910, 30, 88);
  await button(root, "解析本地字幕", 1010, 30, 116, { kind: "secondary" });

  const metricY = 98;
  await metricCard(root, "最近任务", "6", "近 30 条内统计", 248, metricY);
  await metricCard(root, "电影数", "482", "movieCount 合计", 476, metricY);
  await metricCard(root, "最佳字幕", "421", "bestCount 合计", 704, metricY);
  await metricCard(root, "失败记录", "61", "failedCount 合计", 932, metricY);
  await metricCard(root, "下载成功", "398", "downloadCount 合计", 1160, metricY, 120);

  frame(root, "Panel / 配置预检", 248, 210, 666, 250, { fill: colors.surface, radius: 8 });
  await label(root, "配置预检", 266, 228, 200, { size: 16, lineHeight: 22, weight: "bold" });
  if (variant === "配置可用") {
    await statusCard(root, ".env", "已创建", "F:\\work\\subtitleInfoCollection\\.env", "green", 266, 268, 196, 80);
    await statusCard(root, "TMDb", "已配置", "电影榜单与本地字幕匹配可用", "green", 478, 268, 196, 80);
    await statusCard(root, "字幕源", "3/3 可用", "SubHD、ASSRT、OpenSubtitles", "green", 690, 268, 196, 80);
    await statusCard(root, "数据目录", "可用", "C:\\Users\\jing1\\subtitleInfoCollection", "green", 266, 362, 302, 80);
    await statusCard(root, "请求间隔", "13000 ms", "已自动限制到安全下限", "blue", 584, 362, 302, 80);
  } else {
    await statusCard(root, ".env", "未找到", "启动时会从 .env.example 创建", "orange", 266, 268, 196, 80);
    await statusCard(root, "TMDb", "缺少 Token", "无法采集电影榜单或匹配本地字幕", "red", 478, 268, 196, 80);
    await statusCard(root, "字幕源", "1/3 可用", "SubHD 可用，ASSRT/OpenSubtitles 待配置", "orange", 690, 268, 196, 80);
    await statusCard(root, "数据目录", "待创建", "应用启动时尝试自动创建", "orange", 266, 362, 302, 80);
    await statusCard(root, "请求间隔", "13000 ms", "来自 .env 的安全运行配置", "blue", 584, 362, 302, 80);
  }

  frame(root, "Panel / 字幕源状态", 936, 210, 328, 250, { fill: colors.surface, radius: 8 });
  await label(root, "字幕源健康", 954, 228, 200, { size: 16, lineHeight: 22, weight: "bold" });
  await statusCard(root, "SubHD", "健康", "命中 183 条，需验证码时弹窗处理", "green", 954, 268, 292, 72);
  await statusCard(root, "ASSRT", variant === "配置可用" ? "健康" : "待配置", variant === "配置可用" ? "命中 112 条" : "需要 ASSRT_TOKEN", variant === "配置可用" ? "green" : "orange", 954, 350, 292, 72);

  frame(root, "Panel / 最近字幕资料", 248, 480, 600, 282, { fill: colors.surface, radius: 8 });
  await label(root, "最近字幕资料", 266, 498, 200, { size: 16, lineHeight: 22, weight: "bold" });
  const records = variant === "配置可用"
    ? [
        ["沙丘2", "OpenSubtitles · 96.5", "Dune.Part.Two.2024.1080p.BluRay.zh-en.ass"],
        ["奥本海默", "SubHD · 94.2", "Oppenheimer.2023.IMAX.Bilingual.srt"],
        ["坠落的审判", "ASSRT · 91.8", "Anatomy.of.a.Fall.2023.zh&en.ass"],
      ]
    : [["暂无字幕结果", "-", "完成一次采集后，这里会展示电影式资料卡。"]];
  for (let i = 0; i < records.length; i += 1) {
    const yy = 538 + i * 68;
    frame(root, `Recent Record / ${i + 1}`, 266, yy, 564, 54, { fill: colors.surfaceAlt, stroke: colors.lineSoft, radius: 6 });
    await label(root, records[i][0], 280, yy + 9, 260, { size: 14, lineHeight: 18, weight: "bold" });
    await label(root, records[i][1], 646, yy + 9, 160, { size: 12, lineHeight: 16, color: colors.textMuted, align: "RIGHT" });
    await label(root, records[i][2], 280, yy + 31, 530, { size: 12, lineHeight: 16, color: colors.textMuted });
  }

  frame(root, "Panel / 输出与维护", 872, 480, 392, 282, { fill: colors.surface, radius: 8 });
  await label(root, "输出与维护", 890, 498, 180, { size: 16, lineHeight: 22, weight: "bold" });
  await label(root, "最近输出", 890, 538, 120, { size: 12, lineHeight: 16, color: colors.textMuted, weight: "medium" });
  await label(root, "C:\\Users\\jing1\\subtitleInfoCollection\\output\\20260430212801-2026-top100", 890, 562, 338, { size: 12, lineHeight: 18, color: colors.text });
  await button(root, "打开最近输出目录", 890, 632, 138, { kind: "secondary" });
  await button(root, "打开数据目录", 1042, 632, 112, { kind: "secondary" });
}

async function buildCollector(page, x, y, state) {
  const root = screenFrame(page, `采集任务 / ${state}`, x, y);
  await sidebar(root, "采集任务");
  await sectionTitle(root, "采集任务", "选择年份、Top 数量、字幕源和下载策略，运行采集工作流。", 248, 26, 760);
  await badge(root, state, 1134, 30, state === "运行中" ? "blue" : state === "完成" ? "green" : state === "失败" ? "red" : "gray", 92);

  frame(root, "Panel / 采集参数", 248, 96, 1016, 132, { fill: colors.surface, radius: 8 });
  await label(root, "采集参数", 266, 114, 180, { size: 16, lineHeight: 22, weight: "bold" });
  const fields = [["年份", "2026"], ["Top 数量", "100"], ["请求间隔", "13000 ms"]];
  for (let i = 0; i < fields.length; i += 1) {
    const xx = 266 + i * 170;
    await label(root, fields[i][0], xx, 154, 80, { size: 12, lineHeight: 16, color: colors.textMuted });
    rect(root, `Input / ${fields[i][0]}`, xx, 176, 130, 32, { fill: colors.surface, stroke: colors.line, radius: 6 });
    await label(root, fields[i][1], xx + 10, 184, 110, { size: 13, lineHeight: 16, color: colors.text });
  }
  const checks = ["SubHD", "ASSRT", "OpenSubtitles", "源兜底", "下载字幕"];
  for (let i = 0; i < checks.length; i += 1) {
    const xx = 790 + (i % 3) * 134;
    const yy = 150 + Math.floor(i / 3) * 34;
    rect(root, `Checkbox / ${checks[i]}`, xx, yy, 16, 16, { fill: colors.primary, stroke: colors.primary, radius: 4 });
    await label(root, checks[i], xx + 24, yy - 1, 104, { size: 13, lineHeight: 18, color: colors.text });
  }
  await button(root, state === "运行中" ? "采集中..." : "开始采集", 1142, 168, 94, { kind: "primary" });

  frame(root, "Panel / 任务状态", 248, 248, 470, 244, { fill: colors.surface, radius: 8 });
  await label(root, "任务状态", 266, 266, 180, { size: 16, lineHeight: 22, weight: "bold" });
  const progress = state === "运行中" ? 0.52 : state === "完成" ? 1 : state === "失败" ? 0.24 : 0;
  await label(root, state === "待运行" ? "等待开始" : state === "失败" ? "任务失败：OpenSubtitles 登录失败" : state === "完成" ? "任务完成" : "52/100 正在采集：沙丘2", 266, 304, 420, { size: 14, lineHeight: 20, color: colors.text, weight: "medium" });
  rect(root, "Progress / Track", 266, 340, 414, 18, { fill: "#EEF2F7", stroke: colors.line, radius: 6 });
  rect(root, "Progress / Value", 266, 340, Math.max(6, 414 * progress), 18, { fill: state === "失败" ? colors.red : colors.primary, stroke: false, radius: 6 });
  await table(root, "Table / 结果摘要", 266, 382, 414, [{ label: "指标", w: 130 }, { label: "值", w: 284 }], [
    ["电影数量", state === "待运行" ? "0" : "100"],
    ["候选字幕", state === "完成" ? "1260" : state === "运行中" ? "642" : "0"],
    ["最佳候选", state === "完成" ? "91" : state === "运行中" ? "48" : "0"],
  ], { rowH: 30 });

  frame(root, "Panel / 运行统计", 740, 248, 524, 244, { fill: colors.surface, radius: 8 });
  await label(root, "运行统计", 758, 266, 160, { size: 16, lineHeight: 22, weight: "bold" });
  await statusCard(root, "SubHD", state === "失败" ? "可用" : "健康", "搜索 52 次 / 命中 183 / 下载 39", "green", 758, 306, 150, 76);
  await statusCard(root, "ASSRT", "健康", "搜索 52 次 / 命中 112 / 下载 8", "green", 922, 306, 150, 76);
  await statusCard(root, "OpenSubtitles", state === "失败" ? "异常" : "健康", state === "失败" ? "API 登录失败，已记录错误类型" : "搜索 52 次 / 命中 347", state === "失败" ? "red" : "green", 1086, 306, 160, 76);
  await label(root, "输出路径", 758, 404, 120, { size: 12, lineHeight: 16, color: colors.textMuted, weight: "medium" });
  await label(root, "output\\20260430212801-2026-top100\\subtitles-20260430212801.zip", 758, 428, 454, { size: 12, lineHeight: 18, color: colors.text });

  await logPanel(root, "Panel / 采集日志", 248, 516, 1016, 246, [
    "[10:28:01] 任务开始：2026 年 Top100，字幕源 subhd, assrt, opensubtitles",
    "[10:28:04] 电影列表数量：100",
    "[10:29:12] [52/100] 采集：沙丘2",
    "[10:29:15] 命中 18 条，推荐：opensubtitles/Dune.Part.Two.2024.zh-en.ass",
    state === "失败" ? "[10:29:16] ERROR OpenSubtitles：登录失败，任务已停止并写入 failed 记录" : "[10:29:16] 字幕下载成功，写入字幕压缩包队列",
  ]);
}

async function buildParser(page, x, y) {
  const root = screenFrame(page, "字幕解析 / 成功失败混合", x, y);
  await sidebar(root, "字幕解析");
  await sectionTitle(root, "字幕解析", "选择本地 SRT/ASS 文件，解析双语字幕并导出电影 JSON 与字幕 JSON。", 248, 26, 820);
  await button(root, "选择 SRT/ASS 文件", 1070, 30, 156);
  await badge(root, "成功 3 / 失败 1", 904, 34, "orange", 132);

  frame(root, "Panel / 文件队列", 248, 96, 1016, 112, { fill: colors.surface, radius: 8 });
  await label(root, "文件队列", 266, 114, 140, { size: 16, lineHeight: 22, weight: "bold" });
  await label(root, "4 个文件排队解析，输出写入：数据目录/parsed", 266, 148, 520, { size: 13, lineHeight: 20, color: colors.textMuted });
  await statusCard(root, "格式支持", "SRT / ASS", "仅解析包含中英文内容的字幕", "blue", 820, 122, 180, 62);
  await statusCard(root, "TMDb 匹配", "可用", "按文件名构造关键词匹配电影", "green", 1018, 122, 180, 62);

  await table(root, "Table / 解析结果", 248, 232, 1016, [
    { label: "文件路径", w: 372 },
    { label: "电影", w: 166 },
    { label: "电影 ID", w: 170 },
    { label: "原始字幕", w: 90 },
    { label: "导出字幕", w: 90 },
    { label: "状态/关键词", w: 128 },
  ], [
    ["F:\\字幕\\Dune.Part.Two.2024.zh-en.ass", "沙丘2", "tmdb-693134", "1482", "936", "Dune Part Two"],
    ["F:\\字幕\\Oppenheimer.2023.Bilingual.srt", "奥本海默", "tmdb-872585", "2031", "1580", "Oppenheimer"],
    ["F:\\字幕\\Anatomy.of.a.Fall.2023.ass", "坠落的审判", "tmdb-915935", "1264", "901", "Anatomy of a Fall"],
    ["F:\\字幕\\Broken.File.zh.srt", "-", "-", "-", "-", "字幕文件无法解码"],
  ], { rowH: 44 });

  await logPanel(root, "Panel / 解析日志", 248, 508, 1016, 254, [
    "[10:40:11] 解析字幕：Dune.Part.Two.2024.zh-en.ass",
    "[10:40:12] 解析字幕：Oppenheimer.2023.Bilingual.srt",
    "[10:40:14] 解析字幕：Anatomy.of.a.Fall.2023.ass",
    "[10:40:15] 解析失败：Broken.File.zh.srt / 字幕文件无法解码",
    "[10:40:16] 电影 JSON：parsed\\20260430-104016-movies.json",
    "[10:40:16] 字幕 JSON：parsed\\20260430-104016-subtitles.json",
  ]);
}

async function buildHistory(page, x, y) {
  const root = screenFrame(page, "历史记录 / 长路径可读", x, y);
  await sidebar(root, "历史记录");
  await sectionTitle(root, "历史记录", "查看最近采集任务状态、参数、开始结束时间和输出目录。", 248, 26, 820);
  await button(root, "刷新历史", 1128, 30, 98, { kind: "secondary" });
  await table(root, "Table / 历史记录", 248, 96, 1016, [
    { label: "ID", w: 56 },
    { label: "状态", w: 96 },
    { label: "年份", w: 76 },
    { label: "Top", w: 70 },
    { label: "开始时间", w: 174 },
    { label: "结束时间", w: 174 },
    { label: "输出目录", w: 370 },
  ], [
    ["24", "completed", "2026", "100", "2026-04-30T14:28:01+00:00", "2026-04-30T15:12:40+00:00", "C:\\Users\\jing1\\subtitleInfoCollection\\output\\20260430212801-2026-top100"],
    ["23", "failed", "2025", "50", "2026-04-30T13:12:00+00:00", "2026-04-30T13:19:22+00:00", "C:\\Users\\jing1\\subtitleInfoCollection\\output\\20260430211200-2025-top50"],
    ["22", "completed", "2024", "30", "2026-04-30T12:04:18+00:00", "2026-04-30T12:34:09+00:00", "D:\\subtitle-data\\output\\20260430200418-2024-top30"],
    ["21", "completed", "2023", "200", "2026-04-29T23:02:01+00:00", "2026-04-30T01:16:40+00:00", "F:\\collections\\subtitleInfoCollection\\output\\20260430070201-2023-top200"],
  ], { rowH: 52 });
}

async function buildSettings(page, x, y) {
  const root = screenFrame(page, "设置与维护 / 危险操作隔离", x, y);
  await sidebar(root, "设置与维护");
  await sectionTitle(root, "设置与维护", "管理数据目录与本地维护操作，密钥和请求策略仍从 .env 读取。", 248, 26, 820);
  frame(root, "Panel / 本机配置", 248, 96, 1016, 176, { fill: colors.surface, radius: 8 });
  await label(root, "本机配置", 266, 114, 180, { size: 16, lineHeight: 22, weight: "bold" });
  await label(root, "数据目录", 266, 158, 120, { size: 13, lineHeight: 18, color: colors.textMuted, weight: "medium" });
  rect(root, "Input / 数据目录", 350, 148, 620, 36, { fill: colors.surface, stroke: colors.line, radius: 6 });
  await label(root, "C:\\Users\\jing1\\subtitleInfoCollection", 362, 157, 590, { size: 13, lineHeight: 18, color: colors.text });
  await button(root, "选择数据目录", 990, 149, 112, { kind: "secondary" });
  await button(root, "保存数据目录", 1114, 149, 112);
  await label(root, "保存后写入 SUBTITLE_COLLECTION_DATA_DIR，并重新初始化当前数据目录下的 SQLite 存储。", 350, 202, 780, { size: 12, lineHeight: 18, color: colors.textMuted });

  frame(root, "Panel / 配置提示", 248, 296, 1016, 168, { fill: colors.surface, radius: 8 });
  await label(root, "配置提示", 266, 314, 180, { size: 16, lineHeight: 22, weight: "bold" });
  await statusCard(root, ".env 密钥", "只读", "TMDB_TOKEN、ASSRT_TOKEN、OpenSubtitles 账号均不在界面编辑。", "blue", 266, 354, 300, 78);
  await statusCard(root, "代理与间隔", "来自 .env", "HTTP_PROXY、HTTPS_PROXY、SUBTITLE_REQUEST_INTERVAL_MS。", "blue", 586, 354, 300, 78);
  await statusCard(root, "源优先级", "来自 .env", "SUBTITLE_PROVIDER_PRIORITY / SUBTITLE_PROVIDER_DISABLED。", "blue", 906, 354, 300, 78);

  frame(root, "Danger Zone / 数据维护", 248, 488, 1016, 210, { fill: "#FFF7F7", stroke: "#F5B8B8", radius: 8 });
  await label(root, "数据维护", 266, 506, 180, { size: 16, lineHeight: 22, weight: "bold", color: "#7F1D1D" });
  await label(root, "危险操作需要明确视觉隔离，且运行中采集任务会禁用维护按钮。", 266, 536, 780, { size: 13, lineHeight: 20, color: "#991B1B" });
  await button(root, "重置历史", 266, 586, 100, { kind: "secondary" });
  await label(root, "清空采集历史记录，保留 output 文件。", 386, 594, 340, { size: 13, lineHeight: 18, color: colors.textMuted });
  await button(root, "删除输出文件", 266, 638, 120, { kind: "danger" });
  await label(root, "删除 数据目录/output 并清空采集历史；不会删除 parsed、数据库或缓存。", 406, 646, 660, { size: 13, lineHeight: 18, color: colors.textMuted });
}

async function buildAuditPage(page) {
  await figma.setCurrentPageAsync(page);
  page.children.forEach(node => node.remove());
  page.backgrounds = [solid(colors.page)];
  const board = frame(page, "Audit Board / Current Structure", 80, 80, 1440, 1180, { fill: colors.page, stroke: false, radius: 0 });
  await sectionTitle(board, "01 Audit - 当前功能结构与视觉问题", "基于 main_window.py 当前基线，只做信息层级和专业工具视觉重组，不改变采集/解析行为。", 0, 0, 1120);
  frame(board, "Audit / Current IA", 0, 90, 420, 338, { fill: colors.surface, radius: 8 });
  await label(board, "现有入口", 22, 112, 200, { size: 16, lineHeight: 22, weight: "bold" });
  const ia = ["工作台：配置预检、近期任务、字幕源状态、输出维护", "采集任务：年份、Top 数量、字幕源、源兜底、下载字幕", "字幕解析：选择 SRT/ASS、结果表格、解析日志", "历史记录：ID、状态、年份、Top、时间、输出目录", "设置与维护：数据目录、重置历史、删除输出文件"];
  for (let i = 0; i < ia.length; i += 1) await label(board, ia[i], 22, 154 + i * 42, 370, { size: 13, lineHeight: 19, color: colors.textMuted });

  frame(board, "Audit / Problems", 450, 90, 450, 338, { fill: colors.surface, radius: 8 });
  await label(board, "视觉与可读性问题", 472, 112, 240, { size: 16, lineHeight: 22, weight: "bold" });
  const problems = ["页面已具备专业工具雏形，但信息权重仍偏平均。", "状态、预检、输出路径、日志需要更明确的分层。", "长路径、长字幕标题需要表格列宽和 tooltip 策略。", "危险操作需要明显隔离，避免和普通设置混在一起。", "1320x840 固定窗口下需要减少纵向滚动和异常留白。"];
  for (let i = 0; i < problems.length; i += 1) await label(board, problems[i], 472, 154 + i * 42, 388, { size: 13, lineHeight: 19, color: colors.textMuted });

  frame(board, "Audit / Invariants", 930, 90, 430, 338, { fill: colors.surface, radius: 8 });
  await label(board, "实现不变量", 952, 112, 200, { size: 16, lineHeight: 22, weight: "bold" });
  const invariants = ["保留 AppStorage.task_center_summary() 数据形状。", "保留 evaluate_config() 预检逻辑与警告来源。", "保留 CollectorWorker / ParserWorker 信号与业务时序。", "后续仅新增 UI helper、objectName、样式表和布局结构。", "不回退当前未提交改动。"];
  for (let i = 0; i < invariants.length; i += 1) await label(board, invariants[i], 952, 154 + i * 42, 360, { size: 13, lineHeight: 19, color: colors.textMuted });

  await table(board, "Audit / State Matrix", 0, 470, 1360, [
    { label: "区域", w: 180 },
    { label: "需要覆盖状态", w: 300 },
    { label: "设计处理", w: 420 },
    { label: "PySide6 映射", w: 460 },
  ], [
    ["工作台", "空数据 / 配置缺失 / 配置可用", "预检卡、指标卡、最近输出、源健康拆分", "refresh_task_center(), _refresh_config_cards(), _refresh_source_status()"],
    ["采集任务", "待运行 / 运行中 / 完成 / 失败", "参数区、运行统计、进度条、结果摘要、日志流", "start_collection(), update_collect_progress(), show_result_summary()"],
    ["字幕解析", "成功 / 失败混合", "队列概览、结果表、错误行、解析日志", "select_parse_files(), add_parse_row(), parse_finished()"],
    ["历史记录", "多行长路径", "固定状态列 + 弹性输出目录列", "refresh_history(), QTableWidget tooltips"],
    ["设置维护", "普通设置 / 危险操作", "危险分区红色隔离，说明保留 parsed/DB/cache", "save_data_dir_to_env(), reset_history(), delete_output_files()"],
  ], { rowH: 58 });
}

async function buildDesignSystemPage(page) {
  await figma.setCurrentPageAsync(page);
  page.children.forEach(node => node.remove());
  page.backgrounds = [solid(colors.page)];
  const board = frame(page, "Design System Board", 80, 80, 1440, 1260, { fill: colors.page, stroke: false, radius: 0 });
  await sectionTitle(board, "02 Design System - 浅色数据运维台", "低饱和蓝色主操作，绿色/橙色/红色状态，高密度表格和日志面板；圆角控制在 8px 以内。", 0, 0, 1180);

  frame(board, "Tokens / Color", 0, 90, 660, 360, { fill: colors.surface, radius: 8 });
  await label(board, "颜色", 22, 112, 120, { size: 16, lineHeight: 22, weight: "bold" });
  const swatches = [
    ["背景", colors.page], ["面板", colors.surface], ["边线", colors.line], ["主文字", colors.text],
    ["次文字", colors.textMuted], ["主操作", colors.primary], ["成功", colors.green], ["警告", colors.orange],
    ["失败", colors.red], ["日志底", colors.logBg],
  ];
  for (let i = 0; i < swatches.length; i += 1) {
    const xx = 22 + (i % 5) * 124;
    const yy = 154 + Math.floor(i / 5) * 96;
    rect(board, `Swatch / ${swatches[i][0]}`, xx, yy, 92, 44, { fill: swatches[i][1], stroke: colors.line, radius: 6 });
    await label(board, swatches[i][0], xx, yy + 54, 92, { size: 12, lineHeight: 16, color: colors.text });
    await label(board, swatches[i][1], xx, yy + 74, 92, { size: 11, lineHeight: 14, color: colors.textMuted });
  }

  frame(board, "Tokens / Typography", 700, 90, 660, 360, { fill: colors.surface, radius: 8 });
  await label(board, "字体与密度", 722, 112, 180, { size: 16, lineHeight: 22, weight: "bold" });
  await label(board, "页面标题 / 24px Bold", 722, 158, 400, { size: 24, lineHeight: 32, weight: "bold" });
  await label(board, "分区标题 / 16px Bold", 722, 210, 400, { size: 16, lineHeight: 22, weight: "bold" });
  await label(board, "正文信息 / 13px Regular - 用于表格、说明、状态详情。", 722, 250, 540, { size: 13, lineHeight: 20, color: colors.textMuted });
  await label(board, "日志文本 / 12px Mono - 保持时间戳和错误详情可扫读。", 722, 290, 540, { size: 12, lineHeight: 18, color: colors.textMuted, font: fontState.mono });
  await label(board, "间距：页面 18-20px，面板 14-16px，表格行高 34-44px，按钮高 34px。", 722, 340, 560, { size: 13, lineHeight: 20, color: colors.textMuted });

  frame(board, "Components / Controls", 0, 490, 660, 320, { fill: colors.surface, radius: 8 });
  await label(board, "控件", 22, 512, 120, { size: 16, lineHeight: 22, weight: "bold" });
  await button(board, "开始采集", 22, 558, 96);
  await button(board, "解析本地字幕", 136, 558, 124, { kind: "secondary" });
  await button(board, "删除输出文件", 278, 558, 120, { kind: "danger" });
  rect(board, "Input / Default", 22, 622, 280, 34, { fill: colors.surface, stroke: colors.line, radius: 6 });
  await label(board, "C:\\Users\\jing1\\subtitleInfoCollection", 34, 630, 250, { size: 13, lineHeight: 18, color: colors.text });
  await badge(board, "健康", 22, 690, "green");
  await badge(board, "待配置", 120, 690, "orange");
  await badge(board, "异常", 218, 690, "red");
  await badge(board, "运行中", 316, 690, "blue");

  frame(board, "Components / Cards", 700, 490, 660, 320, { fill: colors.surface, radius: 8 });
  await label(board, "卡片", 722, 512, 120, { size: 16, lineHeight: 22, weight: "bold" });
  await metricCard(board, "最佳字幕", "421", "bestCount 合计", 722, 558, 180);
  await statusCard(board, "OpenSubtitles", "健康", "搜索 52 次 / 命中 347 / 下载 18", "green", 922, 558, 260, 96);
  await statusCard(board, "TMDb", "缺少 Token", "无法采集电影榜单或匹配本地字幕", "red", 722, 676, 460, 84);

  await table(board, "Components / Table", 0, 850, 660, [
    { label: "文件路径", w: 280 },
    { label: "电影", w: 120 },
    { label: "原始字幕", w: 90 },
    { label: "状态", w: 170 },
  ], [
    ["F:\\字幕\\Dune.Part.Two.2024.zh-en.ass", "沙丘2", "1482", "成功"],
    ["F:\\字幕\\Broken.File.zh.srt", "-", "-", "字幕文件无法解码"],
    ["F:\\字幕\\Oppenheimer.2023.srt", "奥本海默", "2031", "成功"],
  ], { rowH: 42 });
  await logPanel(board, "Components / Log Panel", 700, 850, 660, 200, [
    "[10:28:01] 任务开始：2026 年 Top100",
    "[10:29:12] [52/100] 采集：沙丘2",
    "[10:29:16] 字幕下载成功，写入字幕压缩包队列",
    "[10:29:18] ERROR OpenSubtitles：登录失败，已记录错误类型",
  ]);
}

async function buildScreensPage(page) {
  await figma.setCurrentPageAsync(page);
  page.children.forEach(node => node.remove());
  page.backgrounds = [solid(colors.page)];
  await label(page, "03 Screens - 完整应用界面高保真稿", 80, 42, 760, { size: 24, lineHeight: 32, weight: "bold" });
  await label(page, "所有核心流程按 1320x840 可实现窗口绘制；每个框架保留 1440px 桌面设计语境和高信息密度。", 80, 78, 900, { size: 13, lineHeight: 20, color: colors.textMuted });
  await buildDashboard(page, 80, 130, "配置可用");
  await buildDashboard(page, 1460, 130, "配置缺失");
  await buildCollector(page, 80, 1040, "待运行");
  await buildCollector(page, 1460, 1040, "运行中");
  await buildCollector(page, 80, 1950, "完成");
  await buildCollector(page, 1460, 1950, "失败");
  await buildParser(page, 80, 2860);
  await buildHistory(page, 1460, 2860);
  await buildSettings(page, 80, 3770);
}

async function ensurePages() {
  const names = ["01 Audit", "02 Design System", "03 Screens"];
  const pages = {};
  for (let i = 0; i < names.length; i += 1) {
    let page = figma.root.children.find(p => p.name === names[i]);
    if (!page) {
      if (i === 0 && figma.root.children.length === 1 && figma.root.children[0].children.length === 0) {
        page = figma.root.children[0];
        page.name = names[i];
        mutatedNodeIds.push(page.id);
      } else {
        page = figma.createPage();
        page.name = names[i];
        createdNodeIds.push(page.id);
      }
    }
    pages[names[i]] = page;
  }
  return pages;
}

await resolveFonts();
const pages = await ensurePages();
await buildAuditPage(pages["01 Audit"]);
await buildDesignSystemPage(pages["02 Design System"]);
await buildScreensPage(pages["03 Screens"]);
await figma.setCurrentPageAsync(pages["03 Screens"]);

return {
  success: true,
  fileKey: figma.fileKey,
  pages: Object.keys(pages),
  fontFamily: fontState.regular.family,
  createdNodeIds,
  mutatedNodeIds,
  notes: [
    "Built 01 Audit, 02 Design System, and 03 Screens.",
    "Screens use real current subtitleInfoCollection labels and 1320x840 implementation-safe frames.",
    "Business logic mapping remains UI-only for later PySide6 implementation.",
  ],
};
