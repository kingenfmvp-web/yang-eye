const pptxgen = require("pptxgenjs");
const { applyTheme } = require("/root/.claude/skills/synced/6d688f5d-ef3a-4bec-88fa-9a380eed87e0_450854a6-3676-4c92-9a59-e6b59e338421/pptx/scripts/apply_theme.js");

const THEME = {
  name: "Yang Eye",
  headFontFace: "Microsoft JhengHei",
  bodyFontFace: "Microsoft JhengHei",
  colors: {
    dk1: "1F2430", lt1: "FFFFFF", dk2: "14213D", lt2: "F1F3F7",
    accent1: "F2A541", accent2: "2A78D6", accent3: "1BAF7A", accent4: "E5534B",
    accent5: "8A94A6", accent6: "6C5CE7", hlink: "2A78D6", folHlink: "6C5CE7",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "陽之眼模擬帳戶現行規則";
pres.author = "陽之眼計畫";
const C = pres.SchemeColor;

const FOOT = "陽之眼計畫｜研究用模擬，不構成投資建議";
pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.3, w: 11.7, h: 1.4, fontSize: 44, bold: true, color: C.background1, valign: "middle", align: "left" }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.8, w: 11.7, h: 2.8, fontSize: 20, color: C.accent1, valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.9, fontSize: 34, bold: true, color: C.text2, valign: "middle", align: "left" }, text: "" } },
    { text: { text: FOOT, options: { x: 0.6, y: 7.0, w: 8, h: 0.3, fontSize: 10, color: C.accent5, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent5 },
});

let n = 0;
const nm = (s) => `${s}_${++n}`;
const card = (slide, x, y, w, h, fill = C.background2) =>
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { type: "none" }, rectRadius: 0.12, objectName: nm("card") });
const dot = (slide, x, y, label, fill = C.accent1, color = C.text2, d = 0.55) => {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: nm("dot") });
  slide.addText(label, { x, y, w: d, h: d, align: "center", valign: "middle", fontSize: 16, bold: true, color, margin: 0, isTextBox: true, objectName: nm("dotlabel") });
};
const txt = (slide, text, o) => slide.addText(text, { isTextBox: true, margin: 0, color: C.text1, fontSize: 15, valign: "top", objectName: nm("t"), ...o });

// 1. 封面
pres.addSection({ title: "總覽" });
let s = pres.addSlide({ masterName: "DARK", sectionTitle: "總覽" });
s.addText("陽之眼模擬帳戶：現行規則", { placeholder: "title" });
s.addText("2026-10-28 版｜11/11 換股起改用 v0.8 選股條件", { placeholder: "body" });
s.addNotes("說明目前模擬帳戶的完整規則：資金配置、選股池、選股條件、換股與成交、每日運作與監控，以及這套規則的回測依據。");

// 2. 一張圖看懂
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "總覽" });
s.addText("一半放 0050，一半買營收加速成長的股票", { placeholder: "title" });
card(s, 0.6, 1.6, 5.8, 4.9, C.text2);
txt(s, "50%", { x: 1.0, y: 2.0, w: 5, h: 1.3, fontSize: 72, bold: true, color: C.accent1 });
txt(s, "核心：0050", { x: 1.0, y: 3.4, w: 5, h: 0.6, fontSize: 24, bold: true, color: C.background1 });
txt(s, "跟著大盤走，降低整體波動\n選股選不滿 10 檔時，空出來的位置也買 0050", { x: 1.0, y: 4.2, w: 5.1, h: 1.8, fontSize: 16, color: C.background1, paraSpaceAfter: 6 });
card(s, 6.9, 1.6, 5.8, 4.9);
txt(s, "50%", { x: 7.3, y: 2.0, w: 5, h: 1.3, fontSize: 72, bold: true, color: C.accent2 });
txt(s, "衛星：營收動能選股", { x: 7.3, y: 3.4, w: 5, h: 0.6, fontSize: 24, bold: true, color: C.text2 });
txt(s, "最多 10 檔，每檔約占帳戶 5%\n每月換股一次，換股時把比例調回 50 / 50", { x: 7.3, y: 4.2, w: 5.1, h: 1.8, fontSize: 16, paraSpaceAfter: 6 });
s.addNotes("核心衛星配置：0050 負責穩定，衛星負責超額報酬。初始資金 100 萬，2026-10-20 收盤建倉。");

