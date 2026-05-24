with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
print(repr(lines[258]))
lines[258] = "    garbled_markers = ['\u9519\u8bef', '???', 'error']\n"
with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Fixed")
