# taxi-reimburse-admin · 打车报销月度汇总 skill（管理员）

北京中关村学院打车报销管理员用的 AI 助手 skill，可用于 Cursor、Claude Code、Codex。它把一个月所有人的打车报销材料逐人检查，核对“金额 - 发票 - 支付记录 - 行程单”是否全部对应，然后生成可以直接打印的月度汇总材料。

## 输出

- `YYYY年M月打车行程汇总.xlsx`：含“行程汇总”“核对明细”“待确认事项”三个工作表。行程汇总为 A4 横向、宽度缩放到一页、竖向分页、每页重复表头。
- `YYYY年M月_打印材料_已标序号.pdf`：出租车支付截图和网约车行程单，每一笔都标上汇总表序号；补充截图紧跟在对应那笔后面。
- `YYYY年M月_网约车电子发票合并.pdf`。
- `YYYY年M月_出租车支付记录汇总.pdf`：先按人、再按出租车发票编号（乘车时间先后）排列，用来对照纸质发票人工核对。
- `检查报告/姓名.txt|json` 和 `汇总数据.json`。

## 安装

```bash
git clone https://github.com/asimfish/taxi-reimburse-admin ~/.cursor/skills/taxi-reimburse-admin
# Claude Code: ~/.claude/skills/   Codex: ~/.codex/skills/
```

依赖：推荐安装 [uv](https://docs.astral.sh/uv/)，首次运行会自动准备临时环境；也可以用 Python 3.9–3.12 手动安装 `pymupdf openpyxl rapidocr_onnxruntime pillow pypinyin`。

## 使用

对助手说：

> 使用 taxi-reimburse-admin 汇总 2026 年 10 月的打车报销，材料在 ~/Desktop/报销/2026-10（每人一个子文件夹）

也可以直接运行：

```bash
bash scripts/run.sh summary <月份目录> --month 2026-10 --out <输出目录>
bash scripts/run.sh verify  <输出目录>
bash scripts/run.sh check   <个人目录> --name 张三 --month 2026-10 [--ai]
bash scripts/run.sh fix     <个人目录> --name 张三 --month 2026-10 --out <新目录> [--ai]
```

原始材料只读。skill 会先复制到工作目录，再在副本上处理。交付前必须运行 `verify`，它会检查以下几项：

- 序号连续，合计金额正确；
- 每笔金额都和凭证对得上；
- 打印材料上的序号能读出，且按顺序排列。

## 可选配置（环境变量）

| 变量 | 作用 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 配合 `--ai` 使用：模型复核，以及看不懂的截图交给视觉模型识别 |
| `REIMBURSE_BUYER_TAX_ID` | 设置后同时校验发票税号 |

使用 `--ai` 时，识别出的文字和部分截图会发送给 DeepSeek API。

## License

MIT
