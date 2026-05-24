with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Find captcha block
idx = c.find('data.get("success") and data.get("pass") is False')
end = c.find("\n\n            ", idx + 50)
if end < 0:
    end = c.find("\n            return None", idx + 100)
block = c[idx:end]
print(f"Block at {idx}-{end}:")
for i, line in enumerate(block.split("\n")):
    print(f"{i}: {repr(line[:120])}")