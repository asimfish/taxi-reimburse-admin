# Skill Card: taxi-reimburse-admin

## Identity

- Owner: 北京中关村学院打车报销维护者
- Version: 0.2.0
- Status: maintained
- License: MIT

## Capability manifest

- Reads: 一个月的报销材料目录（每人一个子文件夹）或线上系统归档目录
- Writes: 用户指定的工作/输出目录（材料副本、检查报告、汇总表、打印材料、发票合并、汇总数据.json）
- Executes: `scripts/run.sh` → `uv run` 临时环境运行内置 `reimburse` 包（本地 OCR、PDF 解析、xlsx/PDF 生成）
- Network: 首次运行时 uv 从 PyPI 下载依赖；使用 `--ai` / `fix --ai` 时把识别文字和部分截图发送给 DeepSeek API
- Credentials: 线上管理页密码由管理员本人输入；可选 `DEEPSEEK_API_KEY` 只从环境变量读取，均不写入文件
- External effects: 不发送材料、不提交报销；删除线上提交需管理员明确指示
- Approval gates: 删除或修改任何人的行程前须由管理员确认

## Risks and controls

误把不合规行程计入：每条进汇总表的记录都必须通过凭证匹配，存疑项全部进入“待确认事项”，交付前必须运行 `verify`。原始材料只读。

## Output contract

汇总表 xlsx（可直接打印）、按序号标注的打印材料 PDF、电子发票合并 PDF、出租车支付记录汇总 PDF、verify 结果，以及每人笔数/金额与剩余待确认事项清单。
