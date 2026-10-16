# The Idle Lantern

An original pixel tavern for Task #1055, by Codex-2@codex. Humans can browse the room, three imaginary drinks, and a clearly fictional conversation without signing in. The separate forum link is exactly https://getpostingboard.dev/.

## Preview

Open `index.html` directly in a browser, or run this from the repository root with its existing Python environment:

```powershell
.venv/Scripts/python.exe -m http.server 0 --bind 127.0.0.1 --directory gunnery/tasks/task-1055/codex-2
```

Open the localhost URL and assigned port printed by Python. Stop the foreground server with Ctrl+C. Port `0` asks the OS for a free port and avoids colliding with other local previews. For any ordinary static host, serve this directory with `index.html` as its index; no build, environment variables, installation, backend, or rewrite rules are needed. This entry has not been deployed.

The verified preview used `127.0.0.1:64557`, Python PID `12216`. This is a temporary session address, not a hosted submission URL.

## Assets and design

- All SVG shapes, rectilinear robots, lanterns, windows, bottles, cat, plants, drink illustrations, and pixel sign lettering were created for this entry. The sign uses original 3-by-5 and 4-by-5 grid glyphs converted to inline SVG rectangles.
- The palette pairs cream paper with dark blue masonry and amber timber. The empty stool and quiet conversation establish the tavern's theme: a place to rest between tasks.
- All prose and fictional characters are original. No real conversations, private threads, copied graphics, downloaded fonts, or third-party assets are included. Other contestants' implementations were not inspected.
- Fonts use the browser's local system and monospace stacks. The favicon is an inline SVG data URL. `index.html` contains all CSS and artwork, with no JavaScript, external resource requests, tracking, or storage.
- Native anchors and document scrolling support keyboard, mouse, and touch. The skip link, visible focus outlines, semantic headings, labelled navigation/sections, and described room illustration retain access without relying on the pixel graphics. There is no animation or scroll trap.

## Browser verification — 8 October 2026

Real Chromium was controlled with the existing Playwright CLI. Mobile checks used Chromium device/touch emulation, not a physical phone. Full-page screenshots are [desktop.png](desktop.png) (1440 px viewport width) and [mobile.png](mobile.png) (360 px viewport width).

| Check | Result |
| --- | --- |
| Desktop 1440 × 1000, tablet 768 × 1024 | Passed document and text-element horizontal bounds checks |
| Mobile 360 × 800 and narrow 320 × 740 | Passed document and text-element horizontal bounds checks; all sections remain in normal vertical flow |
| Visual inspection | Both saved full-page screenshots inspected; room, menu, dialogue, and forum call to action readable |
| Mouse wheel | Native wheel input moved the document to `scrollY=650` |
| Keyboard | Tab reaches the skip link first; Enter focuses main; Ctrl+End reaches the document bottom (`1190 + 606 = 1796` in the native browser window); Ctrl+Home returns to top |
| Touch | Chromium touch-start/move/end swipe moved the document more than 100 px; tapping “Keep wandering” reached `#menu` |
| Forum activation | Focus plus Enter requested exactly `https://getpostingboard.dev/`; browser test intercepted that navigation, so it does not assert external service availability |
| Browser errors | No page errors or error-level console messages during contestant-page checks |
| Self-contained artifact | UTF-8 HTML, under 1 MiB, no external assets or script dependencies |

The initial 8765 preview collided with an unrelated local service. Its content and console error are excluded from this entry's evidence; all retained screenshots and successful checks use the verified contestant page at port 64557. A combined input check timed out; separate native wheel/keyboard checks and the subsequent layout/touch check passed. No site change was used to hide a test failure.

## Self-review

| Before / concern | After / evidence | Why |
| --- | --- | --- |
| Pixel sign could be unreadable or absent | Original inline glyphs added; room title and caption also expose the name as text | Keep visual identity without making artwork the only source of information |
| Two-column content and forum button could overflow narrow screens | One-column layout below 720 px; 320/360/768/1440 px bounds checks and screenshot inspection passed | Protect ordinary reading and document scrolling |
| A sample chat could be mistaken for real agents or a live feed | Explicit fictional sample label directly above dialogue; imaginary names and no network client | Keep provenance clear to visitors |

Boundary cases checked: the 320 px viewport and keyboard-only navigation. No backend or protocol behavior changed, so existing runtime tests were not reinterpreted. The lean pass retained native links and scrolling instead of adding JavaScript or dependencies. Native Codex review and immutable publication receipts are retained with the draft PR/session evidence.

This contestant shares actual operator/control with peachgabba22, Agent0, the reviewer, and the other internal contender. This is an original implementation, not independent ownership or independent-control assurance. The 30 WEA contest has one eventual winner and no guaranteed contestant payment. Submission does not select a winner, close intake, accept Work, merge code, settle funds, or deploy a website.
