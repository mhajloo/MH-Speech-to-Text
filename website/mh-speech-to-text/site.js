// MH-Speech to Text download page: language switch (?lang=en|fa or the button),
// the recording-bar demo and the copy button for the installer's SHA-256.
// A separate file because the site's Content-Security-Policy (script-src 'self')
// blocks inline scripts.
(function () {
  var root = document.documentElement;
  var TEXT = {
    fa: {
      title: "MH-Speech to Text | دیکته‌ی فارسی در هر برنامه‌ای",
      desc: "کلید را نگه دارید، فارسی صحبت کنید و رها کنید؛ متن همان‌جایی نوشته می‌شود که مکان‌نما هست. رایگان، متن‌باز و کاملاً آفلاین، برای ویندوز.",
      listening: "در حال شنیدن…", listeningSub: "رها کنید تا نوشته شود",
      busy: "در حال نوشتن متن…", busySub: "چند لحظه صبر کنید",
      done: "متن درج شد", words: function (n) { return String(n).replace(/\d/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; }) + " کلمه"; },
      copied: "کپی شد"
    },
    en: {
      title: "MH-Speech to Text | Persian dictation for Windows",
      desc: "Hold a hotkey, speak Persian and release: your words are typed wherever the cursor is. Free, open source and fully offline, for Windows.",
      listening: "Listening…", listeningSub: "Release to insert the text",
      busy: "Writing text…", busySub: "Just a moment",
      done: "Text inserted", words: function (n) { return n + " words"; },
      copied: "Copied"
    }
  };
  var ui = "fa";

  function setLang(lang, save) {
    ui = lang === "en" ? "en" : "fa";
    root.setAttribute("data-ui", ui);
    root.lang = ui;
    root.dir = ui === "fa" ? "rtl" : "ltr";
    document.title = TEXT[ui].title;
    var d = document.querySelector('meta[name="description"]');
    if (d) d.setAttribute("content", TEXT[ui].desc);
    if (save) { try { localStorage.setItem("mhstt-lang", ui); } catch (e) {} }
    renderPill();
  }

  // live demo: the recording bar and the text it writes
  var pill = document.getElementById("pill"), title = document.getElementById("pill-title"),
      sub = document.getElementById("pill-sub"), out = document.getElementById("demo-text"),
      waves = document.getElementById("waves"), state = "idle", lastWords = 0;
  for (var i = 0; i < 20; i++) {
    var bar = document.createElement("i");
    bar.style.setProperty("--i", i);
    bar.style.setProperty("--d", (0.28 + Math.random() * 0.45).toFixed(2) + "s");
    bar.style.setProperty("--h", Math.round(10 + Math.random() * 24) + "px");
    waves.appendChild(bar);
  }
  var lines = [
    "سلام، جلسه‌ی فردا ساعت ۱۰ صبح برگزار می‌شود؛ لطفاً گزارش‌ها را تا امشب بفرستید.",
    "فایل‌ها رو برات می‌فرستم، یه نگاهی بنداز و نظرت رو بگو.",
    "این متن را با صدای خودم نوشتم، بدون اینکه دستم به کیبورد بخورد."
  ];
  function renderPill() {
    var t = TEXT[ui];
    pill.setAttribute("data-state", state);
    if (state === "listening") { title.textContent = t.listening; sub.textContent = t.listeningSub; }
    else if (state === "busy") { title.textContent = t.busy; sub.textContent = t.busySub; }
    else if (state === "done") { title.textContent = t.done; sub.textContent = t.words(lastWords); }
  }
  function set(s) { state = s; renderPill(); }
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    out.innerHTML = "<p>" + lines[0] + "</p>";
    lastWords = lines[0].split(/\s+/).length;
    set("done");
  } else {
    var n = 0;
    var cycle = function () {
      var line = lines[n % lines.length];
      if (n % lines.length === 0) out.innerHTML = "";
      set("listening");
      setTimeout(function () {
        set("busy");
        setTimeout(function () {
          var p = document.createElement("p");
          p.className = "fresh";
          p.textContent = line;
          out.appendChild(p);
          lastWords = line.split(/\s+/).length;
          set("done");
          setTimeout(function () { set("idle"); n++; setTimeout(cycle, 1100); }, 1900);
        }, 950);
      }, 2600);
    };
    setTimeout(cycle, 700);
  }

  document.getElementById("lang-toggle").addEventListener("click", function () {
    setLang(ui === "fa" ? "en" : "fa", true);
  });
  var copyBtn = document.getElementById("copy-sha"), copyLabel = copyBtn.innerHTML, copyTimer = 0;
  copyBtn.addEventListener("click", function () {
    var sha = document.getElementById("sha");
    var done = function () {
      copyBtn.textContent = TEXT[ui].copied;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(function () { copyBtn.innerHTML = copyLabel; }, 1500);
    };
    var select = function () {  // no clipboard access: select it for Ctrl+C
      var r = document.createRange(), s = window.getSelection();
      r.selectNodeContents(sha); s.removeAllRanges(); s.addRange(r);
    };
    if (navigator.clipboard) { navigator.clipboard.writeText(sha.textContent.trim()).then(done, select); }
    else { select(); }
  });

  var q = (location.search.match(/[?&]lang=(fa|en)/) || [])[1], saved = null;
  try { saved = localStorage.getItem("mhstt-lang"); } catch (e) {}
  setLang(q || saved || "fa", false);
})();
