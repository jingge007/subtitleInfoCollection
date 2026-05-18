"""Quick SubHD download test for 肖申克的救赎."""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

from subtitle_info_collection.adapters.subhd import SubhdProvider
from subtitle_info_collection.adapters.base import DownloadContext
from subtitle_info_collection.models import MovieInfo


async def main():
    movie = MovieInfo(
        movie_id="tmdb-278",
        tmdb_id=278,
        title="The Shawshank Redemption",
        original_title="The Shawshank Redemption",
        title_zh="肖申克的救赎",
        year=1994,
        rating=8.7,
        vote_count=26000,
    )

    provider = SubhdProvider()

    print("\n========== 开始搜索 ==========")
    candidates = await provider.search(movie)
    print(f"\n搜索结果: {len(candidates)} 个候选字幕\n")

    if not candidates:
        print("❌ 没有找到候选字幕")
        return

    for i, c in enumerate(candidates):
        print(f"  [{i + 1}] {c.subtitle_title}")
        print(f"      语言: {c.language_type}, 格式: {c.subtitle_format}")
        print(f"      详情: {c.detail_url}")
        print()

    candidate = candidates[0]
    print(f"========== 开始下载候选 1: {candidate.subtitle_title} ==========\n")

    context = DownloadContext(
        captcha_ocr_enabled=True,
        captcha_auto_submit_min_confidence=0.85,
        log=lambda msg: print(f"  [LOG] {msg}"),
        request_verification=None,
    )

    try:
        results = await provider.download(candidate, context)
        for r in results:
            print(f"\n✅ 下载成功!")
            print(f"   文件名: {r.file_name}")
            print(f"   大小: {len(r.content):,} bytes")
            print(f"   来源: {r.source_url}")
            print(f"   内容类型: {r.content_type}")
            output_path = f"output_{r.file_name}"
            with open(output_path, "wb") as f:
                f.write(r.content)
            print(f"   已保存到: {output_path}")
    except Exception as e:
        print(f"\n❌ 下载失败: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
