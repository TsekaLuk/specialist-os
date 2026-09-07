# Project Design System

This directory is the product UI boundary for Specialist OS. The generated
Capability Workspace consumes these files; feature pages must not introduce
their own color, radius, shadow or typography primitives.

## Layers

- `tokens.css` owns primitive, semantic and component tokens.
- `workspace.css` owns the stable Workspace pattern and responsive behavior.
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
libraries, if introduced later, must be normalized here before a feature uses
them.

## Agent rules

1. Search this directory before creating a new UI pattern.
2. Reuse an existing token before adding a token.
3. Keep business semantics in the feature and visual behavior here.
4. Promote repeated compositions into a named pattern after the third use.
5. Keep keyboard, focus, labels, responsive behavior and reduced motion in the
   pattern rather than asking each feature to recreate them.