// 3. 選股池
pres.addSection({ title: "選股規則" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "選股規則" });
s.addText("第一步：先圈出夠大、夠活躍的 140 檔", { placeholder: "title" });
const pool = [
  ["上市普通股", "排除 ETF、特別股、存託憑證等"],
  ["近 20 日平均成交金額前 140 名", "每次換股當天重新排名，只用換股前的資料"],
  ["上市滿 6 個月", "剛上市的股票資料太少，不列入"],
  ["近 20 日均量 > 1,000 張", "流動性不足的股票不買"],
];
pool.forEach(([h, d], i) => {
  const y = 1.65 + i * 1.25;
  dot(s, 0.8, y + 0.1, String(i + 1), C.accent2, C.background1);
  txt(s, h, { x: 1.6, y, w: 6.2, h: 0.45, fontSize: 20, bold: true, color: C.text2 });
  txt(s, d, { x: 1.6, y: y + 0.5, w: 6.2, h: 0.5, fontSize: 15, color: C.accent5 });
});
card(s, 8.4, 1.65, 4.3, 4.85, C.background2);
txt(s, "140", { x: 8.8, y: 2.1, w: 3.5, h: 1.3, fontSize: 72, bold: true, color: C.accent2 });
txt(s, "檔候選股", { x: 8.8, y: 3.4, w: 3.5, h: 0.5, fontSize: 22, bold: true, color: C.text2 });
txt(s, "回測時用「當時」的排名，包含後來下市的股票，避免只看到活下來的贏家。", { x: 8.8, y: 4.2, w: 3.6, h: 1.8, fontSize: 15 });
s.addNotes("選股池是時點正確的：每次換股只用當時看得到的成交資料。v0.7 對照另外把上櫃前 140 名也加進來。");

// 4. 選股條件
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "選股規則" });
s.addText("第二步：營收要「又高、又快、還在加速」", { placeholder: "title" });
const conds = [
  ["近 3 月營收年增 > 20%", "成長要夠快", false],
  ["當月營收創 12 個月新高", "成長還在延續", false],
  ["年增率比前 3 個月平均更高", "成長正在加速", false],
  ["近 3 月營收合計 ≥ 3 億", "去年同期也要 ≥ 1.5 億，排除基期太低", true],
  ["前一天收盤在 120 日均線之上", "用股價確認：營收好但股價還在跌的不買", true],
];
conds.forEach(([h, d, isNew], i) => {
  const col = i < 3 ? 0 : 1;
  const row = i < 3 ? i : i - 3;
  const x = col === 0 ? 0.6 : 6.9, y = 1.6 + row * 1.6;
  card(s, x, y, 5.8, 1.35, isNew ? C.accent1 : C.background2);
  txt(s, h, { x: x + 0.3, y: y + 0.2, w: 5.2, h: 0.5, fontSize: 19, bold: true, color: C.text2 });
  txt(s, d, { x: x + 0.3, y: y + 0.75, w: 5.2, h: 0.45, fontSize: 15, color: C.text1 });
});
txt(s, "橘色＝v0.8 新增，11/11 換股起生效", { x: 6.9, y: 4.85 + 0.05 + 1.6, w: 5.8, h: 0.35, fontSize: 13, color: C.accent5 });
s.addNotes("營收要等次月 10 日公告，所以 m 月營收只在 m+1 月 11 日之後使用。v0.8 的兩條新條件見 reports/v08_report.md。");

// 5. 排序與分散
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "選股規則" });
s.addText("第三步：排序、分散、補空位", { placeholder: "title" });
const steps = [
  ["排序", "通過條件的股票，依近 3 月營收年增率由高到低排"],
  ["取前 10 檔", "每檔約占帳戶 5%（衛星的十分之一）"],
  ["同產業最多 3 檔", "避免全部擠在同一個產業"],
  ["選不滿就補 0050", "例如只選到 7 檔，剩下 3 格的錢買 0050"],
];
steps.forEach(([h, d], i) => {
  const x = 0.6 + i * 3.1;
  card(s, x, 1.7, 2.85, 3.2);
  dot(s, x + 0.3, 2.0, String(i + 1), C.accent1, C.text2);
  txt(s, h, { x: x + 0.3, y: 2.8, w: 2.3, h: 0.5, fontSize: 20, bold: true, color: C.text2 });
  txt(s, d, { x: x + 0.3, y: 3.4, w: 2.3, h: 1.4, fontSize: 15 });
  if (i < 3) s.addShape(pres.shapes.RIGHT_TRIANGLE, { x: x + 2.9, y: 3.15, w: 0.15, h: 0.3, rotate: 90, fill: { color: C.accent5 }, line: { type: "none" }, objectName: nm("arrow") });
});
card(s, 0.6, 5.3, 12.1, 1.3, C.background2);
txt(s, "注意：「同產業」是交易所的產業分類。一週下來發現，10 檔裡有 7 檔其實都是 AI 供應鏈，產業上限擋不住這種主題集中，所以另外每天記錄 AI 占比（第 8 頁）。", { x: 0.9, y: 5.5, w: 11.5, h: 0.95, fontSize: 15 });

