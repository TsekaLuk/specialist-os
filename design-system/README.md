# Project Design System

This directory is the product UI boundary for Specialist OS. The generated
Capability Workspace consumes these files; feature pages must not introduce
their own color, radius, shadow or typography primitives.

## Layers

- `frontend/src/design-system/index.tsx` is the canonical React API. Feature
  code imports Button, Input, SearchInput, NavigationItem and StatusBadge here.
- `frontend/src/components/ui/` is the approved open-code infrastructure layer,
  not a feature import target. Button/Badge use shadcn's CVA + Radix Slot
  structure; Input uses its accessible native-input contract.
- `components.css` owns control geometry, focus, variants and semantic tokens.
- `react-workspace.css` owns the React workspace layout. It does not restyle
  the internals of Badge, Button or Input.

- `tokens.css` owns primitive, semantic and component tokens.
- `workspace.css` owns the stable Workspace pattern and responsive behavior.
- `music-evidence.css` and `music-evidence.js` own the read-only listening and
  note-timeline evidence pattern. They consume the shared tokens and plot only
  supplied note events; audio playback uses the browser's accessible player.
- future primitives and patterns belong here before they are reused by a feature.

## Visual direction

- Density: compact-medium, application-first.
- Surfaces: mostly flat with one raised result surface.
- Radius: restrained, 4-8px.
- Color: charcoal text, deep green actions, lime active state.
- Typography: neutral and precise, with a small fixed role scale.
- Motion: fast, subtle, and disabled under reduced motion.
- Icon language: Lucide where an icon is needed.

## Consumption boundary

Generated pages may consume semantic classes from this directory. They must not
add raw colors, arbitrary radii, shadows or new type scales. External UI
libraries must be normalized here before a feature uses
them.

## Agent rules

Open-code intake reviewed on 2026-09-07:
[Button](https://ui.shadcn.com/r/styles/new-york-v4/button.json),
[Badge](https://ui.shadcn.com/r/styles/new-york-v4/badge.json),
[Input](https://ui.shadcn.com/r/styles/new-york-v4/input.json).
Project normalization replaces upstream visual utilities with token-owned
component classes and limits variants to those used by this product. Badge is
24px tall, nonshrinking and single-line, with a 12px icon. Input and Button
retain focus-visible, disabled and native keyboard behavior. The unused legacy
field.tsx is not part of the canonical API.

`npm test` in frontend checks feature import/control boundaries. Browser checks
verify status geometry, image decoding, clipboard, focus and responsive layout.

1. Search this directory before creating a new UI pattern.
2. Reuse an existing token before adding a token.
3. Keep business semantics in the feature and visual behavior here.
4. Promote repeated compositions into a named pattern after the third use.
5. Keep keyboard, focus, labels, responsive behavior and reduced motion in the
   pattern rather than asking each feature to recreate them.
