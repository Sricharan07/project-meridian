// Templates that escape every interpolated value unless it is itself a template.
// Source text (BOM notes, drawing notes) goes straight into the page, so escaping is not optional.

const RAW = Symbol("raw");

export function html(strings, ...values) {
  let out = "";
  strings.forEach((s, i) => {
    out += s;
    if (i < values.length) out += render(values[i]);
  });
  return { [RAW]: out };
}

export const raw = (s) => ({ [RAW]: s });

function render(value) {
  if (value == null || value === false) return "";
  if (Array.isArray(value)) return value.map(render).join("");
  if (value[RAW] !== undefined) return value[RAW];
  return escape(String(value));
}

export function escape(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function mount(element, template) {
  element.innerHTML = render(template);
  return element;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

// An underline that travels to the current item, so a change of place reads as movement.
export function slide(indicator, target, inset = 12) {
  if (!indicator || !target) return;
  indicator.style.width = `${Math.max(target.offsetWidth - 2 * inset, 0)}px`;
  indicator.style.transform = `translateX(${target.offsetLeft + inset}px)`;
}
