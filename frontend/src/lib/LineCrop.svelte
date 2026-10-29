<script module>
  /** Every crop needs its own clipPath name, or the browser reuses the first one it finds. */
  let nextId = 0;

  /**
   * The smallest rect covering a PAGE-XML `Coords@points` value, in page coordinates.
   *
   * @param {string | null | undefined} points e.g. `"1030,449 1028,449 1019,456"`
   * @returns {{ x: number, y: number, w: number, h: number } | null} null if unparseable
   */
  function polygonBox(points) {
    const coords = typeof points === 'string' ? points.trim().split(/\s+/) : [];
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const coord of coords) {
      const [x, y] = coord.split(',').map(Number);
      if (x === undefined || y === undefined || !Number.isFinite(x) || !Number.isFinite(y)) {
        return null;
      }
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
    if (!Number.isFinite(minX) || maxX <= minX || maxY <= minY) return null;

    // A hair of breathing room, so the glyphs are not flush against the crop edge.
    const pad = Math.max(1, Math.round((maxY - minY) * 0.08));
    return { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
  }
</script>

<script>
  /**
   * One OCR line shown as the page image cut to that line's own polygon — never a bounding box:
   * the polygon is both the clip and, through the viewBox, the crop. The viewBox does all the
   * coordinate mapping, so the raster's intrinsic pixel size is irrelevant.
   */
  let {
    /** @type {import('./types.js').LineCropView} */
    crop,
  } = $props();

  const clipId = `line-crop-${++nextId}`;
  const box = $derived(polygonBox(crop?.points));
</script>

{#if crop?.url && crop.width && crop.height && box !== null}
  <svg
    class="crop"
    viewBox="{box.x} {box.y} {box.w} {box.h}"
    role="img"
    aria-label="Page image cropped to this line"
    preserveAspectRatio="xMidYMid meet"
  >
    <defs>
      <clipPath id={clipId}>
        <polygon points={crop.points} />
      </clipPath>
    </defs>
    <!-- preserveAspectRatio="none" maps the raster onto exactly the declared page box, which is the
         coordinate space the polygon lives in; the default would letterbox a resized scan inside it
         and shift the crop off the glyphs. The url(#) form matters: without the hash the reference
         is a relative URL, the clip is invalid, and the whole bounding box shows instead. -->
    <image
      href={crop.url}
      x="0"
      y="0"
      width={crop.width}
      height={crop.height}
      clip-path="url(#{clipId})"
      preserveAspectRatio="none"
    />
  </svg>
{/if}
