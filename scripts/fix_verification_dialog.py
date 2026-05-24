"""Fix verification dialog UI issues in main_window.py."""

def main():
    with open(r'src\subtitle_info_collection\gui\main_window.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Find and replace the captcha container block
    old_block = '''        # Unified captcha container - single adaptive display area
        captcha_container = QVBoxLayout()
        captcha_container.setSpacing(6)

        image_label = QLabel(self)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumHeight(100)
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        pixmap = self._pixmap_from_data_uri(image_data_uri)
        image_label = QLabel(self)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumHeight(100)
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        pixmap = self._pixmap_from_data_uri(image_data_uri)
        captcha_rendered = False
        fallback_label = None

        if not pixmap.isNull():
            # Render captcha (QSvgRenderer handles SVG, QPixmap handles PNG/JPEG)
            image_label.setPixmap(
                pixmap.scaled(480, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            image_label.setStyleSheet(f"border: 1px solid {LINE_SOFT}; border-radius: 8px; padding: 4px;")
            captcha_container.addWidget(image_label)
            captcha_rendered = True
        else:
            logger.info("subhd.captcha.render.fail reason=no_usable_captcha subtitle_id=%s", subtitle_id)

        # Refresh button row
        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_btn = TransparentToolButton(FIF.SYNC, self)
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.setToolTip("刷新验证码")
        refresh_btn.clicked.connect(self._on_captcha_refresh)
        refresh_row.addWidget(refresh_btn)
        captcha_container.addLayout(refresh_row)

        if not captcha_rendered:
            fallback_label = QLabel("验证码加载失败，请点击刷新")
            fallback_label.setAlignment(Qt.AlignCenter)
            fallback_label.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px; padding: 24px;")
            captcha_container.addWidget(fallback_label)

        root.addLayout(captcha_container)

        ocr_label = CaptionLabel("")
        suggested_code = str(payload.get("suggestedCode") or "").strip()
        if suggested_code:
            confidence = float(payload.get("suggestedConfidence") or 0)
            ocr_label.setText(f"OCR 识别: {suggested_code} ({confidence:.0%})")
            ocr_label.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        else:
            localized_msg = self._localize_ocr_message(str(payload.get("ocrMessage") or ""))
            if localized_msg:
                ocr_label.setText(localized_msg)
                ocr_label.setStyleSheet(f"color: {RED}; font-size: 12px;")
        root.addWidget(ocr_label)

        code_input = LineEdit(self)
        if suggested_code:
            code_input.setText(suggested_code)
        code_input.setPlaceholderText("请输入验证码")
        code_input.setFixedHeight(40)
        code_input.setStyleSheet("font-size: 16px; border-radius: 8px;")
        root.addWidget(code_input)

        verification_html = str(payload.get("verificationHtml") or "").strip()
        if verification_html and len(verification_html) > 10:
            browser = QTextBrowser()
            browser.setHtml(verification_html)
            browser.setMaximumHeight(120)
            root.addWidget(browser)'''

    new_block = '''        # Unified captcha container - single adaptive display area
        captcha_container = QVBoxLayout()
        captcha_container.setSpacing(6)

        image_label = QLabel(self)
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumHeight(100)
        image_data_uri = str(payload.get("verificationImageDataUri") or "")
        pixmap = self._pixmap_from_data_uri(image_data_uri)
        captcha_rendered = False
        fallback_html = ""

        if not pixmap.isNull():
            # Render captcha (QSvgRenderer handles SVG, QPixmap handles PNG/JPEG)
            image_label.setPixmap(
                pixmap.scaled(480, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            image_label.setStyleSheet(f"border: 1px solid {LINE_SOFT}; border-radius: 8px; padding: 4px;")
            captcha_container.addWidget(image_label)
            captcha_rendered = True
        else:
            logger.info("subhd.captcha.render.fail reason=no_usable_captcha subtitle_id=%s", subtitle_id)

        # Refresh button row
        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_btn = TransparentToolButton(FIF.SYNC, self)
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.setToolTip("刷新验证码")
        refresh_btn.clicked.connect(self._on_captcha_refresh)
        refresh_row.addWidget(refresh_btn)
        captcha_container.addLayout(refresh_row)

        if not captcha_rendered:
            verification_html = str(payload.get("verificationHtml") or "").strip()
            if verification_html and len(verification_html) > 10:
                # Only show HTML fallback when no image/SVG can be rendered
                browser = QTextBrowser()
                browser.setHtml(verification_html)
                browser.setMaximumHeight(120)
                browser.setStyleSheet(f"border: 1px solid {LINE_SOFT}; border-radius: 6px;")
                captcha_container.addWidget(browser)
            else:
                fallback_label = QLabel("验证码加载失败，请点击刷新")
                fallback_label.setAlignment(Qt.AlignCenter)
                fallback_label.setStyleSheet(f"color: {TEXT_PLACEHOLDER}; font-size: 13px; padding: 24px; border: none;")
                captcha_container.addWidget(fallback_label)

        root.addLayout(captcha_container)

        ocr_label = CaptionLabel("")
        suggested_code = str(payload.get("suggestedCode") or "").strip()
        if suggested_code:
            confidence = float(payload.get("suggestedConfidence") or 0)
            ocr_label.setText(f"OCR 识别: {suggested_code} ({confidence:.0%})")
            ocr_label.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        else:
            localized_msg = self._localize_ocr_message(str(payload.get("ocrMessage") or ""))
            if localized_msg:
                ocr_label.setText(localized_msg)
                ocr_label.setStyleSheet(f"color: {RED}; font-size: 12px;")
        root.addWidget(ocr_label)

        code_input = LineEdit(self)
        if suggested_code:
            code_input.setText(suggested_code)
        code_input.setPlaceholderText("请输入验证码")
        code_input.setFixedHeight(40)
        code_input.setStyleSheet(
            "font-size: 16px; border-radius: 8px; border: 1px solid #d0d0d0; "
            "background: #ffffff; padding: 4px 12px; "
            "selection-background-color: #4a90d9;"
        )
        code_input.setFocus()
        root.addWidget(code_input)'''

    if old_block in content:
        content = content.replace(old_block, new_block)
        with open(r'src\subtitle_info_collection\gui\main_window.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: Verification dialog UI fixed')
    else:
        print('NOT FOUND: old block not found - checking with partial match...')
        # Try to find the unique markers
        markers = [
            'image_label = QLabel(self)',
            'pixmap = self._pixmap_from_data_uri(image_data_uri)',
            'image_label = QLabel(self)',
        ]
        for m in markers:
            idx = content.find(m)
            if idx >= 0:
                ctx_start = max(0, idx - 100)
                ctx_end = min(len(content), idx + 200)
                print(f'Found marker at {idx}')
                print(f'Context: ...{content[ctx_start:ctx_end]}...')
                break

if __name__ == '__main__':
    main()
