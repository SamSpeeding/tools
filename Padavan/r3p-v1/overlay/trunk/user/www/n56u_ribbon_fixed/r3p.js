(function () {
  'use strict';
  var sections = ['network', 'apps', 'system'];
  var ap = document.getElementById('r3p-mode').textContent.trim() === '3';
  var labels = {PROXY: '代理节点', ADS: '广告过滤', GOOGLE: 'Google', YOUTUBE: 'YouTube', FINAL: '其他流量'};
  var app = document.getElementById('apps');
  var errorBox = document.getElementById('request-error');
  var dav = document.querySelector('[data-action="dav-save"]');
  var rules = document.querySelector('[data-action="rules-save"]');
  var settingsLoaded = false;
  var rulesLoaded = false;
  var updating = false;
  var waiting = false;
  var groupKey = '';

  function showSection() {
    var name = location.hash.slice(1);
    if (sections.indexOf(name) < 0) name = 'network';
    sections.forEach(function (id) {
      document.getElementById(id).hidden = id !== name;
      var link = document.querySelector('[data-section="' + id + '"]');
      if (id === name) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (name === 'apps') poll();
  }

  document.getElementById('mode-info').textContent = ap
    ? 'AP 模式下，客户端的上网地址和网关由主路由分配。'
    : '修改 Wi-Fi、LAN 地址或工作模式后，请使用新地址或重新连接 Wi-Fi。';
  if (ap) {
    document.getElementById('lan-link').href = '/Advanced_APLAN_Content.asp';
    document.querySelectorAll('[data-router]').forEach(function (el) { el.hidden = true; });
  }

  function request(form) {
    return fetch('/r3p-service.cgi', {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {'X-R3P-Request': '1', 'Content-Type': 'application/x-www-form-urlencoded'},
      body: form.toString()
    }).then(function (resp) {
      if (!resp.ok) throw new Error('请求失败，请确认已从局域网登录后台。');
      return resp.json();
    }).then(function (data) {
      if (data.Error) throw new Error(data.Error);
      return data;
    });
  }

  function fields(form, name) {
    return form.elements.namedItem(name);
  }

  function render(s) {
    document.getElementById('proxy-state').textContent = s.ProxyRunning ? 'IPv4 和 IPv6 透明代理运行中'
      : s.ProxyEnabled ? '已启用，当前流量直连' : '代理已关闭，当前流量直连';
    document.getElementById('proxy-message').textContent = s.Busy ? '正在处理…' : (s.ProxyMessage || '');
    document.getElementById('dav-state').textContent = s.DAVRunning ? 'WebDAV 运行中' : s.DAVEnabled ? 'WebDAV 已启用，等待共享目录' : 'WebDAV 已关闭';
    document.getElementById('dav-message').textContent = s.DAVMessage || '';
    var link = document.getElementById('dav-url');
    link.textContent = s.DAVURL || '';
    link.href = s.DAVURL || '#';
    var params = document.querySelector('[data-action="proxy-save"]');
    fields(params, 'core').placeholder = s.CoreConfigured ? '已保存核心地址' : '';
    fields(params, 'sha256').placeholder = s.CorePinned ? '已保存校验值' : '';
    document.getElementById('clear-core-sha256').hidden = !s.CorePinned;
    fields(params, 'subscription').placeholder = s.SubscriptionConfigured ? '已保存订阅地址' : '';
    if (!settingsLoaded) {
      fields(dav, 'enabled').checked = s.DAVEnabled;
      fields(dav, 'readonly').checked = s.DAVReadOnly;
      fields(dav, 'port').value = s.DAVPort || 8082;
      fields(dav, 'path').value = s.DAVPath || '';
      fields(dav, 'user').value = s.DAVUser || '';
      settingsLoaded = true;
    }
    if (!rulesLoaded) {
      fields(rules, 'block').value = s.Block || '';
      fields(rules, 'allow').value = s.Allow || '';
      fields(rules, 'rules').value = s.Rules || '';
      fields(rules, 'bypass_clients').value = s.BypassClients || '';
      fields(rules, 'bypass_destinations').value = s.BypassDestinations || '';
      rulesLoaded = true;
    }
    var mounts = document.getElementById('dav-mounts');
    mounts.replaceChildren();
    (s.Mounts || []).forEach(function (mount) {
      var option = document.createElement('option');
      option.value = mount;
      mounts.appendChild(option);
    });
    var groups = s.Groups || {};
    var key = JSON.stringify(groups);
    if (key !== groupKey) {
      groupKey = key;
      var panel = document.getElementById('proxy-groups');
      panel.replaceChildren();
      Object.keys(labels).forEach(function (name) {
        var group = groups[name];
        if (!group) return;
        var label = document.createElement('label');
        label.textContent = labels[name];
        var select = document.createElement('select');
        group.all.forEach(function (optionName) {
          select.appendChild(new Option(optionName, optionName, false, optionName === group.now));
        });
        select.addEventListener('change', function () {
          send('proxy-select', null, {group: name, name: select.value});
        });
        label.appendChild(select);
        panel.appendChild(label);
      });
    }
    app.querySelectorAll('button, select').forEach(function (item) {
      item.disabled = s.Busy || waiting || (ap && ['proxy-on', 'proxy-refresh'].indexOf(item.dataset.action) >= 0);
    });
  }

  function poll() {
    if (app.hidden || updating || waiting) return;
    updating = true;
    request(new URLSearchParams({action: 'status'})).then(render).catch(function (err) {
      errorBox.textContent = err.message;
    }).finally(function () { updating = false; });
  }

  function send(action, form, extra) {
    if (waiting) return;
    waiting = true;
    errorBox.textContent = '';
    var data = new URLSearchParams(form ? new FormData(form) : undefined);
    data.set('action', action);
    if (extra) Object.keys(extra).forEach(function (key) { data.set(key, extra[key]); });
    request(data).then(function () {
      if (form === dav) fields(dav, 'password').value = '';
      if (action === 'proxy-save') form.reset();
    }).catch(function (err) {
      errorBox.textContent = err.message;
    }).finally(function () {
      waiting = false;
      poll();
    });
  }

  app.querySelectorAll('form[data-action]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      send(form.dataset.action, form);
    });
  });
  app.querySelectorAll('button[data-action]').forEach(function (button) {
    button.addEventListener('click', function () { send(button.dataset.action); });
  });
  window.addEventListener('hashchange', showSection);
  showSection();
  window.setInterval(poll, 3000);
})();
