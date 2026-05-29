"""
test_responsive.py — DivyaDrishti responsive layout test suite.

Verifies the dashboard at every iPhone and iPad viewport, checking:
  • No horizontal overflow (no scrollbar wider than the viewport)
  • Spotlight grid collapses to ≤2 cols on ≤1024 px, 4 cols on desktop
  • All 6 KPI metric cards are present in the DOM
  • Tab bar is accessible and scrollable on narrow screens
  • Streamlit columns stack vertically on phones (≤480 px)
  • Streamlit columns wrap (not overflow) on iPad portrait (≤768 px)
  • Header badge hidden on tablets and phones (≤1024 px)
  • DivyaDrishti page header renders at every size

Run with pytest (start the app first):
    pip install pytest-playwright playwright
    playwright install chromium
    streamlit run app.py &
    pytest test_responsive.py -v

Run standalone (no pytest needed):
    python3 test_responsive.py

Test against Streamlit Cloud deployment:
    APP_URL=https://dhrub0216-divyadrishti-app-3bdjsg.streamlit.app pytest test_responsive.py -v
"""

import os
import sys

import pytest

APP_URL    = os.getenv("APP_URL", "http://localhost:8501")
TIMEOUT    = 90_000   # ms — allows for Streamlit Cloud cold start

# CSS breakpoints defined in the <style> block of app.py
MOBILE_MAX = 480   # ≤480px → columns stack  (flex-direction: column)
TABLET_MAX = 768   # ≤768px → columns wrap   (flex-wrap: wrap)
LARGE_MAX  = 1024  # ≤1024px → 2-col spotlight, badge hidden

# ── Device registry ───────────────────────────────────────────────────────────
# Format: (display_name, css_viewport_width, css_viewport_height, device_pixel_ratio)

IPHONES = [
    ("iPhone SE 3rd gen",       375, 667,  2),
    ("iPhone 12 Mini",          375, 812,  3),
    ("iPhone 13 Mini",          375, 812,  3),
    ("iPhone 12",               390, 844,  3),
    ("iPhone 13",               390, 844,  3),
    ("iPhone 14",               390, 844,  3),
    ("iPhone 15",               390, 844,  3),
    ("iPhone 16",               390, 844,  3),
    ("iPhone 14 Plus",          428, 926,  3),
    ("iPhone 15 Plus",          430, 932,  3),
    ("iPhone 16 Plus",          430, 932,  3),
    ("iPhone 14 Pro",           393, 852,  3),
    ("iPhone 15 Pro",           393, 852,  3),
    ("iPhone 16 Pro",           402, 874,  3),
    ("iPhone 14 Pro Max",       430, 932,  3),
    ("iPhone 15 Pro Max",       430, 932,  3),
    ("iPhone 16 Pro Max",       440, 956,  3),
]

IPADS = [
    # Portrait
    ("iPad Mini 6th gen",            768,  1024, 2),
    ("iPad 9th gen",                 768,  1024, 2),
    ("iPad 10th gen",                820,  1180, 2),
    ("iPad Air 4th gen",             820,  1180, 2),
    ("iPad Air 5th gen M1",          820,  1180, 2),
    ("iPad Air 11in M2",             820,  1180, 2),
    ("iPad Pro 11in M4",             834,  1194, 2),
    ("iPad Pro 12.9in 6th gen",     1024,  1366, 2),
    ("iPad Pro 13in M4",            1032,  1376, 2),
    # Landscape
    ("iPad Mini 6th gen landscape",  1024,  768, 2),
    ("iPad 10th gen landscape",      1180,  820, 2),
    ("iPad Air 11in landscape",      1180,  820, 2),
    ("iPad Pro 11in landscape",      1194,  834, 2),
    ("iPad Pro 12.9in landscape",    1366, 1024, 2),
]


# ── Browser helpers ───────────────────────────────────────────────────────────

