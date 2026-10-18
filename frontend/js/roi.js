// Draw a region of interest on a photo (mouse or touch). Reports [x0,y0,x1,y1] as fractions
// of the actual image (letterboxing from object-fit: contain is accounted for).

export function mountRoi(container, imgUrl, onChange) {
  container.innerHTML = `<div class="roi-wrap"><img alt="photo"><canvas></canvas></div>`;
  const img = container.querySelector("img"), cv = container.querySelector("canvas"), g = cv.getContext("2d");
  let box = null, start = null;

  const imgRect = () => {
    const W = cv.clientWidth, H = cv.clientHeight, r = img.naturalWidth / img.naturalHeight;
    let w = W, h = W / r;
    if (h > H) { h = H; w = H * r; }
    return { x: (W - w) / 2, y: (H - h) / 2, w, h };
  };
  const draw = () => {
    cv.width = cv.clientWidth * devicePixelRatio; cv.height = cv.clientHeight * devicePixelRatio;
    g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    if (!box) return;
    const R = imgRect();
    const x = R.x + box[0] * R.w, y = R.y + box[1] * R.h, w = (box[2] - box[0]) * R.w, h = (box[3] - box[1]) * R.h;
    g.fillStyle = "rgba(0,0,0,.45)";
    g.fillRect(0, 0, cv.clientWidth, cv.clientHeight);
    g.clearRect(x, y, w, h);
    g.strokeStyle = "#ff3b3b"; g.lineWidth = 2.5; g.setLineDash([]); g.strokeRect(x, y, w, h);
    g.fillStyle = "#ff3b3b"; g.font = "600 12px system-ui"; g.fillText("Region of interest", x + 4, Math.max(14, y - 6));
  };
  const toFrac = (e) => {
    const r = cv.getBoundingClientRect(), R = imgRect();
    const p = e.touches ? e.touches[0] : e;
    return [Math.min(1, Math.max(0, (p.clientX - r.left - R.x) / R.w)), Math.min(1, Math.max(0, (p.clientY - r.top - R.y) / R.h))];
  };
  const down = (e) => { e.preventDefault(); start = toFrac(e); box = [...start, ...start]; draw(); };
  const move = (e) => {
    if (!start) return; e.preventDefault();
    const p = toFrac(e);
    box = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
    draw();
  };
  const up = () => {
    if (!start) return; start = null;
    if (box && (box[2] - box[0] < 0.02 || box[3] - box[1] < 0.02)) box = null;
    draw(); onChange(box ? box.map((v) => +v.toFixed(4)) : null);
  };
  cv.addEventListener("mousedown", down); cv.addEventListener("touchstart", down, { passive: false });
  window.addEventListener("mousemove", move); cv.addEventListener("touchmove", move, { passive: false });
  window.addEventListener("mouseup", up); cv.addEventListener("touchend", up);
  img.onload = draw;
  img.src = imgUrl;
  new ResizeObserver(draw).observe(cv);
  return { clear() { box = null; draw(); onChange(null); } };
}
