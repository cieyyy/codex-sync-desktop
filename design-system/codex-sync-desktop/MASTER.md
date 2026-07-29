# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Codex Sync Desktop
**Generated:** 2026-07-28 18:38:53
**Category:** Financial Dashboard
**Design Dials:** Variance 4/10 (Balanced / Modern) | Motion 3/10 (Subtle) | Density 8/10 (Dense / Dashboard)

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#38BDF8` | `--color-primary` |
| On Primary | `#050816` | `--color-on-primary` |
| Secondary | `#1D4ED8` | `--color-secondary` |
| Accent/CTA | `#67E8F9` | `--color-accent` |
| Background | `#050816` | `--color-background` |
| Foreground | `#F8FAFC` | `--color-foreground` |
| Muted | `#101A38` | `--color-muted` |
| Border | `#1D2B53` | `--color-border` |
| Destructive | `#F43F5E` | `--color-destructive` |
| Ring | `#67E8F9` | `--color-ring` |

**Color Notes:** Deep navy operations console with high-contrast electric cyan primary actions, royal blue secondary actions, cyan focus, and no gray normal buttons. Green is reserved for success feedback only.

### Desktop Window Chrome

- Windows uses a borderless custom title bar integrated into the deep navy shell.
- Window controls use consistent 1.5-2px vector strokes and preserve keyboard focus.
- The product mark is two device nodes connected by cyan synchronization paths.
- Command-line work runs without a visible terminal; browsers and operating-system authorization surfaces remain visible.

### Typography

- **Heading Font:** Orbitron
- **Body Font:** JetBrains Mono
- **Mood:** cyberpunk, neon, glitch, hud, sci-fi, dark, matrix green, magenta, chamfered, tactical
- **Google Fonts:** [Orbitron + JetBrains Mono](https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Orbitron:wght@700;900&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Orbitron:wght@700;900&display=swap');
```

### Spacing Variables

*Density: 8/10 — Dense / Dashboard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `2px` / `0.125rem` | Tight gaps |
| `--space-sm` | `4px` / `0.25rem` | Icon gaps, inline spacing |
| `--space-md` | `8px` / `0.5rem` | Standard padding |
| `--space-lg` | `12px` / `0.75rem` | Section padding |
| `--space-xl` | `16px` / `1rem` | Large gaps |
| `--space-2xl` | `24px` / `1.5rem` | Section margins |
| `--space-3xl` | `32px` / `2rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #38BDF8;
  color: #050816;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  background: #1D4ED8;
  color: #F8FAFC;
  border: 1px solid #2563EB;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #0B1228;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  color: #F8FAFC;
  background: #101A38;
  border: 1px solid #1D2B53;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #67E8F9;
  outline: none;
  box-shadow: 0 0 0 3px #67E8F930;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: #0B1228;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Dark Mode (OLED)

**Keywords:** Dark theme, low light, high contrast, deep black, midnight blue, eye-friendly, OLED, night mode, power efficient

**Best For:** Night-mode apps, coding platforms, entertainment, eye-strain prevention, OLED devices, low-light

**Key Effects:** Minimal glow (text-shadow: 0 0 10px), dark-to-light transitions, low white emission, high readability, visible focus

### Page Pattern

**Pattern Name:** Real-Time / Operations Landing

- **Conversion Strategy:** For ops/security/iot products. Demo or sandbox link. Trust signals.
- **CTA Placement:** Primary CTA in nav + After metrics
- **Section Order:** 1. Hero (product + live preview or status), 2. Key metrics/indicators, 3. How it works, 4. CTA (Start trial / Contact)

---

## Motion

**Scroll Reveal** (Subtle) — Trigger: scroll (viewport enter) | Duration: 300-400ms | Easing: `power1.out`

```js
gsap.from(el, { opacity: 0, y: 12, duration: 0.35, ease: 'power1.out', scrollTrigger: { trigger: el, start: 'top 90%', toggleActions: 'play none none reverse' } });
```

**Framework notes:** Requires the ScrollTrigger plugin registered once via gsap.registerPlugin(ScrollTrigger)

- ✅ Keep the y offset small (8-16px) so it reads as a fade, not a slide
- ❌ Don't reveal below-the-fold content needed for SEO/crawlers as invisible-by-default without a no-JS fallback
- ⚡ toggleActions 'play none none reverse' avoids re-triggering on every scroll direction change

---

## Anti-Patterns (Do NOT Use)

- ❌ Light mode default
- ❌ Slow rendering

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile

---

## Desktop Window Chrome v0.6.9

- The outer application frame always uses the deep navy border token; window focus must not switch it to cyan.
- Mouse-selected navigation relies on the active-page fill and must not retain a dotted focus rectangle.
- Keyboard navigation keeps a visible focus state so removing mouse focus does not remove accessibility.
- Windows taskbar, Alt+Tab, executable, installer, and shortcuts use the same generated product icon.
- The Windows process sets a stable AppUserModelID before Tk creates the native window.

## Import Preview v0.7.0

- The action summary uses five stable categories: copy, identical, automatic merge, failure, and title update.
- Clicking a populated action opens a centered modal with a master-detail layout: session list on the left, metadata and bounded text preview on the right.
- Conflict previews expose source, local, and merged versions without allowing raw JSONL edits.
- The final title is the only editable field. Validation happens on blur, invalid titles show an inline recovery message, and valid changes remain pending until import.
- The modal preserves keyboard escape, Enter navigation, and Ctrl+S while keeping visible focus and high-contrast dark surfaces.

## Windows Taskbar v0.7.1

- Keep the dark borderless application chrome while registering its native Tk wrapper as a normal Windows application window.
- Apply the stable AppUserModelID, packaged icon, native title, `WS_EX_APPWINDOW`, and ownerless state after every map or restore event.
- Force a native frame refresh after changing extended styles so taskbar and Alt+Tab state update immediately.
- Packaged Windows builds must pass a taskbar-registration smoke test before an installer can be released.

## Full Import Preview

- Never truncate a selected conversation preview; every renderable record must remain reachable by scrolling.
- Load only the currently selected source, local, or merged version instead of eagerly rendering all versions.
- Append records in bounded idle-time batches and show loading/completion feedback beside the preview heading.
- Cancel the previous iterator immediately when the user switches sessions, versions, or closes the dialog.

## First-run Reliability

- Installation success is shown only after the downloaded executable exists and passes a real `--version` launch check.
- Managed portable tools must display their verified path and explain that they do not appear in the Windows installed-apps list.
- Browser authentication runs in the background with visible progress; completion is shown only after `gh auth status` passes.
- A device with zero local sessions and no `session_index.jsonl` is a normal empty state, not a failure.
- First pull automatically establishes the current branch's upstream when the remote branch exists.
