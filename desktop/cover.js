// in the viewer: the text pdf.js has under the panel's .hl boxes (each item cut by the box's x range), vs the quote
module.exports = `(async () => {
  const p = $("panel"), a = M.anchors[hist[hi].e], sheet = p.querySelector(".pg"), L = await pdfLib();
  const pg = await (await pdfs[a.source]).getPage(a.page), vp = pg.getViewport({ scale: parseFloat(sheet.style.width) / pg.getViewport({ scale: 1 }).width });
  const hl = [...sheet.querySelectorAll(".hl")].map(d => ({ l: parseFloat(d.style.left), t: parseFloat(d.style.top), r: parseFloat(d.style.left) + parseFloat(d.style.width), b: parseFloat(d.style.top) + parseFloat(d.style.height) }));
  let got = "";
  for (const it of (await pg.getTextContent()).items) {
    if (!it.str) continue;
    const tx = L.Util.transform(vp.transform, it.transform), fh = Math.hypot(tx[2], tx[3]), l = tx[4], w = it.width * vp.scale, y = tx[5] - fh / 2, n = it.str.length;
    for (const b of hl) if (y > b.t && y < b.b && l < b.r && l + w > b.l)
      got += it.str.slice(Math.max(0, Math.round((b.l - l) / w * n)), Math.min(n, Math.round((b.r - l) / w * n)));
  }
  const g = keyed(got)[0], q = keyed(a.exact)[0];
  return { page: +p.querySelector(".pnum").textContent.split("/")[0], boxes: hl.length, hit: g.includes(q), ratio: +(g.length / q.length).toFixed(2), ms: +p.dataset.ms, got };
})()`;
