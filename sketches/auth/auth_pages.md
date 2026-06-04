# Auth Pages — Sign In / Sign Up

Visual identity and implementation reference for the standalone authentication screens.

| File | Purpose |
| --- | --- |
| `svg_single/login.svg` | Sign-in page mockup |
| `svg_single/signup.svg` | Sign-up page mockup |
| `svg_single/curio_logo_white.png` | White wordmark used on the dark brand panel |
| `svg_single/curio_logo.png` | Dark wordmark (for light surfaces on other pages) |

---

## 1. Canvas & Layout

Both pages share the same standalone, two-panel frame.

| Property | Value |
| --- | --- |
| `viewBox` | `0 0 1670 660` |
| Page background | `#FFFFFF` |
| Brand panel (left) | `x=0, y=0, width=700, height=660`, fill `#0F0F11` |
| Form panel (right) | `x=700, y=0, width=970, height=660`, fill `#FFFFFF` |
| Form content column | Left edge `x=975`, width `420` (right edge `x=1395`) |
| Form vertical anchor | Title baseline at `y≈128–150` |

The 700/970 split gives the brand block ~42% of the width and the form ~58%, with the form vertically centered around the canvas midline (`y=330`).

### Brand panel anatomy

| Element | Position | Notes |
| --- | --- | --- |
| `BrandPanel_Bg` | full left panel | `#0F0F11` flat fill |
| `BrandPanel_Logo` | centered in upper third | `curio_logo_white.png`, referenced via relative path |
| `BrandPanel_Tagline` | below the logo | "Visual workflows for urban data", `font-size="17"`, `fill="#D8D8D8"`, `letter-spacing="1"` |

---

## 2. Color Palette

A tight, utilitarian palette. Black is the primary brand color; grays provide the type hierarchy; brand blue/red/yellow/green only appear inside the Google logo glyph.

### Neutrals

| Token | Hex | Role |
| --- | --- | --- |
| `--ink-900` | `#0F0F11` | Brand black. Brand panel, primary button, primary text, divider strokes in Google/Guest icons |
| `--ink-700` | `#434548` | Subtitle and secondary text ("Sign in to your Curio account", "Don't have an account?") |
| `--ink-500` | `#747474` | Field borders (`1.5px`), "OR" divider label, tertiary text |
| `--ink-400` | `#7F7F7F` | Input placeholder text |
| `--ink-200` | `#D8D8D8` | Tagline on black panel, "OR" divider rule on white panel |
| `--surface-0` | `#FFFFFF` / `white` | Form panel background, input fill, button label on dark button |

### Google brand marks (only inside the Google G icon)

| Hex | Role |
| --- | --- |
| `#4285F4` | Google blue segment |
| `#34A853` | Google green segment |
| `#FBBC04` | Google yellow segment |
| `#EA4335` | Google red segment |

These values are fixed by Google's branding guidelines and are the only departures from the neutral palette — reserve them for the Google-sign-in glyph only.

---

## 3. Typography

| Property | Value |
| --- | --- |
| Font stack | `-apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif` |
| Root declaration | Set on the `<svg>` element, inherited by all `<text>` descendants |

### Type scale (login)

| Role | Size | Weight | Color |
| --- | --- | --- | --- |
| Page title ("Welcome back") | `28` | `700` | `#0F0F11` |
| Page subtitle | `14` | `400` | `#434548` |
| Field label | `12` | `600` | `#0F0F11` |
| Input placeholder | `13` | `400` | `#7F7F7F` |
| Password mask | `15` | `400` | `#7F7F7F`, `letter-spacing="2"` |
| Button label | `14` | `600` | `white` on black, `#0F0F11` on white |
| "OR" divider | `11` | `400` | `#747474`, `letter-spacing="2"` |
| Footer link ("Create one") | `13` | `400` body / `600` link | `#434548` / `#0F0F11` underlined |
| Tagline (brand panel) | `17` | `400` | `#D8D8D8`, `letter-spacing="1"` |

