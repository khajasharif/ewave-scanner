// Draws a tiny SVG polyline for each row's 0 -> 1 -> 2 -> "3?" pivots,
// so the shape of the detected wave is visible at a glance.
(function () {
  const W = 160, H = 56, PAD = 8;
  const colors = { "0": "#7C868F", "1": "#F2B705", "2": "#F2554C", "3?": "#34D399" };

  document.querySelectorAll(".sparkline").forEach((svg) => {
    let pivots;
    try {
      pivots = JSON.parse(svg.dataset.pivots || "[]");
    } catch (e) {
      return;
    }
    if (!pivots.length) return;

    const prices = pivots.map((p) => p.price);
    const min = Math.min(...prices), max = Math.max(...prices);
    const range = max - min || 1;

    const points = pivots.map((p, i) => {
      const x = PAD + (i / (pivots.length - 1)) * (W - 2 * PAD);
      const y = H - PAD - ((p.price - min) / range) * (H - 2 * PAD);
      return { x, y, label: p.label };
    });

    const pathD = points.map((pt, i) => (i === 0 ? "M" : "L") + pt.x.toFixed(1) + "," + pt.y.toFixed(1)).join(" ");

    const ns = "http://www.w3.org/2000/svg";
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", pathD);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "#3A4148");
    path.setAttribute("stroke-width", "1.5");
    svg.appendChild(path);

    points.forEach((pt, i) => {
      const label = pivots[i].label;
      const circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", pt.x);
      circle.setAttribute("cy", pt.y);
      circle.setAttribute("r", i === points.length - 1 ? 3.5 : 2.5);
      circle.setAttribute("fill", colors[label] || "#7C868F");
      svg.appendChild(circle);
    });
  });
})();
