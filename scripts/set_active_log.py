with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Find download method and insert _active_log setting
idx = c.find("async def download(self, candidate: SubtitleCandidate, context: DownloadContext)")
if idx < 0:
    print("Not found")
    exit()

# Find the first statement after the method signature
# Look for the first line after the docstring/comment
body_start = c.find("\n        self._emit", idx)
if body_start < 0:
    body_start = c.find("\n        logger", idx)
if body_start < 0:
    body_start = c.find("\n        #", idx)
    # Go past the comment
    body_start = c.find("\n        ", body_start + 1)

# Insert _active_log at the start
insert_code = "\n        # Forward logs to GUI via _active_log\n        _prev_active = self._active_log\n        self._active_log = context.log\n        try:"
# Find where to insert - right after the method signature line
first_line_end = c.find("\n", idx) + 1
c = c[:first_line_end] + insert_code + c[first_line_end:]

# Add finally to restore _active_log
# Find last line before next method
next_def = c.find("\n    async def ", idx + 500)
if next_def < 0:
    next_def = c.find("\n    def ", idx + 500)
if next_def > 0:
    end_of_method = c.rfind("\n", idx, next_def)
    cleanup = """
        finally:
            self._active_log = _prev_active"""
    # Check if finally already exists
    if "finally:" not in c[idx:next_def]:
        # Insert before the last return or before next method
        insert_before = c.rfind("\n        ", idx, next_def)
        if insert_before > 0:
            next_line_start = c.find("\n", insert_before + 1)
            c = c[:next_line_start] + cleanup + c[next_line_start:]

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Set _active_log in download method")