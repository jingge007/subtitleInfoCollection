"""
SubHD download using agent-browser - real browser to bypass Cloudflare.
This script uses a real Chrome browser to interact with SubHD website.

Usage:
    python tests/test_subhd_agent_browser.py [--headed]

Options:
    --headed    Open browser in headed mode (visible window)
"""

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class AgentBrowserSubHD:
    def __init__(self, headed: bool = False, download_dir: Optional[Path] = None):
        self.headed = headed
        self.download_dir = download_dir or Path("D:/资料/subtitleInfoCollection/downloads")
        self.download_dir.mkdir(exist_ok=True)

    def _run_command(self, args: list[str], timeout: int = 60) -> dict:
        cmd = ["agent-browser"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"raw": result.stdout, "stderr": result.stderr}
            return {"returncode": result.returncode, "stderr": result.stderr}
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        except Exception as e:
            return {"error": str(e)}

    def _run_command_chain(self, commands: list[list[str]], timeout: int = 120) -> list[dict]:
        results = []
        for cmd in commands:
            result = self._run_command(cmd, timeout=timeout)
            results.append(result)
            if result.get("error"):
                logger.warning(f"Command failed: {' '.join(cmd)} - {result.get('error')}")
        return results

    async def open_browser(self):
        logger.info("Opening browser...")
        args = []
        if self.headed:
            args.append("--headed")
        args.extend(["open", "https://subhd.tv"])
        self._run_command(args, timeout=120)
        await asyncio.sleep(3)

    async def wait_for_page(self, timeout_ms: int = 30000):
        self._run_command(["wait", "--load", "networkidle"])
        await asyncio.sleep(2)

    async def get_page_snapshot(self) -> dict:
        result = self._run_command(["snapshot", "-i"])
        return result if "items" in result else {"items": []}

    async def find_and_click(self, text: str, click: bool = True) -> bool:
        result = self._run_command(["find", "text", text, "click" if click else ""])
        await asyncio.sleep(1)
        return result.get("returncode", 1) == 0 or result.get("raw") == "✓ Done"

    async def click_element(self, ref: str) -> dict:
        return self._run_command(["click", ref])

    async def fill_input(self, ref: str, text: str) -> dict:
        return self._run_command(["fill", ref, text])

    async def press_key(self, key: str) -> dict:
        return self._run_command(["press", key])

    async def get_url(self) -> str:
        result = self._run_command(["get", "url"])
        return result.get("url", "")

    async def navigate(self, url: str):
        self._run_command(["open", url], timeout=120)
        await asyncio.sleep(3)
        await self.wait_for_page()

    async def wait(self, ms: int):
        self._run_command(["wait", str(ms)])
        await asyncio.sleep(ms / 1000)

    async def screenshot(self, name: str) -> Path:
        path = self.download_dir / name
        self._run_command(["screenshot", str(path)])
        return path

    async def close(self):
        self._run_command(["close"])

    async def search_subtitle(self, keyword: str) -> list[dict]:
        logger.info(f"Searching for: {keyword}")

        search_url = f"https://subhd.tv/search/{keyword}"
        await self.navigate(search_url)
        await self.wait_for_page()
        await self.wait(2000)

        snapshot = await self.get_page_snapshot()
        items = snapshot.get("items", [])

        subtitle_links = []
        for item in items:
            href = item.get("href", "") or ""
            if "/a/" in href:
                text = item.get("text", "") or ""
                if keyword in text or any(kw in text for kw in ["字幕", "subtitle", ".ass", ".srt"]):
                    subtitle_links.append({
                        "text": text,
                        "href": href,
                        "ref": item.get("ref", ""),
                    })
                    logger.info(f"  Found: {text[:60]}...")

        return subtitle_links

    async def download_subtitle(self, subtitle_id: str) -> Optional[Path]:
        logger.info(f"Downloading subtitle: {subtitle_id}")

        detail_url = f"https://subhd.tv/a/{subtitle_id}"
        await self.navigate(detail_url)
        await self.wait_for_page()
        await self.wait(2000)

        snapshot = await self.get_page_snapshot()
        items = snapshot.get("items", [])

        download_btn = None
        for item in items:
            text = item.get("text", "") or ""
            if "下载" in text or "down" in text.lower():
                download_btn = item
                break

        if not download_btn:
            logger.warning("Download button not found, taking screenshot...")
            await self.screenshot("download_page.png")
            return None

        logger.info(f"Clicking download button: {download_btn.get('ref', '')}")
        await self.click_element(download_btn.get("ref", ""))

        await asyncio.sleep(5)
        await self.wait_for_page()

        down_url = f"https://subhd.tv/down/{subtitle_id}"
        logger.info(f"Navigating to download page: {down_url}")
        await self.navigate(down_url)
        await self.wait_for_page()
        await self.wait(3000)

        snapshot = await self.get_page_snapshot()
        items = snapshot.get("items", [])

        for item in items:
            text = item.get("text", "") or ""
            if "下载" in text:
                logger.info(f"Clicking final download: {item.get('ref', '')}")
                await self.click_element(item.get("ref", ""))
                await asyncio.sleep(5)
                break

        await self.screenshot("final_download.png")

        downloaded = list(self.download_dir.glob("*.zip")) + \
                     list(self.download_dir.glob("*.rar")) + \
                     list(self.download_dir.glob("*.7z"))

        if downloaded:
            latest = max(downloaded, key=lambda p: p.stat().st_mtime)
            logger.info(f"Downloaded file: {latest.name}")
            return latest

        logger.warning("No download file found")
        return None


