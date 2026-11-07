/** Shared synthetic DOM surface for the public v1/v2 runtime. */
class FakeElement {
  constructor(tagName = 'div', id = '') {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.attributes = new Map();
    this.style = { setProperty() {} };
    this.classTokens = new Set();
    this.classList = {
      add: (...values) => values.forEach(value => this.classTokens.add(value)),
      remove: (...values) => values.forEach(value => this.classTokens.delete(value)),
      toggle: (value, force) => {
        const shouldAdd = force === undefined ? !this.classTokens.has(value) : Boolean(force);
        if (shouldAdd) this.classTokens.add(value);
        else this.classTokens.delete(value);
        return shouldAdd;
      },
      contains: value => this.classTokens.has(value),
    };
    this.checked = false;
    this.open = false;
    this.hidden = false;
    this.value = '';
    this._textContent = '';
    this._innerHTML = '';
    this.nodes = new Map();
  }

  get className() { return [...this.classTokens].join(' '); }
  set className(value) { this.classTokens = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._textContent; }
  set textContent(value) { this._textContent = value === null ? '' : String(value); }
  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    this.nodes.clear();
    for (const selector of ['.route', '.bestmark', '.departure-text', '.type-label', '.destination-label',
      '.terminal-badge', '.sub', '.arrival', '.arrival-caption', '.count']) {
      const element = new FakeElement('span');
      element.className = selector.slice(1);
      this.nodes.set(selector, element);
      this.appendChild(element);
    }
  }
  get innerHTML() { return this._innerHTML; }

  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) ?? [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }
  dispatch(name, event = {}) {
    for (const callback of this.listeners.get(name) ?? []) callback({ target: this, key: '', ...event });
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  appendChild(child) {
    if (child.isFragment) {
      this.children.push(...child.children);
      child.children = [];
    } else this.children.push(child);
    return child;
  }
  replaceChildren(...children) {
    this.children = [];
    children.forEach(child => this.appendChild(child));
    this._textContent = '';
  }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch('close'); }
  createDocumentFragment() { const fragment = new FakeElement('#document-fragment'); fragment.isFragment = true; return fragment; }

  querySelector(selector) {
    if (this.nodes.has(selector)) return this.nodes.get(selector);
    const destinationMatch = selector.match(/^\[data-destination-id="([^"]+)"\]$/);
    if (destinationMatch) return this.querySelectorAll('[data-destination-id]').find(node =>
      node.dataset.destinationId === destinationMatch[1]) ?? null;
    return this.querySelectorAll(selector)[0] ?? null;
  }
  querySelectorAll(selector) {
    const descendants = [];
    const visit = element => {
      for (const child of element.children) {
        descendants.push(child);
        visit(child);
      }
    };
    visit(this);
    if (selector === '[data-departure-at]') return descendants.filter(element => element.dataset.departureAt !== undefined);
    if (selector === '[data-destination-id]') return descendants.filter(element => element.dataset.destinationId !== undefined);
    if (selector === '.destination-option') return descendants.filter(element => element.classList.contains('destination-option'));
    if (selector === '.line') return descendants.filter(element => element.classList.contains('line'));
    return [];
  }
}

function makeDom() {
  const ids = ['clock', 'timetable-status', 'board', 'destination-trigger', 'route-display',
    'destination-dialog', 'destination-close', 'destination-list', 'direct-only', 'mode-line', 'mode-departure'];
  const elements = new Map(ids.map(id => [id, new FakeElement(id === 'board' ? 'section' : 'div', id)]));
  const documentRef = {
    body: new FakeElement('body'),
    activeElement: null,
    getElementById: id => elements.get(id) ?? null,
    createDocumentFragment: () => new FakeElement('#document-fragment').markFragment(),
    createElement: tagName => new FakeElement(tagName),
  };
  return { elements, documentRef };
}

FakeElement.prototype.markFragment = function markFragment() { this.isFragment = true; return this; };

export { FakeElement, makeDom };
