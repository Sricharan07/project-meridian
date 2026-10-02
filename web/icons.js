// The app's icons: one 16px grid, one 1.5px stroke, round caps. Drawn here rather than pulled
// from a set, so there are only as many as the interface uses and they all look like one family.

const paths = {
  search: '<circle cx="7" cy="7" r="4.75"/><path d="M10.5 10.5l3.25 3.25"/>',
  arrowUp: '<path d="M8 13.25V3M3.75 7.25L8 3l4.25 4.25"/>',
  arrowRight: '<path d="M3 8h9.5M8.5 3.75L12.75 8 8.5 12.25"/>',
  chevron: '<path d="M6 3.5L10.5 8 6 12.5"/>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  minus: '<path d="M3 8h10"/>',
  fit: '<path d="M2.75 6V2.75H6M10 2.75h3.25V6M13.25 10v3.25H10M6 13.25H2.75V10"/>',
  sheet: '<rect x="2.75" y="3.25" width="10.5" height="9.5" rx="1.5"/><path d="M8.5 9.75h3M2.75 9.75h3.5v3"/>',
  cube: '<path d="M8 2.25l5.25 3v5.5L8 13.75l-5.25-3v-5.5z"/><path d="M2.75 5.25L8 8.25l5.25-3M8 8.25v5.5"/>',
  section: '<path d="M2.75 13.25l10.5-10.5"/><path d="M2.75 8.75l6-6M7.25 13.25l6-6" opacity=".55"/>',
  ruler: '<path d="M2.75 10.5l7.75-7.75 2.75 2.75-7.75 7.75z"/><path d="M5 8.25l1.25 1.25M7 6.25l1.25 1.25M9 4.25l1.25 1.25"/>',
  scan: '<path d="M2.75 5.5V2.75H5.5M10.5 2.75h2.75V5.5M13.25 10.5v2.75H10.5M5.5 13.25H2.75V10.5M2.75 8h10.5"/>',
  sun: '<circle cx="8" cy="8" r="2.75"/><path d="M8 1.75v1.5M8 12.75v1.5M1.75 8h1.5M12.75 8h1.5M3.6 3.6l1.05 1.05M11.35 11.35l1.05 1.05M3.6 12.4l1.05-1.05M11.35 4.65l1.05-1.05"/>',
  moon: '<path d="M13.25 9.75A5.5 5.5 0 016.25 2.75a5.5 5.5 0 107 7z"/>',
  close: '<path d="M4 4l8 8M12 4l-8 8"/>',
  download: '<path d="M8 2.75v7.5M4.75 7.25L8 10.5l3.25-3.25M3 13.25h10"/>',
  link: '<path d="M6.75 9.25l2.5-2.5M7.5 4.5l.9-.9a2.5 2.5 0 013.5 3.5l-.9.9M8.5 11.5l-.9.9a2.5 2.5 0 01-3.5-3.5l.9-.9"/>',
};

// Status marks are filled, so they read at a glance next to a value.
const marks = {
  agree: '<circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.25 8.1l1.85 1.85 3.65-3.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
  single: '<circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 1.75a6.25 6.25 0 010 12.5z" fill="currentColor"/>',
  warn: '<path d="M8 1.9l6.35 11.35H1.65z" fill="currentColor"/><path d="M8 6.25v3.25" stroke="var(--on-red)" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="11.4" r=".85" fill="var(--on-red)"/>',
  blank: '<circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.2 2.2"/>',
  info: '<circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 7.25v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="4.9" r=".85" fill="currentColor"/>',
};

export function icon(name, size = 16) {
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
}

export function mark(name, size = 16) {
  return `<svg class="mark-icon ${name}" width="${size}" height="${size}" viewBox="0 0 16 16" aria-hidden="true">${marks[name]}</svg>`;
}
