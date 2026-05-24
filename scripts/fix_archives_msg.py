"""Update archives.py error message to reflect structure-first validation."""

def main():
    with open(r'src\subtitle_info_collection\engines\archives.py', 'r', encoding='utf-8') as f:
        content = f.read()

    old = '''        raise CollectorError(
            f"下载的载荷不包含大于 {MIN_VALID_SUBTITLE_BYTES // 1024}KB 的有效 ass/srt 字幕",
            ErrorType.DOWNLOAD_FAILED,
        )'''

    new = '''        raise CollectorError(
            "下载的载荷不包含有效的中英双语 ass/srt 字幕",
            ErrorType.DOWNLOAD_FAILED,
        )'''

    if old in content:
        content = content.replace(old, new)
        with open(r'src\subtitle_info_collection\engines\archives.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: Updated archives.py error message')
    else:
        print('NOT FOUND: old archives error message')

if __name__ == '__main__':
    main()
