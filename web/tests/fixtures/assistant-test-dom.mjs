// Small synthetic DOM for controller interaction tests, not a browser renderer.
export function testDom() {
  const htmlWrites = [];
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.attributes = new Map();
      this.dataset = {}; this.events = new Map(); this.checked = false;
      this.disabled = false; this.hidden = false; this.open = false; this._text = "";
    }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
    set textContent(text) { this.children = []; this._text = String(text); }
    get value() {
      if (this.tagName === "SELECT") return this.children.find(child => child.tagName === "OPTION" && child.value === this._value)?.value
        ?? this.children.find(child => child.tagName === "OPTION")?.value ?? "";
      return this._value ?? (this.tagName === "OPTION" ? this.textContent : "");
    }
    set value(value) { this._value = String(value); }
    setAttribute(key, value) {
      this.attributes.set(key, String(value));
      if (["id", "name", "class", "value"].includes(key)) this[key === "class" ? "className" : key] = String(value);
      if (["checked", "disabled", "hidden"].includes(key)) this[key] = true;
      if (key.startsWith("data-")) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = String(value);
    }
    hasAttribute(key) {
      if (key.startsWith("data-")) return Object.hasOwn(this.dataset, key.slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase()));
      return this.attributes.has(key);
    }
    matches(selector) {
      if (selector.startsWith("#")) return this.id === selector.slice(1);
      const attr = selector.match(/^\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]$/);
      if (attr) return attr[2] === undefined ? this.hasAttribute(attr[1]) : String(this[attr[1]] ?? this.attributes.get(attr[1])) === attr[2];
      return this.tagName === selector.toUpperCase();
    }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
    prepend(child) { child.parentElement = this; this.children.unshift(child); }
    replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
    addEventListener(type, listener) { this.events.set(type, [...(this.events.get(type) || []), listener]); }
    async fire(type, { force = false, ...props } = {}) {
      if (type === "click" && this.disabled && !force) return;
      const event = { target: this, currentTarget: this, preventDefault() {}, ...props };
      await Promise.all([this[`on${type}`], ...(this.events.get(type) || [])].filter(Boolean).map(listener => listener(event)));
    }
    showModal() { this.open = true; }
    close() { if (!this.open) return; this.open = false; return this.fire("close"); }
    getBoundingClientRect() { return { left: 10, right: 100, top: 10, bottom: 100 }; }
    set innerHTML(html) {
      htmlWrites.push(html); this.replaceChildren(); const stack = [this];
      for (const [token] of html.matchAll(/<\/?[^>]+>|[^<]+/g)) {
        if (token.startsWith("</")) { stack.pop(); continue; }
        if (!token.startsWith("<")) { stack.at(-1)._text += token; continue; }
        const tag = token.match(/^<([\w-]+)/)?.[1];
        if (!tag) continue;
        const element = new Element(tag);
        for (const [, key, value = ""] of token.slice(tag.length + 1, -1).matchAll(/([\w-]+)(?:="([^"]*)")?/g)) element.setAttribute(key, value);
        stack.at(-1).append(element);
        if (!["input", "br", "img", "hr"].includes(tag)) stack.push(element);
      }
    }
  }
  Element.prototype.before = function (...nodes) {
    const siblings = this.parentElement.children, index = siblings.indexOf(this);
    for (const node of nodes) node.parentElement = this.parentElement;
    siblings.splice(index, 0, ...nodes);
  };
  const body = new Element("body"), host = new Element("form");
  body.append(host);
  const document = {
    body, createElement: tag => new Element(tag),
    querySelector: selector => selector === "#assistantOperationsDialog [data-agent-local]" ? host : body.querySelector(selector),
    getElementById: id => body.querySelector(`#${id}`),
  };
  return { Element, document, htmlWrites };
}
