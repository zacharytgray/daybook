// fleet: the machines, services as a strip of squares with the problems spelled out, sessions per host
(function () {
  'use strict';
  var ZB = window.Board, h = ZB.h, I = ZB.icon;
  var showAll = false;

  function svcRow(r) {
    return h('li', { class: 'svc ' + r.dot }, [h('span', { class: 'sdot ' + r.dot, 'aria-hidden': 'true' }),
      h('div', { class: 'svc-b' }, [h('p', { class: 'mono', text: r.label }),
        r.note || r.open_issues && r.dot !== 'good' ? h('p', { class: 'small muted', text: r.note || r.open_issues + ' open issue' +
          (r.open_issues === 1 ? '' : 's') }) : null]),
      h('span', { class: 'svc-v', text: r.verdict })]);
  }

  // up is true, false, or null when nobody checked
  function state(m) { return m.up === true ? ['good', 'up'] : m.up === false ? ['bad', 'down'] : ['idle', 'not checked']; }

  function render(el, d) {
    var sv = d.services || {}, devs = d.devices || [];
    var up = devs.filter(function (m) { return m.up === true; }).length;
    var checked = devs.filter(function (m) { return m.up !== null && m.up !== undefined; }).length;
    var sum = [];
    if (devs.length) {
      sum.push(!checked ? devs.length + ' machine' + (devs.length === 1 ? '' : 's') + ', not checked'
        : up === devs.length ? devs.length + ' machines up' : up + ' of ' + devs.length + ' machines up');
    }
    if (!sv.error && !sv.off) {
      if (sv.drift) sum.push(sv.drift + ' service' + (sv.drift === 1 ? '' : 's') + ' drifting');
      if (sv.down) sum.push(sv.down + ' down');
    }
    if (!sum.length) sum.push('Nothing to watch yet');
    el.appendChild(h('div', { class: 'room-head', 'data-room': 'fleet' }, [h('p', { class: 'room-title', text: 'Fleet' }),
      h('p', { class: 'room-sub', text: sum.join(', ') + '.' })]));
    var sec = ZB.tile('fleet', 'Fleet', { room: 'fleet', aside: sum.join(', ') });

    if (devs.length) {
      sec.appendChild(h('ul', { class: 'machines', 'aria-label': 'Machines' }, devs.map(function (m) {
        var st = state(m);
        return h('li', { class: 'machine' }, [
          h('div', { class: 'm-top' }, [h('span', { class: 'm-role', text: m.role }),
            h('span', { class: 'm-st ' + st[0] }, [h('span', { class: 'sdot ' + st[0], 'aria-hidden': 'true' }), st[1]])]),
          h('p', { class: 'mono strong m-host', text: m.hostname }),
          h('p', { class: 'mono muted m-ip', text: m.ip }),
          h('p', { class: 'm-sess', text: m.sessions ? m.sessions + ' session' + (m.sessions === 1 ? '' : 's') : 'No sessions' })]);
      })));
    } else {
      sec.appendChild(h('p', { class: 'quiet', text: 'No device registry is set.' }));
    }

    var head = h('div', { class: 'svc-head' }, [h('h3', { class: 'label', text: 'Services' })]);
    sec.appendChild(head);
    if (sv.error) {
      sec.appendChild(h('p', { class: 'unavail', text: 'unavailable: ' + sv.error }));
    } else if (sv.off) {
      sec.appendChild(h('p', { class: 'quiet', text: 'No services file or command is set.' }));
    } else {
      head.appendChild(h('p', { class: 'svc-counts' }, [['ok', sv.ok, ''], ['drift', sv.drift, 'warn'], ['down', sv.down, 'bad']].map(function (p) {
        return h('span', { class: 'svc-c' + (p[1] ? ' ' + p[2] : '') }, [h('b', { text: String(p[1] || 0) }), ' ' + p[0]]);
      })));
      var rows = sv.rows || [];
      // the squares are a picture; the rows below are the readable list
      sec.appendChild(h('div', { class: 'squares', 'aria-hidden': 'true' }, rows.map(function (r) {
        return h('span', { class: 'sq ' + r.dot, title: r.label + ', ' + r.verdict });
      })));
      var bad = rows.filter(function (r) { return r.dot !== 'good'; });
      var list = showAll ? rows : bad;
      if (list.length) sec.appendChild(h('ul', { class: 'svcs', id: 'svc-list' }, list.map(svcRow)));
      else sec.appendChild(h('p', { class: 'quiet', text: 'Every service reports ok.' }));
      if (rows.length > bad.length) {
        sec.appendChild(h('button', { type: 'button', class: 'btn more', 'data-key': 'fleet-all', 'aria-expanded': showAll ? 'true' : 'false',
          'aria-controls': 'svc-list', onclick: function () { showAll = !showAll; ZB.redraw(); } },
        [showAll ? 'Show only problems' : 'Show all ' + rows.length + ' services', I('chev', showAll ? 'up' : '')]));
      }
    }
    el.appendChild(sec);
  }

  ZB.modules.fleet = { render: render };
})();
