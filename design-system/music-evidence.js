const data = JSON.parse(document.getElementById('music-data').textContent);
const audio = document.getElementById('audio');
function bindRoll(canvas, notes) {
const context = canvas.getContext('2d');
const low = notes.reduce((value, n) => Math.min(value, n.pitch), 60) - 2;
const high = notes.reduce((value, n) => Math.max(value, n.pitch), 72) + 2;
const duration = notes.reduce((value, n) => Math.max(value, n.end), Math.max(1, data.analysis.duration));
const tokens = getComputedStyle(document.documentElement);
const color = name => tokens.getPropertyValue(name).trim();
function draw() {
  const ratio = window.devicePixelRatio || 1;
  const {width, height} = canvas.getBoundingClientRect();
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  context.scale(ratio, ratio);
  const left = 38, top = 16, plotWidth = width - 50, plotHeight = height - 46;
  const x = time => left + time / duration * plotWidth;
  const y = pitch => top + (high - pitch) / (high - low) * plotHeight;
  context.font = `12px ${color('--font-sans')}`;
  context.strokeStyle = color('--color-neutral-200');
  context.fillStyle = color('--color-neutral-500');
  for (let pitch = Math.ceil(low / 12) * 12; pitch <= high; pitch += 12) {
    context.fillText(String(pitch), 5, y(pitch) + 4);
    context.beginPath(); context.moveTo(left, y(pitch)); context.lineTo(width - 12, y(pitch)); context.stroke();
  }
  for (let time = 0; time <= duration; time += 10) context.fillText(String(time), x(time), height - 9);
  context.fillStyle = color('--color-brand-500');
  for (const note of notes) context.fillRect(x(note.start), y(note.pitch), Math.max(1,x(note.end)-x(note.start)), Math.max(2,plotHeight/(high-low)*.75));
  context.strokeStyle = color('--color-danger-500');
  context.beginPath(); context.moveTo(x(audio.currentTime), top); context.lineTo(x(audio.currentTime), height-30); context.stroke();
}
new ResizeObserver(draw).observe(canvas);
audio.addEventListener('timeupdate', draw);
audio.addEventListener('seeked', draw);
draw();
}
bindRoll(document.getElementById('roll'), data.notes);
document.querySelectorAll('canvas[data-track]').forEach(canvas => bindRoll(canvas, data.tracks[Number(canvas.dataset.track)].notes));
audio.addEventListener('error', () => { document.getElementById('media-error').hidden = false; });
