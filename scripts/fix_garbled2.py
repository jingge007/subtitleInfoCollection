import sys
sys.stdout.reconfigure(encoding="utf-8")

with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

# Fix garbled markers line
old_garbled = "    garbled_markers = ['\ufffd\ufffd\ufffd?', '???', '\xef\xbf\xbd']"
new_garbled = "    garbled_markers = ['\\ufffd\\ufffd\\ufffd?', '???', '\\xef\\xbf\\xbd']"

if old_garbled in text:
    text = text.replace(old_garbled, new_garbled)
    print("Replaced garbled markers")
else:
    # Try with different encoding
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if "garbled_markers" in line:
            print(f"Line {i+1}: {repr(line[:80])}")
            # Fix it
            lines[i] = "    garbled_markers = ['\\ufffd\\ufffd\\ufffd?', '???', '\\xef\\xbf\\xbd']"
            text = "\n".join(lines)
            print(f"Fixed line {i+1}")
            break

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Done")