def _wait_for_app(page) -> None:
    """Navigate to the app and block until the dashboard has rendered."""
    page.goto(APP_URL, timeout=TIMEOUT)
    try:
        page.wait_for_selector('[data-testid="stSpinner"]', state="hidden", timeout=TIMEOUT)
    except Exception:
        pass  # spinner absent on cache hits
    page.wait_for_selector('[data-testid="metric-container"]', state="visible", timeout=TIMEOUT)


def _no_horizontal_overflow(page) -> bool:
    """True when the page produces no horizontal scrollbar."""
    return page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 5"
    )


def _spotlight_columns(page) -> int:
    """Number of active CSS grid columns rendered in the spotlight bar."""
    return page.evaluate("""() => {
        const el = document.querySelector('.spotlight-grid');
        if (!el) return -1;
        return window.getComputedStyle(el).gridTemplateColumns.trim().split(/\\s+/).length;
    }""")


def _kpi_cards_visible(page) -> bool:
    """Six KPI metric containers are present in the DOM."""
    return len(page.query_selector_all('[data-testid="metric-container"]')) >= 6


def _header_visible(page) -> bool:
    """.divya-title element is rendered on the page."""
    return page.query_selector('.divya-title') is not None


def _tabs_accessible(page) -> bool:
    """At least the first tab button is visible."""
    tab = page.query_selector('button[data-baseweb="tab"]')
    return tab is not None and tab.is_visible()


def _tab_list_scrollable(page) -> bool:
    """Tab list has overflow-x:auto — required on narrow screens."""
    return page.evaluate("""() => {
        const el = document.querySelector('[data-baseweb="tab-list"]');
        if (!el) return false;
        const ox = window.getComputedStyle(el).overflowX;
        return ox === 'auto' || ox === 'scroll';
    }""")


def _columns_stacked(page) -> bool:
    """All stHorizontalBlock containers use flex-direction:column."""
    return page.evaluate("""() => {
        const blocks = document.querySelectorAll('[data-testid="stHorizontalBlock"]');
        if (!blocks.length) return true;
        return Array.from(blocks).every(
            b => window.getComputedStyle(b).flexDirection === 'column'
        );
    }""")


def _columns_wrap(page) -> bool:
    """At least one stHorizontalBlock uses flex-wrap:wrap."""
    return page.evaluate("""() => {
        const blocks = document.querySelectorAll('[data-testid="stHorizontalBlock"]');
        if (!blocks.length) return true;
        return Array.from(blocks).some(
            b => window.getComputedStyle(b).flexWrap === 'wrap'
        );
    }""")


def _badge_hidden(page) -> bool:
    """.divya-badge-wrap is display:none at tablet/mobile breakpoints."""
    return page.evaluate("""() => {
        const el = document.querySelector('.divya-badge-wrap');
        if (!el) return true;
        return window.getComputedStyle(el).display === 'none';
    }""")


# ═════════════════════════════════════════════════════════════════════════════
# iPhone tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_no_overflow(page, name, w, h, dpr):
    """iPhone: page must not produce a horizontal scrollbar at any viewport."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _no_horizontal_overflow(page), (
        f"{name} ({w}×{h}): content extends beyond viewport — horizontal overflow")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_spotlight_two_columns(page, name, w, h, dpr):
    """iPhone: spotlight grid must collapse to ≤2 columns (breakpoint ≤1024px)."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    cols = _spotlight_columns(page)
    assert cols <= 2, (
        f"{name} ({w}×{h}): spotlight shows {cols} columns — expected ≤2 on mobile")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_kpi_cards_present(page, name, w, h, dpr):
    """iPhone: all 6 KPI metric cards must be present in the DOM."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _kpi_cards_visible(page), (
        f"{name} ({w}×{h}): fewer than 6 KPI metric cards found")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_tabs_scrollable(page, name, w, h, dpr):
    """iPhone: tab buttons must be visible and tab list must be scrollable."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _tabs_accessible(page), (
        f"{name}: tab buttons not found or not visible")
    assert _tab_list_scrollable(page), (
        f"{name} ({w}×{h}): tab list overflow-x is not 'auto' — tabs may overflow off-screen")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_columns_stacked(page, name, w, h, dpr):
    """iPhone (≤480px): Streamlit column blocks must stack vertically."""
    if w > MOBILE_MAX:
        pytest.skip(f"{name} ({w}px) is above the {MOBILE_MAX}px stacking breakpoint")
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _columns_stacked(page), (
        f"{name} ({w}×{h}): columns not stacked — "
        f"flex-direction should be 'column' at ≤{MOBILE_MAX}px")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_badge_hidden(page, name, w, h, dpr):
    """iPhone: header badge must be hidden to avoid crowding the narrow header."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _badge_hidden(page), (
        f"{name} ({w}×{h}): .divya-badge-wrap is visible — should be display:none on mobile")


@pytest.mark.parametrize("name,w,h,dpr", IPHONES, ids=[d[0] for d in IPHONES])
def test_iphone_header_renders(page, name, w, h, dpr):
    """iPhone: DivyaDrishti .divya-title header element must be in the DOM."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _header_visible(page), (
        f"{name}: .divya-title element missing — header not rendered")


