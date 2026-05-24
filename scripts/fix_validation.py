"""Fix subtitle validation: structure-first instead of 100KB threshold."""

def main():
    with open(r'src\subtitle_info_collection\engines\subtitle_engine.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update MIN_VALID_SUBTITLE_BYTES to a lower floor (10KB) and add MIN_VALID_ENTRY_COUNT
    old_const = '''MIN_VALID_SUBTITLE_BYTES = 100 * 1024'''
    new_const = '''# 最小有效文件大小（仅作极端兜底，优先使用结构校验）
MIN_VALID_SUBTITLE_BYTES = 10 * 1024
# 最小有效字幕条目数：低于此值视为无效电影字幕
MIN_VALID_SUBTITLE_ENTRIES = 5'''

    if old_const in content:
        content = content.replace(old_const, new_const)
        print('OK: Updated MIN_VALID_SUBTITLE_BYTES and added MIN_VALID_SUBTITLE_ENTRIES')
    else:
        print('NOT FOUND: old MIN_VALID_SUBTITLE_BYTES')

    # 2. Fix the validate_downloaded_subtitle_bytes function to use structure-first validation
    old_block = '''    if len(data) < MIN_VALID_SUBTITLE_BYTES:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason=(
                "字幕文件小于 100KB，判定为无效电影字幕"
                f"（当前 {len(data) / 1024:.1f} KB）"
            ),
            subtitle_format=normalized_format,
            min_bilingual_ratio=required_ratio,
        )

    decoded = decode_subtitle_bytes(data)
    max_replacements = 20 if lenient else 5
    min_score = -500 if lenient else -100
    if not decoded.content or decoded.replacement_count > max_replacements or decoded.score < min_score:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.DECODE_FAILED,
            reason="下载到的字幕无法可靠解码",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            min_bilingual_ratio=required_ratio,
        )

    entries = parse_subtitle_text(decoded.content, normalized_format, "validation")
    bilingual_count = 0
    chinese_only_count = 0
    english_only_count = 0
    for item in entries:
        has_chinese = bool(item.zh_content.strip())
        has_english = bool(item.en_content.strip())
        if has_chinese and has_english:
            bilingual_count += 1
        elif has_chinese:
            chinese_only_count += 1
        elif has_english:
            english_only_count += 1

    entry_count = bilingual_count + chinese_only_count + english_only_count
    bilingual_ratio = bilingual_count / entry_count if entry_count else 0.0

    if entry_count > 0 and bilingual_ratio >= required_ratio:
        return DownloadValidation(
            valid=True,
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content.lstrip("\\ufeff"),
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    if entry_count <= 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason="下载到的字幕没有包含有效的中文或英文对白",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=0,
            bilingual_ratio=0.0,
            min_bilingual_ratio=required_ratio,
        )

    return DownloadValidation(
        valid=False,
        error_type=ErrorType.CONTENT_VALIDATION_FAILED,
        reason=(
            f"双语条目占比 {_format_percent(bilingual_ratio)}，"
            f"低于配置阈值 {_format_percent(required_ratio)}"
            f"（有效条目 {entry_count}，双语 {bilingual_count}，"
            f"中文-only {chinese_only_count}，英文-only {english_only_count}）"
        ),
        subtitle_format=normalized_format,
        encoding=decoded.encoding,
        content=decoded.content,
        entry_count=entry_count,
        bilingual_count=bilingual_count,
        chinese_only_count=chinese_only_count,
        english_only_count=english_only_count,
        bilingual_ratio=bilingual_ratio,
        min_bilingual_ratio=required_ratio,
    )'''

    new_block = '''    # 结构校验优先：先解析字幕条目，用条目数判断有效性
    decoded = decode_subtitle_bytes(data)
    max_replacements = 20 if lenient else 5
    min_score = -500 if lenient else -100
    if not decoded.content or decoded.replacement_count > max_replacements or decoded.score < min_score:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.DECODE_FAILED,
            reason="下载到的字幕无法可靠解码",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            min_bilingual_ratio=required_ratio,
        )

    entries = parse_subtitle_text(decoded.content, normalized_format, "validation")
    bilingual_count = 0
    chinese_only_count = 0
    english_only_count = 0
    for item in entries:
        has_chinese = bool(item.zh_content.strip())
        has_english = bool(item.en_content.strip())
        if has_chinese and has_english:
            bilingual_count += 1
        elif has_chinese:
            chinese_only_count += 1
        elif has_english:
            english_only_count += 1

    entry_count = bilingual_count + chinese_only_count + english_only_count
    bilingual_ratio = bilingual_count / entry_count if entry_count else 0.0

    # 结构校验：条目数不足视为无效
    if entry_count < MIN_VALID_SUBTITLE_ENTRIES:
        # 额外检查文件大小作为兜底（仅当文件极其小时才用大小判定）
        if len(data) < MIN_VALID_SUBTITLE_BYTES:
            return DownloadValidation(
                valid=False,
                error_type=ErrorType.CONTENT_VALIDATION_FAILED,
                reason=(
                    "字幕条目过少且文件过小，判定为无效电影字幕"
                    f"（条目数 {entry_count}，文件大小 {len(data) / 1024:.1f} KB）"
                ),
                subtitle_format=normalized_format,
                encoding=decoded.encoding,
                content=decoded.content,
                entry_count=entry_count,
                bilingual_count=bilingual_count,
                chinese_only_count=chinese_only_count,
                english_only_count=english_only_count,
                bilingual_ratio=bilingual_ratio,
                min_bilingual_ratio=required_ratio,
            )
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason=(
                "字幕条目过少，判定为无效电影字幕"
                f"（条目数 {entry_count}，文件大小 {len(data) / 1024:.1f} KB）"
            ),
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    if entry_count > 0 and bilingual_ratio >= required_ratio:
        return DownloadValidation(
            valid=True,
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content.lstrip("\\ufeff"),
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    if entry_count <= 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason="下载到的字幕没有包含有效的中文或英文对白",
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=0,
            bilingual_ratio=0.0,
            min_bilingual_ratio=required_ratio,
        )

    # 英文-only 检测：中文条目占比过低 -> 拒绝保存
    if bilingual_count == 0 and chinese_only_count == 0 and english_only_count > 0:
        return DownloadValidation(
            valid=False,
            error_type=ErrorType.CONTENT_VALIDATION_FAILED,
            reason=(
                "该字幕为纯英文，非简体中英双语字幕"
                f"（有效条目 {entry_count}，英文 {english_only_count}，"
                f"文件大小 {len(data) / 1024:.1f} KB）"
            ),
            subtitle_format=normalized_format,
            encoding=decoded.encoding,
            content=decoded.content,
            entry_count=entry_count,
            bilingual_count=bilingual_count,
            chinese_only_count=chinese_only_count,
            english_only_count=english_only_count,
            bilingual_ratio=bilingual_ratio,
            min_bilingual_ratio=required_ratio,
        )

    return DownloadValidation(
        valid=False,
        error_type=ErrorType.CONTENT_VALIDATION_FAILED,
        reason=(
            f"双语条目占比 {_format_percent(bilingual_ratio)}，"
            f"低于配置阈值 {_format_percent(required_ratio)}"
            f"（有效条目 {entry_count}，双语 {bilingual_count}，"
            f"中文-only {chinese_only_count}，英文-only {english_only_count}，"
            f"文件大小 {len(data) / 1024:.1f} KB）"
        ),
        subtitle_format=normalized_format,
        encoding=decoded.encoding,
        content=decoded.content,
        entry_count=entry_count,
        bilingual_count=bilingual_count,
        chinese_only_count=chinese_only_count,
        english_only_count=english_only_count,
        bilingual_ratio=bilingual_ratio,
        min_bilingual_ratio=required_ratio,
    )'''

    if old_block in content:
        content = content.replace(old_block, new_block)
        print('OK: Updated validate_downloaded_subtitle_bytes to structure-first')
    else:
        print('NOT FOUND: old validation block')
        # Write debug info
        marker = 'if len(data) < MIN_VALID_SUBTITLE_BYTES:'
        idx = content.find(marker)
        if idx >= 0:
            print(f'Found marker at {idx}')
            print(repr(content[idx-50:idx+200]))

    # 3. Update the size check in main_window.py (parse file validation)
    with open(r'src\subtitle_info_collection\gui\main_window.py', 'r', encoding='utf-8') as f:
        gui_content = f.read()

    old_gui = '（文件过小，< 100 KB 视作无效电影字幕）'
    new_gui = '（文件过小或条目数不足，视作无效电影字幕）'
    if old_gui in gui_content:
        gui_content = gui_content.replace(old_gui, new_gui)
        with open(r'src\subtitle_info_collection\gui\main_window.py', 'w', encoding='utf-8') as f:
            f.write(gui_content)
        print('OK: Updated GUI file validation message')

    with open(r'src\subtitle_info_collection\engines\subtitle_engine.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    main()
