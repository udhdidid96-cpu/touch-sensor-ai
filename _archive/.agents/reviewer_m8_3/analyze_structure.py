import ast
import re

main_path = r"C:\Users\denpo\OneDrive\Desktop\Project2\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    code = f.read()

lines = code.splitlines()
print(f"Total lines in main.py: {len(lines)}")

# Find key sections
routes = []
classes = []
functions = []

tree = ast.parse(code)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        functions.append((node.name, node.lineno))
    elif isinstance(node, ast.ClassDef):
        classes.append((node.name, node.lineno))

print("\n--- Key Classes ---")
for name, lineno in classes[:20]:
    print(f"Line {lineno}: class {name}")

print("\n--- Key Functions (Sample) ---")
for name, lineno in functions[:30]:
    print(f"Line {lineno}: def {name}")
