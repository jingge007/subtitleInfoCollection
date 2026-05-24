import re

with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Find download method start
idx = c.find("async def download(self, candidate: SubtitleCandidate, context: DownloadContext)")
if idx < 0:
    print("Download method not found")
    exit()

# Find the first real statement line after the method signature
warmup_idx = c.find("/down/", idx)
if warmup_idx < 0:
    print("Warmup block not found")
    exit()

# Find the line start before warmup
block_start = c.rfind("\n", idx, warmup_idx) + 1

# Handler code to insert
handler_code = '''
        # Install temporary GUI log forwarder
        _gui_handler = None
        if context.log:
            import logging as _logging
            class _GuiLogHandler(_logging.Handler):
                def emit(self, record):
                    try:
                        msg = self.format(record)
                        context.log("[{time}] subhd {level} {msg}".format(
                            time=datetime.now().strftime("%H:%M:%S"),
                            level=record.levelname.lower(),
                            msg=msg,
                        ))
                    except Exception:
                        pass
            _gui_logger = _logging.getLogger(__name__)
            _gui_handler = _GuiLogHandler()
            _gui_handler.setLevel(_logging.INFO)
            _gui_handler.setFormatter(_logging.Formatter("%(message)s"))
            _gui_logger.addHandler(_gui_handler)
        try:
'''

c = c[:block_start] + handler_code + c[block_start:]

# Add finally clause at end of method
next_def = c.find("\n    async def ", warmup_idx + 3000)
if next_def < 0:
    next_def = c.find("\n    def ", warmup_idx + 3000)
if next_def > 0:
    end_of_method = c.rfind("\n", idx, next_def)
    cleanup_code = """
        finally:
            if _gui_handler:
                _gui_logger = _logging.getLogger(__name__)
                _gui_logger.removeHandler(_gui_handler)
"""
    # Find the last line before the next method
    # Insert before the next method's def
    insert_point = c.rfind("\n    ", idx, next_def)
    if "finally:" not in c[idx:next_def]:
        c = c[:insert_point + 1] + cleanup_code + c[insert_point + 1:]

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Installed GUI log forwarder")