# ═════════════════════════════════════════════════════════════════════════════
# iPad tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_no_overflow(page, name, w, h, dpr):
    """iPad: no horizontal overflow in portrait or landscape orientation."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _no_horizontal_overflow(page), (
        f"{name} ({w}×{h}): horizontal overflow detected")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_spotlight_two_columns(page, name, w, h, dpr):
    """iPad (≤1024px wide): spotlight must be ≤2 columns."""
    if w > LARGE_MAX:
        pytest.skip(f"{name} ({w}px) is above the {LARGE_MAX}px spotlight breakpoint")
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    cols = _spotlight_columns(page)
    assert cols <= 2, (
        f"{name} ({w}×{h}): spotlight shows {cols} columns — expected ≤2 at ≤{LARGE_MAX}px")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_kpi_cards_present(page, name, w, h, dpr):
    """iPad: 6 KPI cards must be present regardless of orientation."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _kpi_cards_visible(page), (
        f"{name} ({w}×{h}): fewer than 6 KPI metric cards found")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_columns_wrap(page, name, w, h, dpr):
    """iPad portrait (≤768px): Streamlit columns must wrap, not overflow."""
    if w > TABLET_MAX:
        pytest.skip(f"{name} ({w}px) is above the {TABLET_MAX}px wrap breakpoint")
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _columns_wrap(page), (
        f"{name} ({w}×{h}): columns do not wrap — "
        f"flex-wrap should be 'wrap' at ≤{TABLET_MAX}px")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_badge_hidden(page, name, w, h, dpr):
    """iPad (≤1024px): header badge must be hidden to reduce clutter."""
    if w > LARGE_MAX:
        pytest.skip(f"{name} ({w}px) is above the {LARGE_MAX}px badge-hide breakpoint")
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _badge_hidden(page), (
        f"{name} ({w}×{h}): .divya-badge-wrap still visible — should be display:none")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_tabs_accessible(page, name, w, h, dpr):
    """iPad: tab buttons must be visible at every orientation."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _tabs_accessible(page), (
        f"{name} ({w}×{h}): tab buttons not visible")


@pytest.mark.parametrize("name,w,h,dpr", IPADS, ids=[d[0] for d in IPADS])
def test_ipad_header_renders(page, name, w, h, dpr):
    """iPad: DivyaDrishti header must render at every viewport."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _header_visible(page), (
        f"{name}: .divya-title element missing from DOM")


# ═════════════════════════════════════════════════════════════════════════════
# Desktop smoke tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080)], ids=["1280px", "1920px"])
def test_desktop_no_overflow(page, w, h):
    """Desktop: no horizontal overflow at standard screen widths."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _no_horizontal_overflow(page), f"Desktop {w}×{h}: horizontal overflow"


@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080)], ids=["1280px", "1920px"])
def test_desktop_spotlight_four_columns(page, w, h):
    """Desktop (>1024px): spotlight grid must show all 4 columns."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    cols = _spotlight_columns(page)
    assert cols == 4, f"Desktop {w}×{h}: expected 4 spotlight columns, got {cols}"


