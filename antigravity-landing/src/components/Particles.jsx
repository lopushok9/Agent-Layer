import { useRef, useEffect, useMemo } from 'react'
import { createNoise2D } from '../utils/noise'

// --- Config ---
const MAX_PARTICLES = 100
const SPAWN_RADIUS_MIN = 120
const SPAWN_RADIUS_MAX = 280
const MIN_LIFESPAN = 0.4
const MAX_LIFESPAN = 1.0
const BASE_SPAWN_RATE = 4
const MAX_SPAWN_RATE = 12
const NOISE_SCALE = 0.003
const NOISE_TIME_SCALE = 0.3
const DRIFT_FORCE = 15
const DAMPING = 0.96
const REPULSION_RADIUS = 80
const REPULSION_STRENGTH = 40

const CHARS = ['~', '=', '-', '\u2014', '\u00b7', '+']
const COLORS = ['#000000']
const FONT_MIN = 10
const FONT_MAX = 20

// --- Pool ---
function createPool() {
  return {
    x: new Float32Array(MAX_PARTICLES),
    y: new Float32Array(MAX_PARTICLES),
    vx: new Float32Array(MAX_PARTICLES),
    vy: new Float32Array(MAX_PARTICLES),
    age: new Float32Array(MAX_PARTICLES),
    lifespan: new Float32Array(MAX_PARTICLES),
    rotation: new Float32Array(MAX_PARTICLES),
    rotSpeed: new Float32Array(MAX_PARTICLES),
    fontSize: new Float32Array(MAX_PARTICLES),
    charIdx: new Uint8Array(MAX_PARTICLES),
    colorIdx: new Uint8Array(MAX_PARTICLES),
    alive: new Uint8Array(MAX_PARTICLES),
    seed: new Float32Array(MAX_PARTICLES),
  }
}

function spawn(pool, i, mx, my, mvx, mvy) {
  const angle = Math.random() * Math.PI * 2
  const dist = SPAWN_RADIUS_MIN + Math.random() * (SPAWN_RADIUS_MAX - SPAWN_RADIUS_MIN)

  pool.x[i] = mx + Math.cos(angle) * dist
  pool.y[i] = my + Math.sin(angle) * dist

  const da = angle + (Math.random() - 0.5)
  const ds = 3 + Math.random() * 10
  pool.vx[i] = Math.cos(da) * ds + mvx * 0.1
  pool.vy[i] = Math.sin(da) * ds + mvy * 0.1

  pool.age[i] = 0
  pool.lifespan[i] = MIN_LIFESPAN + Math.random() * (MAX_LIFESPAN - MIN_LIFESPAN)
  pool.rotation[i] = 0
  pool.rotSpeed[i] = 0
  pool.fontSize[i] = FONT_MIN + Math.random() * (FONT_MAX - FONT_MIN)
  pool.charIdx[i] = Math.floor(Math.random() * CHARS.length)
  pool.colorIdx[i] = Math.floor(Math.random() * COLORS.length)
  pool.alive[i] = 1
  pool.seed[i] = Math.random() * 1000
}

export function Particles() {
  const canvasRef = useRef(null)
  const poolRef = useRef(createPool())
  const mouseRef = useRef({
    x: 0, y: 0, prevX: 0, prevY: 0,
    speed: 0, entered: false,
  })
  const noise2D = useMemo(() => createNoise2D(), [])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let raf
    let lastTime = performance.now()

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = window.innerWidth * dpr
      canvas.height = window.innerHeight * dpr
      canvas.style.width = window.innerWidth + 'px'
      canvas.style.height = window.innerHeight + 'px'
      ctx.scale(dpr, dpr)
    }
    resize()
    window.addEventListener('resize', resize)

    const onMove = (e) => {
      const m = mouseRef.current
      if (!m.entered) {
        m.entered = true
        m.x = e.clientX
        m.y = e.clientY
        m.prevX = e.clientX
        m.prevY = e.clientY
      }
      m.x = e.clientX
      m.y = e.clientY
    }
    window.addEventListener('pointermove', onMove)

    const loop = (now) => {
      raf = requestAnimationFrame(loop)
      const dt = Math.min((now - lastTime) / 1000, 0.1)
      lastTime = now
      const time = now / 1000

      const pool = poolRef.current
      const mouse = mouseRef.current
      const w = window.innerWidth
      const h = window.innerHeight

      // Clear
      ctx.clearRect(0, 0, w, h)

      // Mouse velocity
      if (mouse.entered) {
        const mvx = mouse.x - mouse.prevX
        const mvy = mouse.y - mouse.prevY
        mouse.speed = Math.sqrt(mvx * mvx + mvy * mvy)
        mouse.prevX = mouse.x
        mouse.prevY = mouse.y

        // Spawn
        const rate = Math.min(MAX_SPAWN_RATE, BASE_SPAWN_RATE + mouse.speed * 0.5)
        const count = mouse.speed > 0.5 ? Math.ceil(rate * dt * 60) : 0

        let spawned = 0
        for (let i = 0; i < MAX_PARTICLES && spawned < count; i++) {
          if (!pool.alive[i]) {
            spawn(pool, i, mouse.x, mouse.y, mvx, mvy)
            spawned++
          }
        }
      }

      // Update & draw
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'

      for (let i = 0; i < MAX_PARTICLES; i++) {
        if (!pool.alive[i]) continue

        pool.age[i] += dt
        if (pool.age[i] >= pool.lifespan[i]) {
          pool.alive[i] = 0
          continue
        }

        const t = pool.age[i] / pool.lifespan[i]

        // Noise drift
        const nx = noise2D(pool.x[i] * NOISE_SCALE, time * NOISE_TIME_SCALE + pool.seed[i])
        const ny = noise2D(pool.y[i] * NOISE_SCALE + 137, time * NOISE_TIME_SCALE + pool.seed[i])
        pool.vx[i] += nx * DRIFT_FORCE * dt
        pool.vy[i] += ny * DRIFT_FORCE * dt
        pool.vx[i] *= DAMPING
        pool.vy[i] *= DAMPING

        // Repulsion
        if (mouse.entered) {
          const dx = pool.x[i] - mouse.x
          const dy = pool.y[i] - mouse.y
          const distSq = dx * dx + dy * dy
          if (distSq < REPULSION_RADIUS * REPULSION_RADIUS && distSq > 1) {
            const dist = Math.sqrt(distSq)
            const f = (1 - dist / REPULSION_RADIUS) * REPULSION_STRENGTH * dt
            pool.vx[i] += (dx / dist) * f
            pool.vy[i] += (dy / dist) * f
          }
        }

        pool.x[i] += pool.vx[i] * dt
        pool.y[i] += pool.vy[i] * dt
        pool.rotation[i] += pool.rotSpeed[i] * dt

        // Alpha: fast fade in, smooth fade out
        let alpha
        if (t < 0.1) {
          alpha = t / 0.1
        } else {
          alpha = 1 - (t - 0.1) / 0.9
        }
        alpha *= 0.7

        // Draw
        ctx.save()
        ctx.globalAlpha = alpha
        ctx.fillStyle = COLORS[pool.colorIdx[i]]
        ctx.font = `${Math.round(pool.fontSize[i])}px "SF Mono", "Fira Code", "Cascadia Code", monospace`
        ctx.translate(pool.x[i], pool.y[i])
        ctx.rotate(pool.rotation[i])
        ctx.fillText(CHARS[pool.charIdx[i]], 0, 0)
        ctx.restore()
      }
    }

    raf = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('pointermove', onMove)
    }
  }, [noise2D])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        zIndex: 0,
        pointerEvents: 'none',
      }}
    />
  )
}
