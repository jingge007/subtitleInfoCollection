with open(r"tests\test_subtitle_engine.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
print(f"Line 120: {repr(lines[119])}")

with open(r"tests\test_archives.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "100KB" in line:
        print(f"Line {i+1}: {repr(line)}")