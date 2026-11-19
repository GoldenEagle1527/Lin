(function () {
  var TYPES = [
    ["string", "字符串"],
    ["number", "数字"],
    ["boolean", "是否"],
    ["null", "空"],
    ["object", "对象"],
    ["array", "数组"]
  ];

  function kind(value) {
    if (value === null) return "null";
    if (Array.isArray(value)) return "array";
    return typeof value;
  }

  function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function partialNumber(text) {
    return text === "-" || text === "." || text === "-." || /^-?\d+\.$/.test(text);
  }

  function coerce(value, type) {
    if (type === "string") {
      if (value == null) return "";
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }
    if (type === "number") {
      if (typeof value === "number" && Number.isFinite(value)) return value;
      var number = Number(String(value == null ? "" : value).trim());
      return Number.isFinite(number) ? number : 0;
    }
    if (type === "boolean") return value === true || value === 1;
    if (type === "null") return null;
    if (type === "object") return {};
    return [];
  }

  function uniqueKey(object, base) {
    var name = base;
    var index = 2;
    while (Object.prototype.hasOwnProperty.call(object, name)) {
      name = base + index;
      index += 1;
    }
    return name;
  }

  function rename(object, from, to) {
    var next = {};
    Object.keys(object).forEach(function (key) {
      next[key === from ? to : key] = object[key];
    });
    Object.keys(object).forEach(function (key) { delete object[key]; });
    Object.keys(next).forEach(function (key) { object[key] = next[key]; });
  }

  function Editor(root, value) {
    this.root = root;
    this.value = value;
    this.view = el("div", "json-view");
    this.error = el("p", "json-error");
    this.error.hidden = true;
    this.area = el("textarea", "json-src");
    this.area.hidden = true;
    this.area.spellcheck = false;
    this.area.setAttribute("aria-label", "JSON 源码");
    var toggle = el("button", "json-src-toggle", "JSON");
    toggle.type = "button";
    var source = el("div", "json-source");
    var self = this;
    toggle.addEventListener("click", function () {
      self.area.hidden = !self.area.hidden;
      if (!self.area.hidden) {
        self.area.value = JSON.stringify(self.value, null, 2);
        self.area.focus();
      }
    });
    this.area.addEventListener("input", function () {
      try {
        self.value = JSON.parse(self.area.value);
      } catch (err) {
        self.error.hidden = false;
        self.error.textContent = "不是合法 JSON";
        return;
      }
      self.error.hidden = true;
      self.store();
      self.draw();
    });
    source.appendChild(toggle);
    source.appendChild(this.area);
    source.appendChild(this.error);
    root.appendChild(this.view);
    root.appendChild(source);
    this.draw();
  }

  Editor.prototype.store = function () {
    var field = this.root.querySelector("textarea.json-field");
    if (!field) return;
    field.value = JSON.stringify(this.value, null, 2);
  };

  Editor.prototype.touch = function (redraw, focusKey) {
    if (focusKey) this.pendingFocus = focusKey;
    this.store();
    if (!this.area.hidden) this.area.value = JSON.stringify(this.value, null, 2);
    if (redraw) this.draw();
  };

  Editor.prototype.draw = function () {
    var self = this;
    var focusKey = this.pendingFocus || "";
    this.pendingFocus = "";
    this.view.textContent = "";
    if (!isPlainObject(this.value)) {
      this.view.appendChild(el("p", "json-note", "配置必须是对象。"));
      var fix = el("button", "json-make-object", "改成空对象");
      fix.type = "button";
      fix.addEventListener("click", function () {
        self.value = {};
        self.touch(true);
      });
      this.view.appendChild(fix);
      return;
    }
    this.view.appendChild(renderObject(this.value, function (redraw, nextFocus) {
      self.touch(redraw, nextFocus);
    }, true, focusKey));
    var fresh = this.view.querySelector("[data-fresh='1']");
    if (fresh) {
      fresh.focus();
      if (fresh.select) fresh.select();
    }
  };

  function renderObject(object, changed, isRoot, focusKey) {
    var box = el("div", "json-node");
    var keys = Object.keys(object);
    if (!keys.length) box.appendChild(el("p", "json-empty", "没有字段"));
    keys.forEach(function (key) {
      box.appendChild(renderField(object, key, changed, key === focusKey, focusKey));
    });
    var add = el("button", "json-add", "添加字段");
    add.type = "button";
    add.addEventListener("click", function () {
      var name = uniqueKey(object, "字段");
      object[name] = "";
      changed(true, name);
    });
    box.appendChild(add);
    return box;
  }

  function renderArray(list, changed, focusKey) {
    var box = el("div", "json-node");
    if (!list.length) box.appendChild(el("p", "json-empty", "没有项"));
    list.forEach(function (_item, index) {
      box.appendChild(renderItem(list, index, changed, focusKey));
    });
    var add = el("button", "json-add", "添加一项");
    add.type = "button";
    add.addEventListener("click", function () {
      list.push("");
      changed(true);
    });
    box.appendChild(add);
    return box;
  }

  function renderField(object, key, changed, fresh, focusKey) {
    var slot = { key: key, fresh: fresh };
    return renderEntry(
      function () { return object[slot.key]; },
      function (next, redraw) {
        object[slot.key] = next;
        changed(redraw);
      },
      function () {
        delete object[slot.key];
        changed(true);
      },
      slot,
      object,
      changed,
      focusKey
    );
  }

  function renderItem(list, index, changed, focusKey) {
    var row = document.createElement("div");
    var line = el("div", "json-row");
    line.appendChild(el("span", "json-index", String(index)));
    line.appendChild(typeSelect(function () { return list[index]; }, function (next, redraw) {
      list[index] = next;
      changed(redraw);
    }));
    var valueCell = el("div", "json-val");
    fillValue(valueCell, list[index], function (next, redraw) {
      list[index] = next;
      changed(redraw);
    }, changed);
    line.appendChild(valueCell);
    var remove = el("button", "json-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "删除这项");
    remove.addEventListener("click", function () {
      list.splice(index, 1);
      changed(true);
    });
    line.appendChild(remove);
    row.appendChild(line);
    var current = list[index];
    if (isPlainObject(current) || Array.isArray(current)) {
      var children = el("div", "json-children");
      children.appendChild(isPlainObject(current) ? renderObject(current, changed, false, focusKey) : renderArray(current, changed, focusKey));
      row.appendChild(children);
    }
    return row;
  }

  function renderEntry(get, set, removeValue, slot, object, changed, focusKey) {
    var row = document.createElement("div");
    var line = el("div", "json-row");
    var keyInput = el("input", "json-key");
    keyInput.type = "text";
    keyInput.value = slot.key;
    keyInput.setAttribute("aria-label", "字段名");
    keyInput.autocomplete = "off";
    keyInput.spellcheck = false;
    if (slot.fresh) keyInput.dataset.fresh = "1";
    keyInput.addEventListener("input", function () {
      var next = keyInput.value;
      var bad = next === "" || (next !== slot.key && Object.prototype.hasOwnProperty.call(object, next));
      keyInput.classList.toggle("bad", bad);
      if (!bad && next !== slot.key) {
        rename(object, slot.key, next);
        slot.key = next;
        changed(false);
      }
    });
    keyInput.addEventListener("blur", function () {
      var next = keyInput.value;
      if (next === slot.key) {
        keyInput.classList.remove("bad");
        return;
      }
      if (next === "" || Object.prototype.hasOwnProperty.call(object, next)) {
        keyInput.value = slot.key;
        keyInput.classList.remove("bad");
        return;
      }
      rename(object, slot.key, next);
      slot.key = next;
      changed(false);
    });
    line.appendChild(keyInput);
    line.appendChild(typeSelect(get, set));
    var valueCell = el("div", "json-val");
    fillValue(valueCell, get(), set, changed);
    line.appendChild(valueCell);
    var remove = el("button", "json-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "删除字段");
    remove.addEventListener("click", removeValue);
    line.appendChild(remove);
    row.appendChild(line);
    var current = get();
    if (isPlainObject(current) || Array.isArray(current)) {
      var children = el("div", "json-children");
      children.appendChild(isPlainObject(current) ? renderObject(current, changed, false, focusKey) : renderArray(current, changed, focusKey));
      row.appendChild(children);
    }
    return row;
  }

  function typeSelect(get, set) {
    var select = el("select", "json-type");
    select.setAttribute("aria-label", "类型");
    TYPES.forEach(function (item) {
      var option = el("option", "", item[1]);
      option.value = item[0];
      select.appendChild(option);
    });
    select.value = kind(get());
    select.addEventListener("change", function () {
      set(coerce(get(), select.value), true);
    });
    return select;
  }

  function fillValue(cell, value, set, changed) {
    var type = kind(value);
    if (type === "string" || type === "number") {
      var input = el("input", "json-value");
      input.type = "text";
      input.value = value == null ? "" : String(value);
      input.setAttribute("aria-label", "值");
      input.autocomplete = "off";
      input.spellcheck = false;
      if (type === "number") input.inputMode = "decimal";
      var good = value;
      input.addEventListener("input", function () {
        if (type === "string") {
          set(input.value, false);
          return;
        }
        var text = input.value.trim();
        if (text !== "" && !partialNumber(text) && Number.isFinite(Number(text))) {
          input.classList.remove("bad");
          good = Number(text);
          set(good, false);
          return;
        }
        input.classList.add("bad");
      });
      input.addEventListener("blur", function () {
        if (!input.classList.contains("bad")) return;
        input.value = String(good);
        input.classList.remove("bad");
      });
      cell.appendChild(input);
      return;
    }
    if (type === "boolean") {
      var group = el("div", "json-bool");
      [["true", "是", true], ["false", "否", false]].forEach(function (item) {
        var button = el("button", value === item[2] ? "on" : "", item[1]);
        button.type = "button";
        button.setAttribute("aria-pressed", value === item[2] ? "true" : "false");
        button.addEventListener("click", function () {
          set(item[2], true);
        });
        group.appendChild(button);
      });
      cell.appendChild(group);
      return;
    }
    if (type === "null") {
      cell.appendChild(el("span", "json-meta", "空值"));
      return;
    }
    var count = type === "array" ? value.length : Object.keys(value).length;
    cell.appendChild(el("span", "json-meta", count + " 项"));
  }

  function mount(root) {
    var field = root.querySelector("textarea.json-field");
    var text = field ? field.value : "{}";
    try {
      new Editor(root, JSON.parse(text));
    } catch (err) {
      var editor = new Editor(root, {});
      editor.area.hidden = false;
      editor.area.value = text;
      editor.error.hidden = false;
      editor.error.textContent = "不是合法 JSON";
    }
  }

  document.querySelectorAll("[data-json-editor]").forEach(mount);
})();
