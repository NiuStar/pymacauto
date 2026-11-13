"""只读示例：列应用、列目标窗口，或读取显式指定的 AXTable。

示例身份与控件标识需要替换为你自己的目标；不启动应用、不修改 UI。
"""
import argparse
import json

from pymacauto import Application, MacAXError, window_scope


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-id", help="已运行应用的 bundle identifier")
    parser.add_argument("--window-identifier", help="唯一的顶层窗口标识")
    parser.add_argument("--table-identifier", help="窗口内唯一的 AXTable 标识")
    args = parser.parse_args(argv)
    if args.window_identifier and not args.bundle_id:
        parser.error("--window-identifier 需要 --bundle-id")
    if args.table_identifier and not (args.bundle_id and args.window_identifier):
        parser.error("--table-identifier 需要 --bundle-id 和 --window-identifier")
    try:
        if not args.bundle_id:
            result = Application.list_apps()
        else:
            app = Application.connect(bundle_id=args.bundle_id)
            if args.table_identifier:
                # 结构查询停在表格边界；严格表格读取再单独展开数据。
                scope = window_scope(
                    app, identifier=args.window_identifier, leaf_roles=("AXTable",)
                )
                table = scope.find(role="AXTable", identifier=args.table_identifier)
                result = table.read_table(timeout=15, max_cells=100_000)
            elif args.window_identifier:
                window = window_scope(app, identifier=args.window_identifier)
                from pymacauto import Element
                element = Element(app, window.root)
                result = {"title": element.get("AXTitle"),
                          "identifier": element.get("AXIdentifier")}
            else:
                result = [{"title": window.get("AXTitle"),
                           "identifier": window.get("AXIdentifier")}
                          for window in app.windows()]
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (MacAXError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
