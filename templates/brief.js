// page niceties: done boxes, folds, the now marker. storage can throw (private mode, blocked), so every touch is wrapped
(function () {
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) {
      try { if (v === null) window.localStorage.removeItem(k); else window.localStorage.setItem(k, v); } catch (e) {}
    }
  };

  // next actions remember their ticks per day
  Array.prototype.forEach.call(document.querySelectorAll('input.done-box'), function (box) {
    var key = 'brief:done:' + box.getAttribute('data-key');
    var row = box.closest('li');
    box.checked = store.get(key) === '1';
    row.classList.toggle('is-done', box.checked);
    box.addEventListener('change', function () {
      row.classList.toggle('is-done', box.checked);
      store.set(key, box.checked ? '1' : null);
    });
  });

  // folds: remembered per section; some start shut on a phone. print css ignores them
  var phone = window.matchMedia && window.matchMedia('(max-width: 600px)').matches;
  function fold(sec, shut, save) {
    var btn = sec.querySelector('.chev');
    sec.classList.toggle('folded', shut);
    btn.setAttribute('aria-expanded', shut ? 'false' : 'true');
    if (save) store.set('brief:fold:' + sec.getAttribute('data-fold'), shut ? 'closed' : 'open');
  }
  Array.prototype.forEach.call(document.querySelectorAll('section[data-fold]'), function (sec) {
    var btn = sec.querySelector('.chev');
    var saved = store.get('brief:fold:' + sec.getAttribute('data-fold'));
    btn.hidden = false;
    fold(sec, saved ? saved === 'closed' : phone && sec.hasAttribute('data-fold-phone'), false);
    sec.querySelector('.sec-head').addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      fold(sec, !sec.classList.contains('folded'), true);
    });
  });

  // contents links open a folded section before jumping to it
  Array.prototype.forEach.call(document.querySelectorAll('.contents a'), function (a) {
    a.addEventListener('click', function () {
      var t = document.querySelector(a.getAttribute('href') + '.folded');
      if (t) fold(t, false, false);
    });
  });

  // the desktop rail marks the section being read
  var links = {};
  Array.prototype.forEach.call(document.querySelectorAll('.rail .contents a'), function (a) { links[a.getAttribute('href').slice(1)] = a; });
  if (window.IntersectionObserver) {
    var seen = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting || !links[e.target.id]) return;
        Object.keys(links).forEach(function (k) { links[k].removeAttribute('aria-current'); });
        links[e.target.id].setAttribute('aria-current', 'true');
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    Object.keys(links).forEach(function (k) { var t = document.getElementById(k); if (t) seen.observe(t); });
  }

  // a live "now" line on the ribbon, only on the brief's own date in the configured zone.
  // data-now freezes the clock for demos and screenshots
  var rb = document.querySelector('.ribbon[data-date]');
  if (!rb || !window.Intl) return;
  var mark = rb.querySelector('.rb-now');
  var lo = +rb.getAttribute('data-lo'), hi = +rb.getAttribute('data-hi');
  var zone = rb.getAttribute('data-tz') || undefined;
  var frozen = (rb.getAttribute('data-now') || '').match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  function tick() {
    var parts = {};
    if (frozen) {
      parts = { date: frozen[1], hour: frozen[2], minute: frozen[3] };
    } else {
      try {
        new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
          hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
      } catch (e) { return; }
      parts.date = parts.year + '-' + parts.month + '-' + parts.day;
    }
    var m = (+parts.hour) * 60 + (+parts.minute);
    var on = parts.date === rb.getAttribute('data-date') && m >= lo && m <= hi;
    mark.hidden = !on;
    if (on) mark.style.left = ((m - lo) / (hi - lo) * 100).toFixed(2) + '%';
  }
  tick();
  setInterval(tick, 60000);
})();
