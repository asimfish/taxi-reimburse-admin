import argparse
import json
import sys
from pathlib import Path

from .checks import check_submission
from .config import load_config
from .report_text import report_to_text


def _json_default(o):
    return str(o)


def run_check(a, cfg):
    from . import ai

    hook = ai.vision_hook(cfg, a.cache, a.month[:4]) if a.ai else None
    rep = check_submission(Path(a.folder), a.name, a.month, cfg, cache_dir=a.cache, image_hook=hook)
    return ai.review(rep, cfg, a.cache) if a.ai else rep


def cmd_check(a):
    cfg = load_config(a.config)
    rep = run_check(a, cfg)
    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")
    print(report_to_text(rep))
    return 0 if rep["passed"] else 1


def cmd_fix(a):
    from . import ai

    cfg = load_config(a.config)
    rep = run_check(a, cfg)
    res = ai.build_fix(rep, Path(a.folder), Path(a.out), cfg, a.cache)
    print(res["text"])
    print(f"\n修改版材料：{res['dir']}\n压缩包：{res['zip']}")
    return 0


def cmd_summary(a):
    from .summary import build_from_folders

    cfg = load_config(a.config)
    out = build_from_folders(Path(a.input), a.month, Path(a.out), cfg, cache_dir=a.cache)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=_json_default))
    return 0


def cmd_template(a):
    from .template import write_template

    write_template(Path(a.out))
    print(a.out)
    return 0


def cmd_verify(a):
    from .verify import verify_month

    res = verify_month(Path(a.dir))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["ok"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="reimburse", description="打车报销材料检查与月度汇总")
    p.add_argument("--config", help="配置文件 config.json（可选）")
    p.add_argument("--cache", help="OCR 缓存目录（可选）")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="检查一个人一个月的材料")
    c.add_argument("folder")
    c.add_argument("--name", required=True)
    c.add_argument("--month", required=True, help="YYYY-MM")
    c.add_argument("--json", help="同时输出 JSON 报告")
    c.add_argument("--ai", action="store_true", help="启用模型复核（需要 DEEPSEEK_API_KEY）")
    c.set_defaults(func=cmd_check)
    f = sub.add_parser("fix", help="按凭证自动修改汇总表，输出修改版材料目录和压缩包（不改原文件）")
    f.add_argument("folder")
    f.add_argument("--name", required=True)
    f.add_argument("--month", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--ai", action="store_true", help="用模型修改公务事由（需要 DEEPSEEK_API_KEY）")
    f.set_defaults(func=cmd_fix)
    s = sub.add_parser("summary", help="按人名子文件夹批量检查并生成月度汇总")
    s.add_argument("input", help="目录下每个子文件夹为一个人（文件夹名=姓名）")
    s.add_argument("--month", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_summary)
    t = sub.add_parser("template", help="生成个人汇总表模板")
    t.add_argument("out")
    t.set_defaults(func=cmd_template)
    v = sub.add_parser("verify", help="核对已生成的月度汇总目录")
    v.add_argument("dir")
    v.set_defaults(func=cmd_verify)
    a = p.parse_args(argv)
    sys.exit(a.func(a))
