/* Smart Campus Service Desk: small progressive-enhancement helpers.
   Nothing here is required for the site to work; it only makes it nicer. */
(function () {
  'use strict';

  var $ = function (selector, root) { return (root || document).querySelector(selector); };
  var $$ = function (selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); };

  /* ---- Mobile navigation drawer ------------------------------------------ */
  var menuButton = $('#menu-btn');
  var scrim = $('#scrim');

  function setDrawer(open) {
    document.body.classList.toggle('nav-open', open);
    if (menuButton) {
      menuButton.setAttribute('aria-expanded', open ? 'true' : 'false');
      menuButton.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    }
  }

  if (menuButton) {
    menuButton.addEventListener('click', function () {
      setDrawer(!document.body.classList.contains('nav-open'));
    });
  }
  if (scrim) {
    scrim.addEventListener('click', function () { setDrawer(false); });
  }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { setDrawer(false); }
  });

  /* ---- Flash messages ----------------------------------------------------- */
  $$('.flash').forEach(function (flash) {
    var close = $('.flash-close', flash);
    if (close) {
      close.addEventListener('click', function () { flash.remove(); });
    }
    if (flash.classList.contains('flash-success')) {
      window.setTimeout(function () { flash.remove(); }, 7000);
    }
  });

  /* ---- Confirm before destructive actions --------------------------------- */
  $$('[data-confirm]').forEach(function (element) {
    element.addEventListener('submit', function (event) {
      if (!window.confirm(element.getAttribute('data-confirm'))) {
        event.preventDefault();
      }
    });
  });

  /* ---- Live character counter for textareas ------------------------------- */
  $$('[data-counter]').forEach(function (field) {
    var output = document.getElementById(field.getAttribute('data-counter'));
    if (!output) { return; }
    var update = function () { output.textContent = field.value.length; };
    field.addEventListener('input', update);
    update();
  });

  /* ---- Image preview before upload ---------------------------------------- */
  $$('input[type="file"][data-preview]').forEach(function (input) {
    var preview = document.getElementById(input.getAttribute('data-preview'));
    if (!preview) { return; }
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) { preview.hidden = true; return; }
      if (file.size > 5 * 1024 * 1024) {
        window.alert('That photo is larger than 5 MB. Please choose a smaller one.');
        input.value = '';
        preview.hidden = true;
        return;
      }
      preview.src = URL.createObjectURL(file);
      preview.hidden = false;
    });
  });

  /* ---- Show / hide password ----------------------------------------------- */
  $$('[data-toggle-password]').forEach(function (button) {
    var input = document.getElementById(button.getAttribute('data-toggle-password'));
    if (!input) { return; }
    button.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });

  /* ---- Print button on the reports page ----------------------------------- */
  $$('[data-print]').forEach(function (button) {
    button.addEventListener('click', function () { window.print(); });
  });

  /* ---- Keep the unread-notification badge fresh ---------------------------- */
  var sidebar = $('#sidebar');
  var unreadUrl = sidebar && sidebar.getAttribute('data-unread-url');
  if (unreadUrl && window.fetch) {
    var badges = $$('.js-unread');
    var dots = $$('.js-unread-dot');

    var refresh = function () {
      if (document.hidden) { return; }
      fetch(unreadUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (response) { return response.ok ? response.json() : null; })
        .then(function (data) {
          if (!data) { return; }
          badges.forEach(function (badge) { badge.textContent = data.count; badge.hidden = !data.count; });
          dots.forEach(function (dot) { dot.hidden = !data.count; });
        })
        .catch(function () { /* offline: try again next time */ });
    };

    window.setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
  }
})();


 /* ---- Experience layer: theme, command palette, copy helpers ------------- */
 (function () {
   'use strict';

   var root = document.documentElement;
   var themeButton = document.getElementById('theme-btn');
   var savedTheme = null;
   try { savedTheme = localStorage.getItem('smart-campus-theme'); } catch (e) {}
   if (savedTheme === 'dark' || savedTheme === 'light') root.setAttribute('data-theme', savedTheme);

   function setTheme(theme) {
     root.setAttribute('data-theme', theme);
     try { localStorage.setItem('smart-campus-theme', theme); } catch (e) {}
     if (themeButton) themeButton.title = theme === 'dark' ? 'Use light mode' : 'Use dark mode';
   }
   if (themeButton) {
     themeButton.addEventListener('click', function () {
       setTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
     });
     themeButton.title = root.getAttribute('data-theme') === 'dark' ? 'Use light mode' : 'Use dark mode';
   }

   var palette = document.getElementById('command-palette');
   var paletteInput = document.getElementById('palette-input');
   var paletteList = document.getElementById('palette-list');
   var paletteItems = paletteList ? Array.prototype.slice.call(paletteList.querySelectorAll('a')) : [];

   function closePalette() {
     if (!palette) return;
     palette.hidden = true;
     document.body.classList.remove('palette-open');
   }
   function openPalette() {
     if (!palette) return;
     palette.hidden = false;
     if (paletteInput) {
       paletteInput.value = '';
       paletteInput.focus();
     }
     paletteItems.forEach(function (item) { item.hidden = false; });
   }
   function filterPalette() {
     var q = (paletteInput.value || '').toLowerCase().trim();
     paletteItems.forEach(function (item) {
       item.hidden = q && item.getAttribute('data-command').indexOf(q) === -1;
     });
   }
   if (palette) {
     document.querySelectorAll('[data-palette-close]').forEach(function (el) {
       el.addEventListener('click', closePalette);
     });
     if (paletteInput) paletteInput.addEventListener('input', filterPalette);
   }

   document.addEventListener('keydown', function (event) {
     var tag = (event.target && event.target.tagName || '').toLowerCase();
     var typing = tag === 'input' || tag === 'textarea' || tag === 'select' || event.target.isContentEditable;
     if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
       event.preventDefault();
       openPalette();
       return;
     }
     if (event.key === 'Escape' && palette && !palette.hidden) closePalette();
     if (!typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
       var shortcuts = { n: '/requests/new', m: '/requests', b: '/notifications', p: '/profile' };
       var target = shortcuts[event.key.toLowerCase()];
       if (target) window.location.href = target;
     }
   });

   /* Add lightweight copy-to-clipboard behavior to any [data-copy] element. */
   document.querySelectorAll('[data-copy]').forEach(function (button) {
     button.addEventListener('click', function () {
       var value = button.getAttribute('data-copy') || '';
       if (!navigator.clipboard) return;
       navigator.clipboard.writeText(value).then(function () {
         var original = button.getAttribute('aria-label') || button.textContent;
         button.setAttribute('aria-label', 'Copied');
         button.classList.add('copied');
         window.setTimeout(function () {
           button.setAttribute('aria-label', original);
           button.classList.remove('copied');
         }, 1400);
       });
     });
   });

   /* Give external links and long tables a little more resilience. */
   document.querySelectorAll('a[target="_blank"]').forEach(function (link) {
     link.setAttribute('rel', 'noopener noreferrer');
   });

   /* Lazy-load images without changing the server-rendered experience. */
   document.querySelectorAll('img:not([loading])').forEach(function (image) {
     image.loading = 'lazy';
   });
 }());


 /* ---- Optional PWA shell -------------------------------------------------- */
 if ('serviceWorker' in navigator && window.isSecureContext) {
   window.addEventListener('load', function () {
     navigator.serviceWorker.register('/static/sw.js').catch(function () {});
   });
 }
