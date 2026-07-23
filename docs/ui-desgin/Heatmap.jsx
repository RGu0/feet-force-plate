// FeetForcePlate — plantar pressure heatmap on the light data canvas.
// The core data visualization: light canvas + blue grid + isolated heat scale.
// Pressure blobs are soft "energy" radial gradients (not hard color tiles);
// low pressure fades into the canvas, high pressure gets a soft outer glow.

function Heatmap({ live = false, side = "both" }) {
  const canvasRef = React.useRef(null);

  React.useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const draw = (t) => {
      const w = cv.clientWidth, h = cv.clientHeight;
      cv.width = w * dpr; cv.height = h * dpr;
      const ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const feet = side === "both" ? [0.34, 0.66] : side === "left" ? [0.4] : [0.6];
      const pulse = live ? 1 + 0.06 * Math.sin(t / 380) : 1;
      feet.forEach((cx0, fi) => {
        const cx = cx0 * w;
        // pressure regions: heel, arch(low), forefoot, big toe
        const regions = [
          { y: 0.72, r: 0.14, load: 0.95 },  // heel — high
          { y: 0.52, r: 0.10, load: 0.30 },  // arch — low
          { y: 0.34, r: 0.15, load: 0.90 },  // forefoot — high
          { y: 0.20, r: 0.07, load: 0.55 },  // toes
          { y: 0.16, r: 0.05, load: 0.72, dx: fi === 0 ? -0.03 : 0.03 }, // big toe
        ];
        regions.forEach((rg) => {
          const gy = rg.y * h;
          const gx = cx + (rg.dx || 0) * w;
          const rad = rg.r * h * (0.9 + rg.load * 0.4) * pulse;
          const g = ctx.createRadialGradient(gx, gy, rad * 0.1, gx, gy, rad);
          const col = heatColor(rg.load);
          g.addColorStop(0, rgba(col, 0.85 * rg.load + 0.1));
          g.addColorStop(0.5, rgba(col, (0.85 * rg.load + 0.1) * 0.5));
          g.addColorStop(1, rgba(col, 0));
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(gx, gy, rad, 0, Math.PI * 2);
          ctx.fill();
        });
      });
    };
    let raf;
    const loop = (t) => { draw(t); if (live) raf = requestAnimationFrame(loop); };
    if (live) raf = requestAnimationFrame(loop); else draw(0);
    return () => raf && cancelAnimationFrame(raf);
  }, [live, side]);

  return (
    <div style={{
      position: "relative", width: "100%", height: "100%", borderRadius: "var(--radius-card)",
      background: "var(--viz-canvas)", border: "1px solid var(--viz-canvas-border)",
      backgroundImage: "linear-gradient(var(--viz-grid) 1px,transparent 1px),linear-gradient(90deg,var(--viz-grid) 1px,transparent 1px)",
      backgroundSize: "28px 28px", overflow: "hidden",
    }}>
      <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
      <div style={{ position: "absolute", top: 12, left: 12, font: "var(--text-secondary-size)", color: "var(--viz-axis-label)", background: "rgba(255,255,255,.7)", padding: "2px 8px", borderRadius: 6 }}>足底压力分布</div>
      <Legend />
    </div>
  );
}

function Legend() {
  return (
    <div style={{ position: "absolute", bottom: 12, right: 12, display: "flex", flexDirection: "column", gap: 4, background: "rgba(255,255,255,.75)", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--viz-canvas-border)" }}>
      <div style={{ font: "var(--text-secondary-size)", color: "var(--viz-axis-label)" }}>压力</div>
      <div style={{ width: 120, height: 10, borderRadius: 5, background: "linear-gradient(90deg,var(--viz-heat-1),var(--viz-heat-2),var(--viz-heat-3),var(--viz-heat-4),var(--viz-heat-5))" }} />
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-num)", fontSize: 10, color: "var(--viz-axis-label)" }}><span>低</span><span>高</span></div>
    </div>
  );
}

const HEAT = [[45,79,168],[31,159,206],[99,198,133],[240,194,74],[226,85,57]];
function heatColor(load) {
  const p = Math.max(0, Math.min(1, load)) * (HEAT.length - 1);
  const i = Math.floor(p), f = p - i;
  const a = HEAT[i], b = HEAT[Math.min(i + 1, HEAT.length - 1)];
  return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
}
function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }
window.Heatmap = Heatmap;