// 6. 換股與成交
pres.addSection({ title: "執行" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "執行" });
s.addText("換股時點與成交規則：只做真的做得到的單", { placeholder: "title" });
const tl = [
  ["每月 10 日", "上市公司公告上月營收的期限"],
  ["11 日起第一個交易日", "用剛公告的營收選股，當天收盤價換股"],
  ["新股收漲停", "不追，那一格現金保留，之後第一個沒漲停的交易日再買"],
  ["要賣的股收跌停", "延到之後第一個沒跌停的交易日再賣"],
];
s.addShape(pres.shapes.LINE, { x: 1.0, y: 2.2, w: 11.3, h: 0, line: { color: HEX.accent5, width: 2 }, objectName: nm("timeline") });
tl.forEach(([h, d], i) => {
  const x = 0.6 + i * 3.1;
  dot(s, x + 0.2, 1.92, String(i + 1), i >= 2 ? C.accent4 : C.accent2, C.background1);
  txt(s, h, { x, y: 2.75, w: 2.85, h: 0.5, fontSize: 19, bold: true, color: C.text2 });
  txt(s, d, { x, y: 3.3, w: 2.85, h: 1.4, fontSize: 15 });
});
card(s, 0.6, 5.0, 12.1, 1.3, C.background2);
txt(s, [
  { text: "交易成本：", options: { bold: true, color: C.text2 } },
  { text: "手續費 0.1425%（每筆最低 20 元），賣出另收證交稅 0.3%；股數取整數，可買零股。", options: { breakLine: true } },
  { text: "除權息：", options: { bold: true, color: C.text2 } },
  { text: "股利自動再投入（調整持股股數），分割與面額變更也會調整。" },
], { x: 0.9, y: 5.2, w: 11.5, h: 0.95, fontSize: 15, paraSpaceAfter: 6 });
s.addNotes("漲停不追的規則來自 reports/limits_report.md：回測假設漲停也買得到，每年多算約 2.5 個百分點。");

// 7. 每日運作
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "執行" });
s.addText("每天自動跑：兩個排程、一個儀表板", { placeholder: "title" });
const ops = [
  ["08:10", "週一～五", "盤前參考", "前一晚費半、那斯達克、台積電 ADR，以及 0050 預估開盤跳空。只是參考，不影響換股", C.accent1],
  ["10:10", "週一～六", "帳本更新", "證交所收盤資料隔天早上才發布，所以記錄前一個交易日。沒有新資料就略過，只更新「最後檢查」", C.accent2],
];
ops.forEach(([t, d, h, desc, col], i) => {
  const y = 1.6 + i * 2.15;
  card(s, 0.6, y, 12.1, 1.9, C.background2);
  txt(s, t, { x: 0.9, y: y + 0.25, w: 2.6, h: 0.9, fontSize: 44, bold: true, color: col });
  txt(s, d, { x: 0.9, y: y + 1.2, w: 2.6, h: 0.4, fontSize: 14, color: C.accent5 });
  txt(s, h, { x: 3.8, y: y + 0.25, w: 8.6, h: 0.5, fontSize: 21, bold: true, color: C.text2 });
  txt(s, desc, { x: 3.8, y: y + 0.8, w: 8.6, h: 0.95, fontSize: 15 });
});
txt(s, "資料來源：證交所與櫃買中心 OpenAPI（每日行情）、FinMind（營收、除權息、加權報酬指數，用自己的 token）", { x: 0.6, y: 6.1, w: 12.1, h: 0.6, fontSize: 14, color: C.accent5 });

