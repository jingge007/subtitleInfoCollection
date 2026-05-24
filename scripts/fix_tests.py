import re

# Fix test_subtitle_engine.py
with open(r"tests\test_subtitle_engine.py", "r", encoding="utf-8") as f:
    c = f.read()

# Fix 1: rejects_small_movie_subtitle_file - check for new message
old1 = 'assert "\u6709\u6548\u6761\u76ee\u6570\u4e0d\u8db3" in validation.reason'  # 有效条目数不足
if old1 not in c:
    # Original assertion - replace it
    old1_orig = 'assert "\u5c0f\u4e8e 100KB" in validation.reason'  # 小于 100KB
    new1 = 'assert "\u6761\u76ee\u6570" in validation.reason  # now reports entry count instead of file size'
    if old1_orig in c:
        c = c.replace(old1_orig, new1)
        print("Fixed test 1: small movie subtitle file")

# Fix 2: rejects_english_only_content - new message includes file size
old2_orig = 'assert "\u82f1\u6587-only" in validation.reason and "4000" in validation.reason'
new2 = 'assert "\u7eaf\u82f1\u6587" in validation.reason and "\u975e\u7b80\u4f53\u4e2d\u82f1\u53cc\u8bed" in validation.reason'
if old2_orig in c:
    c = c.replace(old2_orig, new2)
    print("Fixed test 2: english only content")
elif 'english_only' in c:
    # Find the line
    idx = c.find('english_only')
    print(f"Found at {idx}: {repr(c[idx:idx+120])}")

with open(r"tests\test_subtitle_engine.py", "w", encoding="utf-8") as f:
    f.write(c)

# Fix test_archives.py
with open(r"tests\test_archives.py", "r", encoding="utf-8") as f:
    c = f.read()

old_a = 'match="\u5c0f\u4e8e 100KB"'  # 小于 100KB
new_a = 'match="\u65e0\u6548\u7684\u7535\u5f71\u5b57\u5e55"'  # 无效的电影字幕
if old_a in c:
    c = c.replace(old_a, new_a)
    print("Fixed test archives: small subtitle")
else:
    # Try regex match
    idx = c.find('100KB')
    if idx > 0:
        print(f"Found 100KB at {idx}: {repr(c[idx-30:idx+30])}")

with open(r"tests\test_archives.py", "w", encoding="utf-8") as f:
    f.write(c)

print("Done updating tests")