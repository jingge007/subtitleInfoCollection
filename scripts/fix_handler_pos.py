with open(r"src\subtitle_info_collection\adapters\subhd.py", "r", encoding="utf-8") as f:
    c = f.read()

# Remove the incorrectly placed handler code (inside a dict literal)
bad_block = '''
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

if bad_block in c:
    c = c.replace(bad_block, "\n")
    print("Removed broken handler block")

# Also remove the misplaced finally block  
bad_finally = '''
        finally:
            if _gui_handler:
                _gui_logger = _logging.getLogger(__name__)
                _gui_logger.removeHandler(_gui_handler)
'''
if bad_finally in c:
    c = c.replace(bad_finally, "")
    print("Removed broken finally block")

with open(r"src\subtitle_info_collection\adapters\subhd.py", "w", encoding="utf-8") as f:
    f.write(c)
print("Fixed")