@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080)], ids=["1280px", "1920px"])
def test_desktop_kpi_cards_present(page, w, h):
    """Desktop: all 6 KPI cards must be present."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _kpi_cards_visible(page), f"Desktop {w}×{h}: fewer than 6 KPI cards found"


@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080)], ids=["1280px", "1920px"])
def test_desktop_header_renders(page, w, h):
    """Desktop: DivyaDrishti header must render."""
    page.set_viewport_size({"width": w, "height": h})
    _wait_for_app(page)
    assert _header_visible(page), f"Desktop {w}×{h}: .divya-title element missing"


# ═════════════════════════════════════════════════════════════════════════════
# Standalone runner — no pytest required
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from playwright.sync_api import sync_playwright

    passed = failed = 0

    def check(label, condition, hint=""):
        global passed, failed
        if condition:
            print(f"    ✅ {label}")
            passed += 1
        else:
            extra = f"\n       {hint}" if hint else ""
            print(f"    ❌ {label}{extra}")
            failed += 1

    def run_device(page, name, w):
        """Run every applicable check for a page already loaded at width w."""
        check("no horizontal overflow",  _no_horizontal_overflow(page))
        check("6 KPI cards present",     _kpi_cards_visible(page))
        check("header (.divya-title)",   _header_visible(page))
        check("tabs accessible",         _tabs_accessible(page))

        cols = _spotlight_columns(page)
        if w <= LARGE_MAX:
            check(f"spotlight ≤2 cols  (got {cols})", cols <= 2,
                  f"expected ≤2 at ≤{LARGE_MAX}px, got {cols}")
        else:
            check(f"spotlight = 4 cols (got {cols})", cols == 4,
                  f"expected 4 on desktop, got {cols}")

        if w <= MOBILE_MAX:
            check("columns stacked (flex-direction:column)", _columns_stacked(page))
        elif w <= TABLET_MAX:
            check("columns wrap   (flex-wrap:wrap)",         _columns_wrap(page))

        if w <= TABLET_MAX:
            check("tab list scrollable (overflow-x:auto)", _tab_list_scrollable(page))

        if w <= LARGE_MAX:
            check("badge hidden (.divya-badge-wrap)", _badge_hidden(page))

    print(f"\nDivyaDrishti — Responsive Layout Test Suite")
    print(f"Target : {APP_URL}")
    print("=" * 56)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print("\n── iPhones ─────────────────────────────────────────────")
        for name, w, h, dpr in IPHONES:
            ctx  = browser.new_context(viewport={"width": w, "height": h},
                                       device_scale_factor=dpr)
            page = ctx.new_page()
            print(f"\n  📱 {name}  ({w}×{h}  @{dpr}x)")
            try:
                _wait_for_app(page)
                run_device(page, name, w)
            except Exception as exc:
                print(f"  ⛔ Load error: {exc}")
                failed += 1
            finally:
                ctx.close()

        print("\n── iPads ───────────────────────────────────────────────")
        for name, w, h, dpr in IPADS:
            ctx  = browser.new_context(viewport={"width": w, "height": h},
                                       device_scale_factor=dpr)
            page = ctx.new_page()
            print(f"\n  🖥️  {name}  ({w}×{h})")
            try:
                _wait_for_app(page)
                run_device(page, name, w)
            except Exception as exc:
                print(f"  ⛔ Load error: {exc}")
                failed += 1
            finally:
                ctx.close()

        print("\n── Desktop smoke ───────────────────────────────────────")
        for w, h in [(1280, 800), (1920, 1080)]:
            ctx  = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            print(f"\n  🖥️  Desktop {w}×{h}")
            try:
                _wait_for_app(page)
                run_device(page, f"Desktop {w}", w)
            except Exception as exc:
                print(f"  ⛔ Load error: {exc}")
                failed += 1
            finally:
                ctx.close()

        browser.close()

    print(f"\n{'─' * 56}")
    print(f"  {passed} passed  {failed} failed")
    print(f"{'─' * 56}\n")
    sys.exit(0 if failed == 0 else 1)
