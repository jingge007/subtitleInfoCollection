# Fix test assertions that no longer match after validation changes

# 1. test_subtitle_engine.py
with open(r"tests\test_subtitle_engine.py", "r", encoding="utf-8") as f:
    c = f.read()

# Line 120: change assertion
old = 'assert "\u6709\u6548\u6761\u76ee\u6570\u4e0d\u8db3" in validation.reason'
new = 'assert "\u6761\u76ee\u6570" in validation.reason and "\u6587\u4ef6\u5927\u5c0f" in validation.reason'
if old in c:
    c = c.replace(old, new)
    print("Fixed test: rejects_small_movie_subtitle_file")

# Line 195: change assertion
old2 = 'assert "\u82f1\u6587-only 4000" in validation.reason'
new2 = 'assert "\u7eaf\u82f1\u6587" in validation.reason and "4000" in validation.reason'
if old2 in c:
    c = c.replace(old2, new2)
    print("Fixed test: rejects_english_only_content")

with open(r"tests\test_subtitle_engine.py", "w", encoding="utf-8") as f:
    f.write(c)

# 2. test_archives.py
with open(r"tests\test_archives.py", "r", encoding="utf-8") as f:
    c = f.read()

old_a = 'match="\u5c0f\u4e8e 100KB"'
new_a = 'match="\u65e0\u6548\u7684\u7535\u5f71\u5b57\u5e55"'
if old_a in c:
    c = c.replace(old_a, new_a)
    print("Fixed test: archives small subtitle")
else:
    # Alternative: the match might use \u5c0f\u4e8e 100KB
    idx = c.find("100KB")
    if idx > 0:
        line = c[c.rfind("\n", 0, idx):c.find("\n", idx)]
        print(f"Found 100KB at: {repr(line)}")

with open(r"tests\test_archives.py", "w", encoding="utf-8") as f:
    f.write(c)

print("Done")