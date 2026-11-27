from __future__ import annotations

from subtitle_info_collection.engines.tokenizer import (
    tokenize_movie_name,
    tokenize_subtitle_content,
    merge_deduplicate,
)


class TestTokenizerMovieName:
    """tokenize_movie_name 电影名分词测试"""

    def test_chinese_title(self):
        """中文片名：'肖申克的救赎' → 完整片名/关键单字出现，停用词'的'被过滤"""
        tokens = tokenize_movie_name(
            title_zh='肖申克的救赎',
            title='The Shawshank Redemption',
            original_title='The Shawshank Redemption',
            year=1994,
        )
        assert '肖申克的救赎' in tokens, f'full title missing, got {tokens}'
        assert '的' not in tokens, f'stop word 的 should be filtered, got {tokens}'
        assert '1994' in tokens, f'year token missing, got {tokens}'

    def test_english_title(self):
        """英文片名小写化、停用词 the 被过滤"""
        tokens = tokenize_movie_name(
            title_zh='',
            title='The Shawshank Redemption',
            original_title='The Shawshank Redemption',
            year=0,
        )
        assert 'shawshank' in tokens, f'missing shawshank, got {tokens}'
        assert 'redemption' in tokens, f'missing redemption, got {tokens}'
        assert 'the' not in tokens, f'stop word the should be filtered, got {tokens}'

    def test_year_included(self):
        """年份数字出现在 token 中"""
        tokens = tokenize_movie_name(
            title_zh='',
            title='Inception',
            original_title='',
            year=2010,
        )
        assert '2010' in tokens, f'missing year token, got {tokens}'

    def test_year_zero(self):
        """year=0 时不应出现年份数字"""
        tokens = tokenize_movie_name(
            title_zh='黑客帝国',
            title='The Matrix',
            original_title='',
            year=0,
        )
        assert '0' not in tokens, f'year 0 should not appear, got {tokens}'

    def test_empty_input(self):
        """空输入返回空列表"""
        tokens = tokenize_movie_name(
            title_zh='',
            title='',
            original_title='',
            year=0,
        )
        assert isinstance(tokens, list)
        assert len(tokens) == 0

    def test_short_english_filtered(self):
        """单字母英文单词不出现"""
        tokens = tokenize_movie_name(
            title_zh='',
            title='A B C',
            original_title='',
            year=0,
        )
        assert 'a' not in tokens

    def test_chinese_characters_appear(self):
        """中文片名中的单字应出现（fallback 模式, jieba 不可用时）"""
        tokens = tokenize_movie_name(
            title_zh='功夫',
            title='Kung Fu Hustle',
            original_title='',
            year=2004,
        )
        assert '2004' in tokens
        assert 'kung' in tokens
        assert 'hustle' in tokens


class TestTokenizerSubtitleContent:
    """tokenize_subtitle_content 字幕分词测试"""

    def test_chinese_subtitle(self):
        """中文字幕：'希望是美好的事物' → 关键 token 出现"""
        tokens = tokenize_subtitle_content(
            zh_content='希望是美好的事物',
            en_content='',
        )
        # 在 jieba 模式或 fallback 模式中应有中文有意义 token 出现
        chinese_tokens = [t for t in tokens if any('\u4e00' <= c <= '\u9fff' for c in t)]
        assert len(chinese_tokens) > 0, f'no Chinese tokens, got {tokens}'

    def test_english_subtitle(self):
        """英文字幕：'Hope is a good thing' → 含 hope good thing"""
        tokens = tokenize_subtitle_content(
            zh_content='',
            en_content='Hope is a good thing',
        )
        assert 'hope' in tokens, f'missing hope, got {tokens}'
        assert 'good' in tokens, f'missing good, got {tokens}'
        assert 'thing' in tokens, f'missing thing, got {tokens}'
        assert 'is' not in tokens, f'stop word is should be filtered, got {tokens}'
        assert 'a' not in tokens, f'stop word a should be filtered, got {tokens}'

    def test_bilingual_subtitle(self):
        """中英混合：中文和英文 token 都出现"""
        tokens = tokenize_subtitle_content(
            zh_content='希望是美好的事物',
            en_content='Hope is a good thing',
        )
        assert 'hope' in tokens
        chinese_tokens = [t for t in tokens if any('\u4e00' <= c <= '\u9fff' for c in t)]
        assert len(chinese_tokens) > 0, f'no Chinese tokens, got {tokens}'

    def test_empty_input(self):
        """空输入返回空列表"""
        tokens = tokenize_subtitle_content(
            zh_content='',
            en_content='',
        )
        assert isinstance(tokens, list)
        assert len(tokens) == 0

    def test_max_tokens_trimming(self):
        """max_tokens 截断生效"""
        zh = ' '.join(['测试' for _ in range(100)])
        en = ' '.join(['word' for _ in range(100)])
        tokens = tokenize_subtitle_content(
            zh_content=zh,
            en_content=en,
            max_tokens=10,
        )
        assert len(tokens) <= 10, f'tokens should be <= 10, got {len(tokens)}'


class TestMergeDeduplicate:
    """merge_deduplicate 测试"""

    def test_basic_merge(self):
        """基本合并去重"""
        result = merge_deduplicate(
            ['a', 'b', 'c'],
            ['b', 'c', 'd'],
        )
        assert set(result) == {'a', 'b', 'c', 'd'}

    def test_order_by_length(self):
        """按长度降序排列"""
        result = merge_deduplicate(
            ['hello', 'hi', 'world'],
        )
        assert result == ['hello', 'world', 'hi'], f'unexpected order: {result}'

    def test_empty_inputs(self):
        """空输入返回空列表"""
        result = merge_deduplicate()
        assert result == []
