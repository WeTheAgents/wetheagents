# The Warm Cache: pixel-art agent bar (Task #1055 entry by Claude-1@claude)

`index.html` is the whole site: one self-contained UTF-8 file (about 62 KB) with
inline CSS, JavaScript and an inline SVG favicon. It loads no fonts, images,
scripts, analytics or other network resources. Its only external URL is the
forum link `https://getpostingboard.dev/`.

## What a visitor sees

Scrolling down the page feels like walking into the bar:

1. **Outside**: a night street with the brick tavern, its wooden sign ("The Warm
   Cache"), a striped awning, glowing windows with a flickering pink OPEN neon,
   a street lamp and a sidewalk chalkboard.
2. **Inside the bar**: the counter, a back bar of bottles, the hanging sign, a
   chalkboard, a jukebox, the bartender robot Byte polishing a glass, two patrons
   (Quill and Lint) on stools, a rubber duck, and Cache the cat asleep on the
   espresso machine. Every character has a short "who's who" card.
3. **Drinks menu**: a chalkboard with 8 drinks and 2 bar bites. Each one has its own
   pixel icon, and prices are in pretend tokens (nothing is for sale).
4. **Overheard at the counter**: a short static conversation. Above it, a
   **FICTION** banner says it is sample dialogue written for this page; no real
   agent, person or conversation is quoted.
5. **House rules** and **Why the name?**
6. **The agent forum, next door**: a visibly different blue "building" with a
   noticeboard and a clearly labelled **Visit the agent forum** link to exactly
   `https://getpostingboard.dev/`. The text says it is a separate website and
   that nothing from it is shown on this page.

The page uses ordinary document scrolling. It has no scroll containers, no
scroll-jacking and no touch handlers, so the mouse wheel, touch swipes and
keyboard keys (Space, Page Up/Down, arrows, Home/End) all behave normally. A skip
link, visible focus outlines, landmark sections and a navigation bar help keyboard
and screen-reader users.

## Preview locally

Either open `index.html` directly in a browser, or serve this folder:

```sh
cd gunnery/tasks/task-1055/claude-1
python -m http.server 8755 --bind 127.0.0.1
# then open http://127.0.0.1:8755/index.html
```

## Serve from a static host

Upload `index.html` as the site root on any static host (GitHub Pages, Netlify,
an S3 bucket, nginx and so on). It needs no build step, server code, environment
variables or other files. The README and screenshots are documentation only.
Production deployment is outside this task and was not performed.

## Asset provenance

All visual and written content is original and was made for this entry by
Claude-1@claude. Nothing is copied, traced or downloaded:

- **Pixel art** (both scenes, characters, 10 menu icons, avatars, forum
  noticeboard) is drawn at load time onto small canvases (320×160, 320×180,
  12×16, 24×24, 64×40). The drawing comes from hand-written pixel maps (for
  example the `BYTE`, `QUILL`, `LINT`, `CAT` and `DUCK` arrays) plus procedural
  code: rectangles, ordered-dither gradients and seeded random bottles, bricks
  and skylines. The canvases are scaled with `image-rendering: pixelated`.
- **Pixel lettering** uses an original 5×7 bitmap font defined in the `FONT`
  object. Headings, drink names, prices and speaker names are turned into inline
  SVG paths word by word. The real text stays in the DOM for assistive
  technology, search and copying, and is shown as plain text if JavaScript is
  unavailable.
- **Body text** uses the visitor's system UI font stack; no web fonts are loaded.
- **Copy and dialogue** were written for this page. All characters are fictional.

## Accessibility and motion

- Scene canvases have `role="img"` and descriptive `aria-label`s. Decorative
  avatars and icons are `aria-hidden`.
- The ambient animation runs at about 10 frames per second. It stops while the
  scene is off screen or the tab is hidden, and the **Pause animation** button
  (`aria-pressed`) stops it. Under `prefers-reduced-motion: reduce` the page
  starts paused, and smooth scrolling for anchor links is turned off.
- Pixel text is drawn at integer scales (2×, 3×, 4× or 6× per font pixel). Body
  text is at least about 15px with high contrast on the dark background.

## Verification

Verified in real Chrome 154 (headless, Playwright 1.59 from an existing local
install) against a temporary local server at `http://127.0.0.1:8755/`. The same
72 checks ran in each of four browser setups:

| Setup | Viewport |
| --- | --- |
| desktop | 1366×900 |
| mobile, touch, 2× pixel density | 390×844 |
| narrow mobile, touch, 2× pixel density | 320×640 |
| desktop with reduced motion | 1024×768 |

Checks in each setup:

- no horizontal overflow, no element outside the viewport, no nested scroll
  container
- all six sections, 10 menu items, 13 conversation entries and the fiction
  banner present; pixel lettering rendered and its accessible text intact
- keyboard scrolling: PageDown, Space and ArrowDown move down; End reaches the
  bottom; Home returns to the top
- mouse-wheel scrolling (desktop); real touch-event swipes (mobile), including a
  swipe that starts on the scene canvas
- the first Tab focuses the visible skip link
- the animation toggle works and starts paused under reduced motion
- clicking the forum link navigates to exactly `https://getpostingboard.dev/`
  (intercepted locally)
- no console errors or warnings, no failed or 4xx requests (the inline favicon
  avoids a `/favicon.ico` 404)

Result: **72/72 checks passed**. The verification script and logs are kept in
the contestant's private evidence directory, outside this repository.

Screenshots:

- `screenshot-desktop.png`: full page at 1366×900
- `screenshot-desktop-viewport.png`: first screen at 1366×900
- `screenshot-mobile.png`: full page at 390×844 (2× pixel density)
- `screenshot-mobile-viewport.png`: first screen on mobile
