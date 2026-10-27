import json
import os
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "taxi-reimburse" / "config.json"

DEFAULTS = {
    "unit": "北京中关村学院",
    "buyer_name": "北京中关村学院",
    # 税号不写进代码：在配置文件里填写 buyer_tax_id，或设置环境变量 REIMBURSE_BUYER_TAX_ID；为空时只核对抬头名称
    "buyer_tax_id": "",
    # 模型检查（OpenAI 兼容接口）；api_key 只从环境变量或私有配置文件读取
    "llm": {
        "enabled": True,
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "vision_model": "deepseek-flash",
        "timeout": 300,
    },
    # 地点类别：识别起止地与公务事由里提到的地点
    "place_groups": {
        "学院": ["中关村学院", "海淀大悦信息科技园", "大悦信息科技园", "学院", "学校", "单位"],
        "实验场地": ["海龙大厦", "海龙", "实验场地", "真机实验", "实验室场地"],
        "地铁站": ["地铁", "永丰站"],
        "合作单位": ["合作单位", "合作方", "璞跃", "深势科技", "深势", "北理", "北京理工", "plugandplay", "plug and play", "智源", "北京大学", "北大"],
    },
    # 出现即判为不可解释的地点（不通过）
    "forbidden_place_keywords": ["银行", "派出所", "出入境", "医院", "政务服务", "营业厅", "4s店"],
    # 出现需要说明的地点（提醒）
    "suspicious_place_keywords": ["小区", "公寓", "家园", "酒店", "宾馆", "商场", "购物中心", "万达", "餐厅", "饭店", "机场", "火车站", "高铁站", "电影", "ktv"],
    "vague_reasons": ["打车", "出行", "交通", "办事", "有事", "外出", "回家", "无", "待补充", "待确认", "/", "-"],
    "roster": [],
}


def load_config(path=None):
    """依次合并：默认值、~/.config/taxi-reimburse/config.json、$REIMBURSE_CONFIG、显式传入的 path，最后是 $REIMBURSE_BUYER_TAX_ID。"""
    cfg = json.loads(json.dumps(DEFAULTS))
    for p in (USER_CONFIG, os.environ.get("REIMBURSE_CONFIG"), path):
        if p and Path(p).is_file():
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            llm = data.pop("llm", None)
            cfg.update(data)
            if llm:
                cfg["llm"].update(llm)
    if os.environ.get("REIMBURSE_BUYER_TAX_ID"):
        cfg["buyer_tax_id"] = os.environ["REIMBURSE_BUYER_TAX_ID"].strip()
    return cfg


def tax_hint(cfg):
    return f"，税号 {cfg['buyer_tax_id']}" if cfg.get("buyer_tax_id") else ""
