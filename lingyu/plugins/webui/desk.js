(function () {
  var root = document.documentElement;
  document.querySelectorAll("[data-theme-set]").forEach(function (button) {
    button.addEventListener("click", function () {
      var mode = button.getAttribute("data-theme-set");
      if (mode === "system") root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", mode);
      document.querySelectorAll("[data-theme-set]").forEach(function (item) {
        item.setAttribute("aria-pressed", item === button ? "true" : "false");
      });
    });
  });

  var form = document.querySelector("form");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    var blocked = false;
    document.querySelectorAll("[data-json-editor]").forEach(function (editor) {
      var error = editor.querySelector(".json-error");
      if ((error && !error.hidden) || editor.querySelector(".bad")) blocked = true;
    });
    if (!blocked) return;
    event.preventDefault();
    var note = document.getElementById("form-error");
    if (!note) return;
    note.hidden = false;
    note.textContent = "还有没写完的配置，这次没有提交。";
  });
})();
