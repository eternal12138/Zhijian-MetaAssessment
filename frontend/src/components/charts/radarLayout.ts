/** Reserve space for complete multiline axis labels, independently of the viewport. */
export function radarLayout(width: number, height: number, axisCount = 3) {
  const labelWidth = Math.min(140, Math.max(60, width * 0.29))
  // Three spokes occupy a triangle, not a full circle. Centre its visible bounds
  // (including equal label margins), rather than leaving empty space below it.
  const triangle = axisCount === 3
  const radius = Math.max(0, Math.min(
    (width - labelWidth - 40) / (triangle ? Math.sqrt(3) : 2),
    (height - 104) / (triangle ? 1.5 : 2)
  ))
  return {
    labelWidth,
    radius,
    center: [width / 2, height / 2 + (triangle ? radius / 4 : 0)] as [number, number]
  }
}

export function radarAxisLabel(label: string) {
  return label.replace(/\s*([（(])/, '\n$1')
}

export function escapeChartText(value: unknown) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]!)
}