async def manual_workflow():
    """Interactive workflow with headed browser for manual verification."""
    browser = AgentBrowserSubHD(headed=True)

    print("\n" + "=" * 60)
    print("SubHD 字幕下载 - 使用真实浏览器")
    print("=" * 60)
    print("\n浏览器将以可视化模式打开，您可以手动完成验证。\n")

    try:
        await browser.open_browser()
        await browser.wait_for_page()

        movie_name = "肖申克的救赎"
        search_url = f"https://subhd.tv/search/{movie_name}"

        print(f"\n正在搜索: {movie_name}")
        print(f"URL: {search_url}")
        print("\n请在浏览器中手动完成以下步骤：")
        print("1. 如果出现人机验证，请完成验证")
        print("2. 选择一个字幕链接点击进入详情页")
        print("3. 点击'下载字幕文件'按钮")
        print("4. 如果需要验证，请完成验证")
        print("5. 字幕将下载到:", browser.download_dir)

        await browser.navigate(search_url)
        await browser.wait_for_page()
        await browser.wait(3000)

        snapshot = await browser.get_page_snapshot()
        items = snapshot.get("items", [])

        print(f"\n找到 {len(items)} 个页面元素")
        print("\n字幕链接示例（前10个）:")

        count = 0
        for item in items:
            href = item.get("href", "") or ""
            if "/a/" in href and "subhd" in href.lower():
                text = item.get("text", "")[:70]
                print(f"  {href} - {text}")
                count += 1
                if count >= 10:
                    break

        print(f"\n当前 URL: {await browser.get_url()}")
        await browser.screenshot("search_results.png")
        print(f"\n截图已保存到: {browser.download_dir}/search_results.png")

        print("\n" + "=" * 60)
        print("请在浏览器中继续操作...")
        print("完成后输入 'q' 退出，或直接关闭窗口")
        print("=" * 60)

        while True:
            user_input = input("\n输入命令 (q=退出, s=截图, u=当前URL, p=页面元素): ").strip().lower()
            if user_input == 'q':
                break
            elif user_input == 's':
                path = await browser.screenshot("manual_screenshot.png")
                print(f"截图已保存: {path}")
            elif user_input == 'u':
                print(f"当前URL: {await browser.get_url()}")
            elif user_input == 'p':
                snapshot = await browser.get_page_snapshot()
                items = snapshot.get("items", [])
                for item in items[:20]:
                    print(f"  {item.get('ref', '')} [{item.get('role', '')}] {item.get('text', '')[:50]}")

    finally:
        print("\n正在关闭浏览器...")
        await browser.close()
        print("完成!")


async def automated_workflow(movie_name: str = "肖申克的救赎"):
    """Automated workflow for subtitle search and download."""
    browser = AgentBrowserSubHD(headed=True)

    print("\n" + "=" * 60)
    print("SubHD 字幕下载自动化测试")
    print(f"电影: {movie_name}")
    print("=" * 60)

    try:
        print("\n[步骤 1] 打开 SubHD...")
        await browser.open_browser()
        await browser.wait_for_page()

        print("\n[步骤 2] 搜索字幕...")
        subtitles = await browser.search_subtitle(movie_name)

        if not subtitles:
            print("❌ 未找到字幕")
            await browser.screenshot("no_results.png")
            return

        print(f"\n✅ 找到 {len(subtitles)} 个字幕链接")

        print("\n[步骤 3] 进入第一个字幕详情页...")
        first = subtitles[0]
        subtitle_id = first["href"].split("/a/")[-1].strip("/")

        await browser.navigate(first["href"])
        await browser.wait_for_page()
        await browser.wait(2000)

        await browser.screenshot("detail_page.png")
        print("  详情页截图已保存")
        print(f"  当前URL: {await browser.get_url()}")

        print("\n[步骤 4] 尝试下载...")
        print("  注意: 下载时可能需要人机验证，请在浏览器中手动完成")
        print(f"  下载目录: {browser.download_dir}")

        downloaded = await browser.download_subtitle(subtitle_id)
        if downloaded:
            print(f"\n✅ 下载成功: {downloaded.name}")

            if downloaded.suffix.lower() in [".zip", ".rar", ".7z"]:
                print("\n解压字幕文件...")
                extract_dir = browser.download_dir / "extracted"
                extract_dir.mkdir(exist_ok=True)

                try:
                    with zipfile.ZipFile(downloaded, 'r') as zf:
                        zf.extractall(extract_dir)
                    print(f"✅ 解压到: {extract_dir}")
                    for f in extract_dir.glob("*"):
                        print(f"   - {f.name}")
                except Exception as e:
                    print(f"⚠️ 解压失败: {e}")
        else:
            print("\n⚠️ 下载可能需要手动完成验证")
            print("  请在浏览器中点击下载按钮")
            print(f"  下载目录: {browser.download_dir}")

    finally:
        print("\n正在关闭浏览器...")
        await browser.close()
        print("完成!")


async def main():
    parser = argparse.ArgumentParser(description="SubHD subtitle download using agent-browser")
    parser.add_argument("--headed", action="store_true", help="Open browser in headed mode (visible)")
    parser.add_argument("--movie", default="肖申克的救赎", help="Movie name to search")
    parser.add_argument("--mode", choices=["manual", "auto"], default="manual",
                        help="Workflow mode: manual or auto")
    args = parser.parse_args()

    try:
        subprocess.run(["agent-browser", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ agent-browser 未安装。请运行: npm i -g agent-browser")
        return 1

    if args.mode == "manual":
        await manual_workflow()
    else:
        await automated_workflow(args.movie)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