### Type scale (signup)

Slightly tighter to accommodate the extra fields (Name, Email, Password, Confirm password).

| Role | Size | Weight | Color |
| --- | --- | --- | --- |
| Page title ("Create account") | `26` | `700` | `#0F0F11` |
| Page subtitle | `13` | `400` | `#434548` |
| Field label | `11` | `600` | `#0F0F11` |
| Input placeholder | `12` | `400` | `#7F7F7F` |
| Password mask | `14` | `400` | `#7F7F7F`, `letter-spacing="2"` |
| Button label | `14` | `600` | `white` on black |
| Google/Guest inline buttons | `13` | `600` | `#0F0F11` |
| Footer link ("Sign in") | `13` | `400` body / `600` link | `#434548` / `#0F0F11` underlined |

---

## 4. Form Components

### Input field

- Rect: `width="420"`, `height="38"` (signup) / `40` (login), `rx="8"`, `ry="8"`
- `fill="white"`, `stroke="#747474"`, `stroke-width="1.5"`
- Label sits `12px` above the field, left-aligned at `x=975`
- Placeholder text indented `17px` inside the field (`x=992`)

### Primary button ("Sign in" / "Create account")

- Rect: `width="420"`, `height="42–44"`, `rx="8"`, `ry="8"`, `fill="#0F0F11"`
- Label: centered, `font-size="14"`, `font-weight="600"`, `fill="white"`
- No hover state is drawn in the mockup; implementation should add an `:hover` opacity/darkening step (e.g. `opacity: .9`).

### "OR" divider

- Left rule: `stroke="#D8D8D8"`, `stroke-width="1"`, length ~`182px`
- Label: `OR` in `#747474`, `font-size="11"`, `letter-spacing="2"`
- Right rule: matches the left

### Secondary buttons — Google / Guest

Same rounded-rect shell as the input fields: `rx="8"`, `fill="white"`, `stroke="#747474"`, `stroke-width="1.5"`.

- **Google**: `48x48` Google G glyph (the four colored segments listed in §2) + "Continue with Google" (login) or "Google" (signup, side-by-side layout)
- **Guest**: monochrome stroked user icon (`stroke="#0F0F11"`, `stroke-width="1.8"`, `fill="none"`, round line caps) + "Continue as guest" (login) or "Guest" (signup)

On **login**, these two buttons stack vertically below the form. On **signup**, they sit side-by-side beneath the divider to save vertical space.

### Footer link

Plain paragraph style with an underlined `<tspan>` for the action word:

- Body copy: `fill="#434548"`
- Link word: `fill="#0F0F11"`, `font-weight="600"`, `text-decoration="underline"`

Login: "Don't have an account? **Create one**"
Signup: "Already have an account? **Sign in**"

---

## 5. Reusable Tokens (suggested names)

If you lift this palette into the live React app, these are the names the auth mockups imply:

```css
--color-ink-900: #0F0F11;  /* brand black, primary button, headings */
--color-ink-700: #434548;  /* secondary text */
--color-ink-500: #747474;  /* borders, tertiary labels */
--color-ink-400: #7F7F7F;  /* placeholder */
--color-ink-200: #D8D8D8;  /* rules, muted text on black */
--color-surface: #FFFFFF;  /* form panel, inputs */

--radius-field: 8px;
--radius-button: 8px;

--font-stack: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
```

---

## 6. Accessibility Notes

- Body text contrast: `#434548` on `#FFFFFF` = **9.5:1** (AAA).
- Placeholder `#7F7F7F` on `#FFFFFF` = **4.6:1** (AA for large; borderline for body — acceptable for placeholders only).
- Primary button: `white` on `#0F0F11` = **19.7:1** (AAA).
- Tagline `#D8D8D8` on `#0F0F11` = **13.1:1** (AAA).
- All interactive shells use a `1.5px` stroke, which keeps the focus ring legible when overlaid.
