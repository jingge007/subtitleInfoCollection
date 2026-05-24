with open(r"tests\test_subtitle_engine.py", "rb") as f:
    data = f.read()
# Find line 120 area
text = data.decode("utf-8", errors="replace")
lines = text.split("\n")
print(f"Line 120: {lines[119]}")
# Show hex around the Chinese characters
line_bytes = lines[119].encode("utf-8")
idx = line_bytes.find("assert".encode())
if idx >= 0:
    # Show what's after "assert "
    rest = line_bytes[idx+7:]
    print(f"Bytes after 'assert ': {rest[:50].hex()}")

# Check archives
with open(r"tests\test_archives.py", "rb") as f:
    data = f.read()
text = data.decode("utf-8", errors="replace")
for i, line in enumerate(text.split("\n")):
    if "100KB" in line:
        print(f"archives line {i+1}: {line.strip()}")