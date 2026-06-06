import asyncio
from playwright.async_api import async_playwright

APP_URL = "https://dhrub0216-divyadrishti-app-3bdjsg.streamlit.app"

async def wake():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        print(f"Loading {APP_URL} ...")

        await page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)

        # If Streamlit shows the sleep screen, click wake up
        try:
            wake_btn = page.get_by_role("button", name="Yes, get this app back up!")
            await wake_btn.wait_for(timeout=8_000)
            print("App was sleeping — clicking wake up...")
            await wake_btn.click()
            await page.wait_for_timeout(60_000)
        except Exception:
            print("No sleep screen — app already awake.")

        # Wait for Streamlit WebSocket (this is what resets the 7-day timer)
        try:
            await page.wait_for_selector(
                "[data-testid='stAppViewContainer']", timeout=90_000
            )
            print("App fully loaded. Sleep timer reset.")
        except Exception:
            print("App opened — session still counts as a visit.")

        await page.wait_for_timeout(8_000)
        await browser.close()

asyncio.run(wake())
