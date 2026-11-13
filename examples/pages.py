"""调用方配置的页面识别/切换；默认只识别，不点击、不主动切前台。

pages.json 是模板，不是对任意应用开箱即用的配置。
"""
import argparse
import json
from pathlib import Path

from pymacauto import Application, MacAXError, PageSession, read_table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-id", required=True, help="已运行目标应用")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).with_name("pages.json"))
    parser.add_argument("--to", help="目标页面配置名；与 --execute 一起使用")
    parser.add_argument("--execute", action="store_true", help="明确允许切换页面")
    parser.add_argument("--read-table", action="store_true", help="另读当前确认表格的原始数据")
    args = parser.parse_args(argv)
    if args.to is not None and not args.execute:
        parser.error("切换页面需要 --to 与 --execute；仅识别当前页请省略 --to")
    if args.execute and args.to is None:
        parser.error("--execute 必须明确指定 --to")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        app = Application.connect(bundle_id=args.bundle_id)
        session = PageSession.from_config(app, config)
        observed = session.switch(args.to) if args.to is not None else session.detect()
        # table 是当前原生引用，不直接 JSON 序列化，也不跨切页缓存。
        result = {"page": observed["page"], "headers": observed["headers"]}
        if args.read_table:
            result["snapshot"] = read_table(app.backend, observed["table"])
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (MacAXError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