// 8. 對照與監控
pres.addSection({ title: "監控與依據" });
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "監控與依據" });
s.addText("同時記錄四條線，加上 AI 集中度", { placeholder: "title" });
const lines = [
  ["模擬帳戶", "正式跑的這一組", C.accent1],
  ["加權報酬指數", "大盤（含息），判斷有沒有贏大盤", C.accent5],
  ["選股池等權重", "140 檔各買一樣多，判斷選股有沒有用", C.accent3],
  ["v0.7 對照", "選股池加入上櫃前 140 名，只記錄不換", C.accent6],
];
lines.forEach(([h, d, col], i) => {
  const x = i % 2 === 0 ? 0.6 : 4.55, y = 1.6 + Math.floor(i / 2) * 2.0;
  card(s, x, y, 3.75, 1.8);
  s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.32, w: 0.3, h: 0.3, fill: { color: col }, line: { type: "none" }, objectName: nm("legend") });
  txt(s, h, { x: x + 0.75, y: y + 0.25, w: 2.8, h: 0.45, fontSize: 19, bold: true, color: C.text2 });
  txt(s, d, { x: x + 0.3, y: y + 0.85, w: 3.25, h: 0.85, fontSize: 14 });
});
card(s, 8.6, 1.6, 4.1, 3.8, C.text2);
txt(s, "35%", { x: 8.9, y: 1.9, w: 3.5, h: 1.2, fontSize: 64, bold: true, color: C.accent1 });
txt(s, "AI 供應鏈占淨值", { x: 8.9, y: 3.1, w: 3.5, h: 0.5, fontSize: 19, bold: true, color: C.background1 });
txt(s, "衛星 10 檔中 7 檔屬 AI 供應鏈，0050 另約半數是台積電。只記錄、不影響選股。", { x: 8.9, y: 3.7, w: 3.5, h: 1.5, fontSize: 14, color: C.background1 });
txt(s, "AI 子產業分群取自 ToAlpha 產業輪動頁，每月換股前更新", { x: 0.6, y: 5.75, w: 12.1, h: 0.4, fontSize: 13, color: C.accent5 });

// 9. 回測依據
s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "監控與依據" });
s.addText("為什麼用這套規則：回測多賺一點，但跌得也更深", { placeholder: "title" });
const chartOpts = (title, colors) => ({
  x: 0, y: 0, w: 6.0, h: 4.3, barDir: "bar", showTitle: true, title, titleFontSize: 16, titleColor: HEX.dk2, titleFontFace: "+mj-lt",
  chartColors: colors, showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 13, dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
  dataLabelFormatCode: '0.0"%"', catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt",
  valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
});
const labels = ["0050（含息）", "核心衛星 v0.3", "核心衛星 v0.8"];
s.addChart(pres.charts.BAR, [{ name: "年化報酬", labels, values: [20.9, 22.7, 24.0] }],
  { ...chartOpts("年化報酬（2015–2026）", [HEX.accent5, HEX.accent2, HEX.accent1]), x: 0.6, y: 1.5, objectName: "chart_cagr" });
s.addChart(pres.charts.BAR, [{ name: "最大回撤", labels, values: [34.0, 46.3, 43.9] }],
  { ...chartOpts("最大回撤（越短越好）", [HEX.accent5, HEX.accent2, HEX.accent4]), x: 6.7, y: 1.5, objectName: "chart_dd" });
txt(s, "已扣手續費、證交稅、每邊 0.1% 滑價，並套用漲停延後買。Sharpe：0050 1.09、v0.8 1.10，幾乎打平。累計已測約 20 個版本，數字要保守看待。", { x: 0.6, y: 6.0, w: 12.1, h: 0.75, fontSize: 14, color: C.accent5 });
s.addNotes("數據來自 reports/v08_report.md 的核心衛星表（含漲停延後與滑價）。最大回撤以正值呈現長度，實際為 -34.0%、-46.3%、-43.9%。");

// 10. 現況與下一步
s = pres.addSlide({ masterName: "DARK", sectionTitle: "監控與依據" });
s.addText("現況與下一步", { placeholder: "title" });
txt(s, [
  { text: "10/27 收盤：模擬帳戶 -2.1%、大盤 -0.4%（才 3 個交易日，屬正常波動）", options: { bullet: true, breakLine: true } },
  { text: "11/10 演練第一次 v0.8 換股；11/11 正式換股", options: { bullet: true, breakLine: true } },
  { text: "至少累積 6～12 個月紀錄再評估，不因短期輸贏改規則", options: { bullet: true } },
], { x: 0.8, y: 3.8, w: 11.7, h: 2.2, fontSize: 20, color: C.background1, paraSpaceAfter: 10 });

(async () => {
  const out = "/home/user/yang-eye/docs/陽之眼模擬帳戶規則.pptx";
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
