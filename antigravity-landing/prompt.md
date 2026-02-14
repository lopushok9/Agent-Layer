Create a full-screen interactive particle background using Three.js (WebGL, not canvas 2D). The visual result must replicate a minimal modern SaaS landing background similar to Google Antigravity auth screen.

Requirements:

Scene setup:

Fullscreen transparent WebGL canvas.

Orthographic camera.

No visible axes or helpers.

Background color: light gray #f5f5f5.

High DPI support.

Particle system behavior:

Particles are generated ONLY inside a circular radius around the mouse cursor (radius ~180px).

When the mouse moves, new particles spawn around it.

Maximum particles on screen ~1200.

Old particles fade out and get removed after lifespan (~2.5–4s).

Particles gently drift with floating motion (low velocity, slight randomness).

Add subtle inertia effect: particles slightly react to mouse movement direction with a soft repulsion force.

Particle appearance:

Shape: short rounded rectangles or thin capsules (not circles).

Each particle has random rotation.

Size: 4px–12px length.

Slight blur/glow effect.

Opacity: 0.5–0.9, fading out at the end of lifespan.

Blend mode: additive or normal with soft transparency.

Color behavior:

Use gradient palette:
purple (#7b61ff)
blue (#4ea1ff)
pink (#ff5ea8)
orange (#ff9a3c)

Each particle picks a random color from that palette.

Over its lifetime, slightly shift hue or brightness.

Some particles subtly animate color over time.

Motion:

Floating behavior like light confetti in zero gravity.

Small noise-based drift (Perlin or simplex noise preferred).

Slight rotation over time.

No sharp movements.

Performance:

Use BufferGeometry.

Use instancing (THREE.InstancedMesh).

Avoid creating geometries per frame.

Use requestAnimationFrame loop.

Clean memory properly.

Interaction:

Track mouse position smoothly (lerp).

On fast movement, slightly increase particle spawn rate.

On mouse stop, particles slowly dissipate.




Visual goal:
Elegant, subtle, airy, premium tech aesthetic. The particles should feel light, minimal, and modern. No chaos, no heavy explosions. Smooth and soft.