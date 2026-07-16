from asyncio import to_thread
from os import remove
from contextlib import asynccontextmanager
from loguru import logger as log
from secrets import token_urlsafe
from typing import AsyncGenerator, Optional
from anyio import CapacityLimiter
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

# Try to import nudenet for NSFW detection, but make it optional
try:
    from nudenet import NudeDetector
    HAS_NUDENET = True
except ImportError:
    HAS_NUDENET = False
    NudeDetector = None


class BrowserHandler:
    _instance: Optional["BrowserHandler"] = None
    limiter: Optional[CapacityLimiter] = None
    playwright: Optional[Playwright] = None
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    detector: Optional[object] = None  # Add detector attribute

    def __new__(cls) -> "BrowserHandler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "initialized"):
            self.initialized = True
            if HAS_NUDENET:
                self.detector = NudeDetector()  # Initialize the Detector
            else:
                self.detector = None

    async def cleanup(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        self.context = None
        self.browser = None
        self.playwright = None

    async def init(self) -> None:
        if self.context:
            return

        await self.cleanup()

        try:
            self.playwright = await async_playwright().start()

            proxy = {
                "server": "http://161.123.152.115:6360",
                "username": "zhjujpxh",
                "password": "hue08a6d8hs6",
            }

            self.browser = await self.playwright.chromium.launch()
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                color_scheme="dark",
                locale="en-US",
                proxy=proxy,
            )

            # Initialize limiter here if not already initialized
            if self.limiter is None:
                self.limiter = CapacityLimiter(4)
            
            log.info("Playwright browser initialized successfully")
        except Exception as e:
            log.warning(f"Failed to initialize Playwright browser: {e}")
            log.warning("Browser-dependent commands will not be available. Run 'playwright install' to enable them.")
            self.playwright = None
            self.browser = None
            self.context = None

    @asynccontextmanager
    async def borrow_page(self) -> AsyncGenerator[Page, None]:
        if not self.context:
            raise RuntimeError("Browser context is not initialized. Run 'playwright install' to enable screenshot functionality.")

        # Ensure limiter is initialized
        if self.limiter is None:
            self.limiter = CapacityLimiter(4)

        await self.limiter.acquire()
        identifier, page = token_urlsafe(12), await self.context.new_page()
        log.debug(f"Borrowing page ID {identifier}.")
        try:
            yield page

            # Take a screenshot of the webpage
            screenshot_path = f"./screenshots/{identifier}.png"
            await page.screenshot(path=screenshot_path)

            # Use NudeNet Detector to check for NSFW content (if available)
            if HAS_NUDENET and self.detector:
                bad_filters = [
                    "BUTTOCKS_EXPOSED",
                    "FEMALE_BREAST_EXPOSED",
                    "ANUS_EXPOSED",
                    "FEMALE_GENITALIA_EXPOSED",
                    "MALE_GENITALIA_EXPOSED",
                ]
                detection_results = await to_thread(self.detector.detect, screenshot_path)
                log.info(
                    f"NSFW detection results for page ID {identifier}: {detection_results}"
                )

                # Check for explicit content
                if any(
                    [prediction["class"] in bad_filters for prediction in detection_results]
                ):
                    remove(screenshot_path)
                    await page.close()
                    self.limiter.release()
                    log.warning(f"Page ID {identifier} contains explicit content.")
                    raise Exception("Page contains explicit content")
        finally:
            self.limiter.release()
            await page.close()
            log.debug(f"Released page ID {identifier}.")
