import ast

main_path = r"C:\Users\denpo\OneDrive\Desktop\Project2\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)
routes = []
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr in ("get", "post", "put", "delete", "websocket"):
                    routes.append((node.name, node.lineno, dec.func.attr))

print("--- FastAPI Endpoints ---")
for rname, lineno, method in routes:
    print(f"Line {lineno}: [{method.upper()}] {rname}")
