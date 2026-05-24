"""Fix subtitle title wrapping in verification dialog."""

def main():
    with open(r'src\subtitle_info_collection\gui\main_window.py', 'r', encoding='utf-8') as f:
        content = f.read()

    old = '''        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        if subtitle_title:
            sub_label = StrongBodyLabel(subtitle_title)
            sub_label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
            root.addWidget(sub_label)'''

    new = '''        subtitle_title = payload.get("subtitleTitle") or payload.get("detailUrl") or ""
        if subtitle_title:
            sub_label = StrongBodyLabel(subtitle_title)
            sub_label.setWordWrap(True)
            sub_label.setMaximumWidth(460)
            sub_label.setStyleSheet(f"color: {TEXT}; font-size: 14px;")
            root.addWidget(sub_label)'''

    if old in content:
        content = content.replace(old, new)
        with open(r'src\subtitle_info_collection\gui\main_window.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: Title wrapping fixed')
    else:
        print('NOT FOUND')

if __name__ == '__main__':
    main()
