// Pablo mascot assets. Run: desktop/node_modules/electron/dist/electron.exe assets/character/build.js
// In:  pablo-default.webp (full body), pablo-poses.webp (sheet: Default | Waving, Thinking / Surprised, Confident),
//      pablo-head.webp (face + hat: the app icon)
// Out: desktop/assets/pablo.ico + pablo.png (app / shortcut / taskbar)
//      src/pablo_v2/skill/mascot.py (data URIs for the viewer), preview/*.png (to eyeball)
// Paper outside the figure -> transparent; inside stays white, so it reads the same on a dark page. No colour or effects.
const { app, BrowserWindow } = require("electron");
const fs = require("fs"), path = require("path");
const HERE = __dirname, ROOT = path.join(HERE, "..", "..");

// pose crops on the sheet, as fractions of its size (each is then trimmed to its ink)
const POSES = { waving: [.435, 0, .705, .45], thinking: [.74, 0, .975, .45],
                surprised: [.455, .48, .7, .915], confident: [.735, .48, .97, .915] };

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { offscreen: true } });
  const url = f => "file:///" + path.join(HERE, f).replace(/\\/g, "/");
  await win.loadURL(url("pablo-default.webp"));  // a file:// page may read the other file:// image
  win.webContents.on("console-message", e => console.error("renderer:", e.message));
  const out = await win.webContents.executeJavaScript(`(async () => {
    const load = src => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = src; });
    const canvas = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
    // ink -> black alpha; paper reached from the crop's edge -> transparent, enclosed paper -> white. Returns the canvas + ink bbox
    function ink(img, r) {
      const W = img.naturalWidth, H = img.naturalHeight, [x0, y0, x1, y1] = r.map((f, i) => Math.round(f * (i % 2 ? H : W)));
      const c = canvas(x1 - x0, y1 - y0), g = c.getContext("2d"); g.drawImage(img, -x0, -y0);
      const d = g.getImageData(0, 0, c.width, c.height), p = d.data; let L = c.width, T = c.height, R = 0, B = 0;
      for (let i = 0; i < p.length; i += 4) {
        const a = Math.max(0, Math.min(255, (235 - (.299 * p[i] + .587 * p[i + 1] + .114 * p[i + 2])) * 1.4));
        p[i] = p[i + 1] = p[i + 2] = 0; p[i + 3] = a;
        if (a > 60) { const x = (i / 4) % c.width, y = (i / 4 / c.width) | 0; L = Math.min(L, x); R = Math.max(R, x); T = Math.min(T, y); B = Math.max(B, y); }
      }
      const W2 = c.width, H2 = c.height, G = Math.round(W2 / 55);  // G closes small gaps in the outline
      // square dilation of a 0/1 mask by G (separable running max)
      const grow = m => { const t = new Uint8Array(m.length), o = new Uint8Array(m.length);
        for (let y = 0; y < H2; y++) for (let x = 0; x < W2; x++) { let v = 0; for (let k = Math.max(0, x - G); k <= Math.min(W2 - 1, x + G) && !v; k++) v = m[y * W2 + k]; t[y * W2 + x] = v; }
        for (let x = 0; x < W2; x++) for (let y = 0; y < H2; y++) { let v = 0; for (let k = Math.max(0, y - G); k <= Math.min(H2 - 1, y + G) && !v; k++) v = t[k * W2 + x]; o[y * W2 + x] = v; }
        return o; };
      const wall = grow(Uint8Array.from({ length: W2 * H2 }, (_, i) => p[i * 4 + 3] >= 128 ? 1 : 0));
      const flood = new Uint8Array(W2 * H2), st = [];  // outside paper, kept G away from the ink
      for (let x = 0; x < W2; x++) st.push(x, (H2 - 1) * W2 + x); for (let y = 0; y < H2; y++) st.push(y * W2, y * W2 + W2 - 1);
      while (st.length) { const i = st.pop(); if (flood[i] || wall[i]) continue; flood[i] = 1; const x = i % W2;
        if (x > 0) st.push(i - 1); if (x < W2 - 1) st.push(i + 1); if (i >= W2) st.push(i - W2); if (i < W2 * (H2 - 1)) st.push(i + W2); }
      const out = grow(flood);  // grow back up to the outline
      for (let i = 0; i < out.length; i++) if (!out[i]) { const a = p[i * 4 + 3]; p[i * 4] = p[i * 4 + 1] = p[i * 4 + 2] = 255 - a; p[i * 4 + 3] = 255; }
      g.putImageData(d, 0, 0);
      return { c, box: [L, T, R + 1, B + 1] };
    }
    // the ink box (top part only when cut < 1), padded 3%, scaled to height h
    function png({ c, box: [L, T, R, B] }, h, cut = 1) {
      B = T + Math.round((B - T) * cut); const pad = Math.round((B - T) * .03);
      L = Math.max(0, L - pad); T = Math.max(0, T - pad); R = Math.min(c.width, R + pad); B = Math.min(c.height, B + pad);
      const w = Math.round((R - L) * h / (B - T)), o = canvas(w, h), g = o.getContext("2d");
      g.imageSmoothingQuality = "high"; g.drawImage(c, L, T, R - L, B - T, 0, 0, w, h);
      return o.toDataURL("image/png");
    }
    const one = await load(${JSON.stringify(url("pablo-default.webp"))}), sheet = await load(${JSON.stringify(url("pablo-poses.webp"))});
    const P = ${JSON.stringify(POSES)}, art = { default: png(ink(one, [0, 0, 1, 1]), 360) };
    for (const k in P) art[k] = png(ink(sheet, P[k]), 240);
    art.think = png(ink(sheet, P.thinking), 64, .6);  // head + hand on the chin + "?" (the composer's small icon)
    // the head centred in an s x s square, with a thin white rim so the black hat stays visible on a dark taskbar
    const hd = ink(await load(${JSON.stringify(url("pablo-head.webp"))}), [0, 0, 1, 1]);
    function square({ c, box: [L, T, R, B] }, s) {
      const side = Math.max(R - L, B - T) * 1.08, x = (L + R - side) / 2, y = (T + B - side) / 2, rim = Math.max(1, s / 40);
      const fig = canvas(s, s), fg = fig.getContext("2d"); fg.imageSmoothingQuality = "high"; fg.drawImage(c, x, y, side, side, 0, 0, s, s);
      const sil = canvas(s, s), sg = sil.getContext("2d"); sg.drawImage(fig, 0, 0); sg.globalCompositeOperation = "source-in"; sg.fillStyle = "#fff"; sg.fillRect(0, 0, s, s);
      const o = canvas(s, s), g = o.getContext("2d");
      for (let a = 0; a < 16; a++) g.drawImage(sil, rim * Math.cos(a * Math.PI / 8), rim * Math.sin(a * Math.PI / 8));
      g.drawImage(fig, 0, 0); return o.toDataURL("image/png");
    }
    const icons = {};
    for (const s of [16, 20, 24, 32, 40, 48, 64, 128, 256]) icons[s] = square(hd, s);
    art.head = icons[64];
    return { art, icons };
  })().catch(e => { console.error(e.stack); throw e; })`);
  const buf = u => Buffer.from(u.split(",")[1], "base64");
  // .ico with PNG entries (Vista+): header, 16-byte directory entries, then the PNGs
  const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256], pngs = sizes.map(s => buf(out.icons[s]));
  const hdr = Buffer.alloc(6 + 16 * sizes.length); hdr.writeUInt16LE(1, 2); hdr.writeUInt16LE(sizes.length, 4);
  let off = hdr.length;
  sizes.forEach((s, i) => { const e = 6 + 16 * i; hdr[e] = s % 256; hdr[e + 1] = s % 256; hdr.writeUInt16LE(1, e + 4);
    hdr.writeUInt16LE(32, e + 6); hdr.writeUInt32LE(pngs[i].length, e + 8); hdr.writeUInt32LE(off, e + 12); off += pngs[i].length; });
  fs.writeFileSync(path.join(ROOT, "desktop", "assets", "pablo.ico"), Buffer.concat([hdr, ...pngs]));
  fs.writeFileSync(path.join(ROOT, "desktop", "assets", "pablo.png"), buf(out.icons[256]));
  fs.mkdirSync(path.join(HERE, "preview"), { recursive: true });
  for (const [k, u] of Object.entries(out.art)) fs.writeFileSync(path.join(HERE, "preview", k + ".png"), buf(u));
  for (const s of sizes) fs.writeFileSync(path.join(HERE, "preview", `icon-${s}.png`), buf(out.icons[s]));
  fs.writeFileSync(path.join(ROOT, "src", "pablo_v2", "skill", "mascot.py"),
    '"""Pablo mascot images as data URIs. Generated by assets/character/build.js; do not edit."""\n\nART = {\n' +
    Object.entries(out.art).map(([k, u]) => `    ${JSON.stringify(k)}: ${JSON.stringify(u)},`).join("\n") + "\n}\n");
  console.log("ok", Object.entries(out.art).map(([k, u]) => `${k} ${Math.round(u.length / 1024)}KB`).join(", "));
  app.quit();
}).catch(e => { console.error(e); app.exit(1); });
