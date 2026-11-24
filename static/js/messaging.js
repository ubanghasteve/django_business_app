/**
 * In-house messaging: conversation list, chat pane, send/fetch messages,
 * file upload, emoji picker, reply UI, online/offline. Real-time via WebSocket; polling fallback.
 */
(function () {
  'use strict';

  var C = window.MESSAGING_CONFIG || {};
  var POLL_INTERVAL_MS = 0;    /* Ajax-only – poll immediately after previous completes for instant delete sync */
  var POLL_INTERVAL_WHEN_WS_MS = 20;   /* Backup when WebSocket connected – instant catch-up if a WS message is missed */
  var PRESENCE_INTERVAL_MS = 5000;   /* Presence refresh so offline/online visible within ~5s */
  var TYPING_POLL_MS = 200;
  var CALL_POLL_MS = 1500;
  var lastMessageTimestamp = null;
  var currentConversationId = null;
  var onlineUserIds = [];
  var replyToMessageId = null;
  var replyToPreview = null;
  var pollTimer = null;
  var messagePollInFlight = false;
  var deletedPollTimer = null;
  var deletedPollInFlight = false;
  var lastDeletedCheckAt = null;
  var DELETED_POLL_MS = 50;
  var presenceTimer = null;
  var callPollTimer = null;
  var typingPollTimer = null;
  var messageWs = null;
  var messageWsConvId = null;
  var conversationSearchQuery = '';
  var currentConvDetail = null;
  var forbiddenMessageShown = false;
  var loadRetriedForConv = {};
  var listRefreshTimer = null;
  var backToBottomCheckTimer = null;
  var LIST_REFRESH_INTERVAL_MS = 40;   /* Refresh conversation list very frequently so new messages show super fast */
  var lastUnreadByConv = {};
  var scrollPosByConv = {};
  var conversationsLoadInFlight = false;
  var conversationsLoadRetryCount = 0;
  var lastSuccessfulConversationsHtml = null;
  var pendingSentContent = null;

  /* WhatsApp-style emoji modal: categories and data */
  var EMOJI_CATEGORIES = [
    { id: 'smileys', label: 'Smileys & People', icon: '😀' },
    { id: 'animals', label: 'Animals & Nature', icon: '🐶' },
    { id: 'food', label: 'Food & Drink', icon: '🍕' },
    { id: 'activities', label: 'Activities', icon: '⚽' },
    { id: 'travel', label: 'Travel & Places', icon: '✈️' },
    { id: 'objects', label: 'Objects', icon: '💡' },
    { id: 'symbols', label: 'Symbols', icon: '❤️' },
    { id: 'flags', label: 'Flags', icon: '🏳️' },
    { id: 'gif', label: 'GIF', icon: '🎬', special: true },
    { id: 'avatars', label: 'Avatars', icon: '👤', special: true }
  ];
  var EMOJI_DATA = {
    smileys: '😀 😃 😄 😁 😅 😂 🤣 🙂 🙃 😉 😊 😇 🥰 😍 🤩 😘 😗 ☺ 😚 😙 🥲 😋 😛 😜 🤪 😝 🤑 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 🤥 😌 😔 😪 🤤 😴 😷 🤒 🤕 🤢 🤮 🤧 🥵 🥶 🥴 😵 🤯 🤠 🥳 🥸 😎 🤓 🧐 😕 😟 🙁 ☹ 😮 😯 😲 😳 🥺 😦 😧 😨 😰 😥 😢 😭 😱 😖 😣 😞 😓 😩 😫 🥱 😤 😡 😠 🤬 😈 💀 ☠ 💩 🤡 👻 👽 👾 🤖 😺 😸 😹 😻 😼 😽 🙀 😿 😾 👋 🤚 🖐 ✋ 🖖 👌 🤌 🤏 ✌ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💪 🤳 👂 👃 👀 🧠 💋 👄 🦷 👅'.split(' '),
    animals: '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🙈 🙉 🙊 🐒 🐔 🐧 🐦 🐤 🐣 🐥 🦆 🦅 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🐛 🦋 🐌 🐞 🐜 🦟 🦗 🕷 🦂 🐢 🐍 🦎 🦖 🦕 🐙 🦑 🦐 🦞 🦀 🐡 🐠 🐟 🐬 🐳 🐋 🦈 🐊 🌵 🎄 🌲 🌳 🌴 🍀 🍁 🍂 🍃 🌺 🌻 🌹 🥀 🌷 🌸 💐 🌼 🌷 🪷 🌱 🪴 🌿 ☘️ 🍀 🍄 🐚 🪨 🌊'.split(' '),
    food: '🍇 🍈 🍉 🍊 🍋 🍌 🍍 🥭 🍎 🍏 🍐 🍑 🍒 🍓 🥝 🍅 🥥 🥑 🍆 🥔 🥕 🌽 🌶 🥒 🥬 🥦 🧄 🧅 🍄 🥜 🌰 🍞 🥐 🥖 🧀 🥚 🍳 🥞 🧇 🥓 🥩 🍗 🍖 🌭 🍔 🍟 🍕 🫓 🥪 🥙 🧆 🌮 🌯 🫔 🥗 🥘 🫕 🥫 🍝 🍜 🍲 🍛 🍣 🍱 🥟 🦪 🍤 🍙 🍚 🍘 🍥 🥠 🥮 🍢 🍡 🍧 🍨 🍦 🥧 🍰 🎂 🍮 🍭 🍬 🍫 🍿 🍩 🍪 🥛 🍼 🫖 ☕ 🍵 🧃 🥤 🍶 🍺 🍻 🥂 🍷 🥃 🍸 🍹 🧉 🍾 🥄'.split(' '),
    activities: '⚽ 🏀 🏈 ⚾ 🥎 🎾 🏐 🏉 🥏 🎱 🪀 🏓 🏸 🏒 🏑 🥍 🏏 🪃 🥅 ⛳ 🪁 🏹 🎣 🤿 🥊 🥋 🎽 🛹 🛼 🛷 ⛸ 🏂 🪂 🏋 🤼 🤸 ⛹ 🤺 🤾 🏌 🏇 🏊 ⛷ 🏄 🚣 🤽 🚴 🚵 🎪 🎭 🎨 🎬 🎤 🎧 🎼 🎹 🥁 🎷 🎺 🎸 🪕 🎻 🎲 ♟ 🎯 🎳 🎮 🎰 🧩 🎲'.split(' '),
    travel: '🚗 🚕 🚙 🚌 🚎 🏎 🚓 🚑 🚒 🚐 🛻 🚚 🚛 🚜 🏍 🛵 🚲 🛴 🚏 🛣 🛤 ⛽ 🚨 🚥 🚦 🛑 🚧 ⛓ ⛵ 🚤 🛳 🛥 🚢 ✈ 🛩 🛫 🛬 🪂 💺 🚁 🚟 🚠 🚡 🚔 🌋 🗻 🏕 🏖 🏜 🏝 🏔 🏗 🏘 🏚 🏠 🏡 🏢 🏣 🏤 🏥 🏦 🏨 🏩 🏪 🏫 🏬 🏭 🏯 🏰 💒 🗼 🗽 ⛪ 🕌 🛕 🕍 ⛩ 🕋 ⛲ ⛺ 🌁 🌃 🏙 🌄 🌅 🌆 🌇 🌉 ♨ 🌌'.split(' '),
    objects: '⌚ 📱 📲 💻 ⌨ 🖥 🖨 🖱 🖲 🕹 🗜 💽 💾 💿 📀 📼 📷 📸 📹 🎥 📞 ☎ 📟 📠 📺 📻 🎙 🎚 🎛 ⏱ ⏲ ⏰ 🕰 ⏳ 🔮 📡 🔭 🕳 💊 💉 🩸 🩹 🩺 💈 ⚗ 🔬 🔭 📿 🧿 🕎 ✡ 🔯 🕌 ⛎ ♈ ♉ ♊ ♋ ♌ ♍ ♎ ♏ ♐ ♑ ♒ ♓ 📁 📂 🗂 📅 📆 🗒 🗓 📇 📈 📉 📊 📋 📌 📍 📎 🖇 📏 📐 ✂ 🗃 🗄 🗑 🔒 🔓 🔏 🔐 🔑 🗝 🔨 ⛏ 🪓 🛠 🗡 ⚔ 🛡 🔧 🔩 ⚙ 🗜 ⚖ 🔗 ⛓ 🧰'.split(' '),
    symbols: '❤ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 ❣ 💕 💞 💓 💗 💖 💘 💝 💟 ☮ ✝ ☪ 🕉 ☸ ✡ 🔯 🕎 ☯ ☦ 🛐 ⛎ ♈ ♉ ♊ ♋ ♌ ♍ ♎ ♏ ♐ ♑ ♒ ♓ ✅ ❌ ❓ ❗ ‼ ⁉ 💯 🔰 ⭕ 🚫 🚳 🚭 🚯 🚱 🚷 📵 🔞 🚸 ⚠ 🛑 🔴 🟠 🟡 🟢 🔵 🟣 🟤 ⚫ ⚪ 🟥 🟧 🟨 🟩 🟦 🟪 🟫 ⬛ ⬜ ◼ ◻ ◾ ◽ ▪ ▫ 🔶 🔷 🔸 🔹 🔺 🔻 💠 🔘 🔳 🔲 ➿ 〰 ✔ ✖ ➕ ➖ ➗ ✖ ♾ 💲 💱 ℹ 🔤 🔡 🔠 🔢 # * 0️⃣ 1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔟'.split(' '),
    flags: '🏳 🏴 🏁 🚩 🏳️‍🌈 🏴‍☠️ 🇦🇨 🇦🇩 🇦🇪 🇦🇫 🇦🇬 🇦🇮 🇦🇱 🇦🇱 🇦🇲 🇦🇳 🇦🇴 🇦🇶 🇦🇷 🇦🇸 🇦🇹 🇦🇺 🇦🇼 🇦🇽 🇦🇿 🇧🇦 🇧🇧 🇧🇩 🇧🇪 🇧🇫 🇧🇬 🇧🇭 🇧🇮 🇧🇯 🇧🇱 🇧🇲 🇧🇳 🇧🇴 🇧🇶 🇧🇷 🇧🇸 🇧🇹 🇧🇻 🇧🇼 🇧🇾 🇧🇿 🇨🇦 🇨🇨 🇨🇩 🇨🇫 🇨🇬 🇨🇭 🇨🇮 🇨🇰 🇨🇱 🇨🇲 🇨🇳 🇨🇴 🇨🇵 🇨🇷 🇨🇺 🇨🇻 🇨🇼 🇨🇽 🇨🇾 🇨🇿 🇩🇪 🇩🇬 🇩🇯 🇩🇰 🇩🇲 🇩🇴 🇪🇨 🇪🇪 🇪🇬 🇪🇷 🇪🇸 🇪🇹 🇪🇺 🇫🇮 🇫🇯 🇫🇰 🇫🇲 🇫🇴 🇫🇷 🇬🇦 🇬🇧 🇬🇩 🇬🇪 🇬🇫 🇬🇬 🇬🇭 🇬🇮 🇬🇲 🇬🇳 🇬🇵 🇬🇶 🇬🇷 🇬🇸 🇬🇹 🇬🇺 🇬🇼 🇬🇾 🇭🇰 🇭🇳 🇭🇷 🇭🇹 🇭🇺 🇮🇨 🇮🇩 🇮🇪 🇮🇱 🇮🇲 🇮🇳 🇮🇴 🇮🇶 🇮🇷 🇮🇸 🇮🇹 🇯🇪 🇯🇲 🇯🇴 🇯🇵 🇰🇪 🇰🇬 🇰🇭 🇰🇮 🇰🇲 🇰🇳 🇰🇵 🇰🇷 🇰🇼 🇰🇾 🇰🇿 🇱🇦 🇱🇧 🇱🇨 🇱🇮 🇱🇰 🇱🇷 🇱🇸 🇱🇹 🇱🇺 🇱🇻 🇱🇾 🇲🇦 🇲🇨 🇲🇩 🇲🇪 🇲🇫 🇲🇬 🇲🇭 🇲🇰 🇲🇱 🇲🇲 🇲🇳 🇲🇴 🇲🇵 🇲🇶 🇲🇷 🇲🇸 🇲🇹 🇲🇺 🇲🇻 🇲🇼 🇲🇽 🇲🇾 🇲🇿 🇳🇦 🇳🇨 🇳🇪 🇳🇫 🇳🇬 🇳🇮 🇳🇱 🇳🇴 🇳🇵 🇳🇷 🇳🇺 🇳🇿 🇴🇲 🇵🇦 🇵🇪 🇵🇫 🇵🇬 🇵🇭 🇵🇰 🇵🇱 🇵🇲 🇵🇳 🇵🇷 🇵🇸 🇵🇹 🇵🇼 🇵🇾 🇶🇦 🇷🇪 🇷🇴 🇷🇸 🇷🇺 🇷🇼 🇸🇦 🇸🇧 🇸🇨 🇸🇩 🇸🇪 🇸🇬 🇸🇭 🇸🇮 🇸🇯 🇸🇰 🇸🇱 🇸🇲 🇸🇳 🇸🇴 🇸🇷 🇸🇸 🇸🇹 🇸🇻 🇸🇾 🇸🇿 🇹🇦 🇹🇨 🇹🇩 🇹🇫 🇹🇬 🇹🇭 🇹🇯 🇹🇰 🇹🇱 🇹🇲 🇹🇳 🇹🇴 🇹🇷 🇹🇹 🇹🇻 🇹🇼 🇹🇿 🇺🇦 🇺🇬 🇺🇲 🇺🇳 🇺🇸 🇺🇾 🇺🇿 🇻🇦 🇻🇨 🇻🇪 🇻🇬 🇻🇮 🇻🇳 🇻🇺 🇼🇫 🇼🇸 🇽🇰 🇾🇪 🇾🇹 🇿🇦 🇿🇲 🇿🇼 🇬🇧 🇺🇸 🇨🇦 🇦🇺 🇯🇵 🇩🇪 🇫🇷 🇪🇸 🇮🇹 🇷🇺 🇨🇳 🇮🇳 🇧🇷'.split(' ')
  };

  function getCsrfToken() {
    // Prefer cookie - Django rotates it on login/session changes; page meta can be stale in multi-tab
    var fromCookie = getCookie('csrftoken');
    if (fromCookie && fromCookie.trim()) return fromCookie.trim();
    var meta = document.querySelector('meta[name="csrf-token"]');
    var fromMeta = meta && meta.getAttribute('content');
    if (fromMeta && fromMeta.trim()) return fromMeta.trim();
    var fromConfig = (typeof C !== 'undefined' && C && C.csrfToken) ? C.csrfToken : '';
    if (fromConfig && fromConfig.trim()) return fromConfig.trim();
    var fromForm = document.querySelector('[name=csrfmiddlewaretoken]');
    return (fromForm && fromForm.value) ? fromForm.value : '';
  }
  function getCookie(name) {
    var parts = document.cookie.split(';');
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].trim();
      var eq = part.indexOf('=');
      if (eq > 0 && part.slice(0, eq).trim() === name) {
        return part.slice(eq + 1).trim();
      }
    }
    return null;
  }

  function conversationApiUrl(baseUrl, conversationId) {
    if (!baseUrl || conversationId == null) return baseUrl;
    return baseUrl.replace(/\/conversations\/\d*\/?/, '/conversations/' + conversationId + '/');
  }

  function parseJsonResponse(r) {
    var ct = (r.headers && r.headers.get('content-type')) ? r.headers.get('content-type') : '';
    return r.text().then(function (text) {
      if (ct.indexOf('application/json') === -1) {
        var err = new Error('You no longer have access to this conversation.');
        err.status = r.status;
        throw err;
      }
      var data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch (e) {
        var err2 = new Error('You no longer have access to this conversation.');
        err2.status = r.status;
        throw err2;
      }
      if (r.status === 403) {
        var err3 = new Error(data.error || 'Forbidden');
        err3.status = 403;
        throw err3;
      }
      if (r.status === 404) {
        var err4 = new Error(data.error || 'Not found');
        err4.status = 404;
        throw err4;
      }
      if (r.status >= 400) {
        var err5 = new Error(data.error || 'Request failed');
        err5.status = r.status;
        throw err5;
      }
      return data;
    });
  }

  function apiGet(url, noCache) {
    var opts = {
      method: 'GET',
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    };
    if (noCache !== false) {
      opts.cache = 'no-store';
      opts.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
      opts.headers['Pragma'] = 'no-cache';
    }
    return fetch(url, opts).then(function (r) {
      return parseJsonResponse(r);
    });
  }
  function apiPost(url, body, contentType) {
    var opts = {
      method: 'POST',
      headers: {
        'X-CSRFToken': getCsrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
      },
      credentials: 'same-origin'
    };
    if (contentType === 'form') {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = typeof body === 'string' ? body : JSON.stringify(body || {});
    }
    return fetch(url, opts).then(function (r) {
      return parseJsonResponse(r);
    });
  }

  function showNewMessageToast(convId, name) {
    var container = document.getElementById('messagingToastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'messagingToastContainer';
      container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:1060;display:flex;flex-direction:column;gap:0.5rem;max-width:320px;';
      document.body.appendChild(container);
    }
    var toast = document.createElement('div');
    toast.style.cssText = 'background:var(--theme-primary-color,#1976d2);color:#fff;padding:0.75rem 1rem;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,.2);cursor:pointer;font-size:0.9rem;';
    toast.textContent = 'New message in ' + (name || 'Chat');
    toast.setAttribute('data-conv-id', String(convId));
    toast.addEventListener('click', function () {
      selectConversation(parseInt(this.getAttribute('data-conv-id'), 10));
      this.remove();
    });
    container.appendChild(toast);
    setTimeout(function () { if (toast.parentNode) toast.remove(); }, 5000);
  }

  function loadConversations(skipInFlightCheck) {
    var listEl = document.getElementById('conversationList');
    if (!listEl) return Promise.resolve();
    if (conversationsLoadInFlight && !skipInFlightCheck) return Promise.resolve();
    conversationsLoadInFlight = true;
    var url = C.apiConversations;
    if (conversationSearchQuery) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'q=' + encodeURIComponent(conversationSearchQuery);
    url += (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
    return apiGet(url).then(function (data) {
      conversationsLoadInFlight = false;
      conversationsLoadRetryCount = 0;
      var raw = data.conversations || [];
      var seenIds = {};
      var convos = [];
      for (var i = 0; i < raw.length; i++) {
        var c = raw[i];
        var id = c.id != null ? Number(c.id) : c.id;
        if (seenIds[id]) continue;
        seenIds[id] = true;
        convos.push(c);
      }
      var hadUnread = lastUnreadByConv;
      convos.forEach(function (c) {
        var prev = hadUnread[c.id];
        if (c.id !== currentConversationId && c.unread_count > 0 && prev != null && c.unread_count > prev) {
          showNewMessageToast(c.id, c.name || 'Chat');
        }
        lastUnreadByConv[c.id] = c.unread_count;
      });
      listEl.innerHTML = convos.length === 0
        ? (conversationSearchQuery
            ? '<div class="text-muted text-center py-4">No conversations match your search. Try different words or clear the search.</div>'
            : '<div class="text-muted text-center py-4">No conversations yet. Start a new chat.</div>')
        : convos.map(function (c) {
            var name = c.name || 'Chat';
            var initial = name.charAt(0).toUpperCase();
            var isLeft = c.left || c.can_rejoin;
            var isActive = !isLeft && currentConversationId === c.id ? ' active' : '';
            var online = (c.member_ids || []).some(function (id) { return id !== C.currentUserId && onlineUserIds.indexOf(id) >= 0; });
            var dot = online ? '<span class="online-dot"></span>' : '<span class="online-dot offline"></span>';
            var unreadBadge = (c.unread_count > 0) ? '<span class="unread-badge">' + (c.unread_count > 99 ? '99+' : c.unread_count) + '</span>' : '';
            var meta = isLeft ? 'You left · Click to rejoin' : (c.last_message_at ? 'Last activity' : '');
            return '<div class="messaging-list-item' + isActive + '" data-id="' + c.id + '"' + (isLeft ? ' data-left="1"' : '') + '>' +
              '<div class="avatar">' + initial + '</div>' +
              '<div class="flex-grow-1 min-w-0"><div class="name">' + escapeHtml(name) + unreadBadge + '</div><div class="meta">' + meta + '</div></div>' +
              dot + '</div>';
          }).join('');
      listEl.querySelectorAll('.messaging-list-item').forEach(function (el) {
        el.addEventListener('click', function () {
          var id = parseInt(el.getAttribute('data-id'), 10);
          if (el.getAttribute('data-left') === '1' && C.apiRejoin) {
            rejoinConversation(id);
            return;
          }
          selectConversation(id);
        });
      });
      lastSuccessfulConversationsHtml = listEl.innerHTML;
      return Promise.resolve();
    }).catch(function (err) {
      conversationsLoadInFlight = false;
      if (err && err.status === 403) {
        stopPolling();
        stopCallPolling();
        if (!forbiddenMessageShown && listEl) {
          listEl.innerHTML = '<div class="text-danger text-center py-4 small">You no longer have access. Refresh or go to Inbox.</div>';
          forbiddenMessageShown = true;
        }
        return;
      }
      var maxRetries = 3;
      if (conversationsLoadRetryCount < maxRetries) {
        conversationsLoadRetryCount += 1;
        var delay = Math.min(500 * Math.pow(2, conversationsLoadRetryCount), 4000);
        setTimeout(function () { loadConversations(true); }, delay);
        if (listEl && lastSuccessfulConversationsHtml) {
          listEl.innerHTML = lastSuccessfulConversationsHtml;
        } else if (listEl && !listEl.querySelector('.text-danger')) {
          listEl.innerHTML = '<div class="text-muted text-center py-4 small">Retrying…</div>';
        }
      } else {
        if (listEl) listEl.innerHTML = '<div class="text-danger text-center py-4">Failed to load conversations. <a href="#" onclick="location.reload();return false;">Refresh</a></div>';
      }
      return Promise.reject(err);
    });
  }

  function isMobileView() {
    return window.matchMedia && window.matchMedia('(max-width: 768px)').matches;
  }

  function selectConversation(id) {
    stopCallPolling();
    closeMessageWebSocket();
    currentConversationId = id;
    lastMessageTimestamp = null;
    replyToMessageId = null;
    replyToPreview = null;
    var rb = document.getElementById('replyBar');
    if (rb) rb.style.display = 'none';
    currentConvDetail = null;
    forbiddenMessageShown = false;
    var paneEmpty = document.getElementById('paneEmpty');
    var paneChat = document.getElementById('paneChat');
    var root = document.querySelector('.chat-app') || document.querySelector('.messaging-root');
    if (paneEmpty) paneEmpty.style.display = 'none';
    if (paneChat) {
      paneChat.style.display = 'flex';
      paneChat.classList.add('pane-chat-enter');
      if (typeof updateBackToBottomVisibility === 'function') {
        updateBackToBottomVisibility();
        requestAnimationFrame(function () { updateBackToBottomVisibility(); });
      }
    }
    if (id && root && isMobileView()) root.classList.add('chat-open');
    var list = document.getElementById('messageList');
    if (list) {
      var wrap = document.getElementById('loadOlderWrap');
      var kids = [];
      for (var i = 0; i < list.children.length; i++) kids.push(list.children[i]);
      kids.forEach(function (el) {
        if (el.id !== 'loadOlderWrap') list.removeChild(el);
      });
      if (wrap) { wrap.style.display = 'none'; wrap.removeAttribute('data-before'); wrap.removeAttribute('data-before-id'); }
    }
    document.querySelectorAll('.messaging-list-item').forEach(function (el) {
      el.classList.toggle('active', parseInt(el.getAttribute('data-id'), 10) === id);
    });
    if (id) loadRetriedForConv[id] = false;
    if (backToBottomCheckTimer) { clearInterval(backToBottomCheckTimer); backToBottomCheckTimer = null; }
    if (id && typeof updateBackToBottomVisibility === 'function') {
      backToBottomCheckTimer = setInterval(updateBackToBottomVisibility, 350);
    }
    /* Use Ajax polling only – no WebSocket */
    loadConversationDetail(id);
    loadMessages(id);
    if (id && C.apiMarkRead) {
      var markUrl = conversationApiUrl(C.apiMarkRead, id);
      apiPost(markUrl, {}).catch(function () {});
    }
    startPolling();
    startTypingPoll();
    updateHeaderActions();
  }

  function rejoinConversation(convId) {
    if (!convId || !C.apiRejoin) return;
    var url = conversationApiUrl(C.apiRejoin, convId);
    apiPost(url, {}).then(function (data) {
      if (data.error) return;
      loadConversations();
      selectConversation(convId);
    }).catch(function (err) {
      if (err && err.message && typeof alert !== 'undefined') alert(err.message || 'Could not rejoin.');
    });
  }

  function loadConversationDetail(id) {
    var url = conversationApiUrl(C.apiConversationDetail, id);
    url += (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
    apiGet(url).then(function (data) {
      currentConvDetail = data;
      var titleEl = document.getElementById('chatTitle');
      if (titleEl) titleEl.textContent = data.name || 'Chat';
      var presEl = document.getElementById('chatPresence');
      if (presEl) {
        var online = (data.members || []).filter(function (m) { return m.user_id !== C.currentUserId && m.online; }).length;
        presEl.textContent = online > 0 ? (online + ' online') : '';
      }
      updateHeaderActions();
    }).catch(function () {
      currentConvDetail = null;
      if (document.getElementById('chatPresence')) document.getElementById('chatPresence').textContent = '';
      updateHeaderActions();
    });
  }

  function updateHeaderActions() {
    var isGroup = currentConvDetail && currentConvDetail.is_group;
    var isGroupAdmin = currentConvDetail && currentConvDetail.is_group_admin;
    var btnRename = document.getElementById('btnRenameConv');
    var btnAdd = document.getElementById('btnAddMember');
    var btnMembers = document.getElementById('btnMembers');
    var btnLeave = document.getElementById('btnLeaveConv');
    if (btnRename) btnRename.style.display = isGroup && isGroupAdmin ? '' : 'none';
    if (btnAdd) btnAdd.style.display = isGroup && isGroupAdmin ? '' : 'none';
    if (btnMembers) btnMembers.style.display = isGroup ? '' : 'none';
    if (btnLeave) btnLeave.style.display = 'inline-block';
  }

  function loadMessages(convId, after, before, beforeId) {
    var url = conversationApiUrl(C.apiMessages, convId);
    var params = [];
    if (after) params.push('after=' + encodeURIComponent(after));
    if (beforeId) params.push('before_id=' + encodeURIComponent(beforeId));
    else if (before) params.push('before=' + encodeURIComponent(before));
    params.push('_=' + Date.now());
    url += (url.indexOf('?') >= 0 ? '&' : '?') + params.join('&');
    var isLoadOlder = !!(before || beforeId);
    return apiGet(url).then(function (data) {
      var list = document.getElementById('messageList');
      if (!list) return;
      var msgs = data.messages || [];
      var atEnd = !isLoadOlder;
      var prevDateKey = null;
      var scrollHeightBefore = list.scrollHeight;
      var firstMsgTime = null;
      var firstMsgId = null;
      var existingIds = {};
      if (isLoadOlder && list) list.querySelectorAll('[data-message-id]').forEach(function (el) { existingIds[el.getAttribute('data-message-id')] = true; });
      var iter = atEnd ? msgs : msgs.slice().reverse();
      iter.forEach(function (m) {
        if (isLoadOlder && existingIds[String(m.id)]) return;
        if (lastMessageTimestamp === null || new Date(m.created_at) > new Date(lastMessageTimestamp)) lastMessageTimestamp = m.created_at;
        if (!firstMsgTime && m.created_at) { firstMsgTime = m.created_at; firstMsgId = m.id; }
        var dateKey = m.created_at ? m.created_at.slice(0, 10) : '';
        if (atEnd) {
          if (dateKey && dateKey !== prevDateKey) {
            prevDateKey = dateKey;
            appendDateSeparator(list, m.created_at, false);
          }
          appendMessage(list, m, true);
        } else {
          appendMessage(list, m, false);
          if (dateKey && dateKey !== prevDateKey) {
            prevDateKey = dateKey;
            appendDateSeparator(list, m.created_at, true);
          }
        }
        if (dateKey) prevDateKey = dateKey;
      });
      if (atEnd) {
        var loadOlderWrap = document.getElementById('loadOlderWrap');
        if (loadOlderWrap && msgs.length > 0) {
          loadOlderWrap.style.display = 'block';
          loadOlderWrap.setAttribute('data-before', msgs[0].created_at);
          loadOlderWrap.setAttribute('data-before-id', String(msgs[0].id));
        }
        var saved = scrollPosByConv[convId];
        if (saved && saved.scrollTop != null) {
          list.scrollTop = Math.min(saved.scrollTop, list.scrollHeight - list.clientHeight);
          delete scrollPosByConv[convId];
        } else {
          list.scrollTop = list.scrollHeight;
        }
        if (typeof updateBackToBottomVisibility === 'function') updateBackToBottomVisibility();
      } else {
        var loadOlderWrap2 = document.getElementById('loadOlderWrap');
        if (firstMsgTime != null && loadOlderWrap2) {
          loadOlderWrap2.setAttribute('data-before', firstMsgTime);
          if (firstMsgId != null) loadOlderWrap2.setAttribute('data-before-id', String(firstMsgId));
        }
        if (msgs.length < 50 && loadOlderWrap2) loadOlderWrap2.style.display = 'none';
        if (list) list.scrollTop = list.scrollHeight - scrollHeightBefore + list.scrollTop;
      }
    }).catch(function (err) {
      if (err && (err.status === 403 || err.status === 404)) {
        stopPolling();
        stopCallPolling();
        var list = document.getElementById('messageList');
        if (list && !list.querySelector('.messaging-access-revoked')) {
          var el = document.createElement('div');
          el.className = 'messaging-access-revoked text-danger text-center py-3 small';
          el.textContent = err.message || 'You no longer have access to this conversation.';
          var ref = firstContentChild(list);
          list.insertBefore(el, ref || list.firstChild);
        }
      } else if (!isLoadOlder && document.getElementById('messageList')) {
        var list = document.getElementById('messageList');
        if (!list.querySelector('.text-muted')) {
          var el = document.createElement('div');
          el.className = 'text-muted text-center py-2';
          el.textContent = 'Could not load messages.';
          list.appendChild(el);
        }
        /* Retry initial load once after a short delay (e.g. token or network ready). */
        if (convId && typeof loadMessages === 'function' && !loadRetriedForConv[convId]) {
          loadRetriedForConv[convId] = true;
          setTimeout(function () {
            if (currentConversationId === convId && list && list.querySelector('.text-muted')) {
              var msgEl = list.querySelector('.text-muted');
              if (msgEl && msgEl.textContent.indexOf('Could not load') !== -1) msgEl.remove();
              loadMessages(convId, null, null, null);
            }
          }, 800);
        }
      }
    });
  }

  function dateLabel(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    var dDay = new Date(d);
    dDay.setHours(0, 0, 0, 0);
    if (dDay.getTime() === today.getTime()) return 'Today';
    if (dDay.getTime() === yesterday.getTime()) return 'Yesterday';
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: d.getFullYear() !== today.getFullYear() ? 'numeric' : undefined });
  }

  function firstContentChild(container) {
    var c = container.firstChild;
    while (c && c.id === 'loadOlderWrap') c = c.nextSibling;
    return c;
  }

  function appendDateSeparator(container, iso, atTop) {
    var div = document.createElement('div');
    div.className = 'msg-date-sep';
    div.setAttribute('data-date-sep', iso ? iso.slice(0, 10) : '');
    div.textContent = dateLabel(iso);
    if (atTop) {
      var ref = firstContentChild(container);
      if (ref) container.insertBefore(div, ref);
      else container.appendChild(div);
    } else container.appendChild(div);
  }

  function getMessageFileUrl(messageId) {
    if (!messageId) return '';
    var base = (C.apiServeFile || '/messaging/api/message-file/').replace(/\/\d*\/?$/, '').replace(/\/$/, '');
    var origin = (typeof location !== 'undefined' && location.origin) ? location.origin : '';
    return origin + base + '/' + messageId + '/';
  }

  function appendMessage(container, m, atEnd) {
    var currentId = C.currentUserId != null ? Number(C.currentUserId) : 0;
    var senderId = m.sender_id != null ? Number(m.sender_id) : 0;
    var isSent = senderId === currentId;
    var canDeleteForAll = isSent || (currentConvDetail && currentConvDetail.is_group_admin);
    var canDelete = !m.is_deleted;
    var bubbleClass = (isSent ? 'msg-bubble sent' : 'msg-bubble received') + ' msg-animate';
    var time = m.created_at ? new Date(m.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : '';
    var replyPart = m.reply_preview ? '<div class="reply-preview">' + escapeHtml(m.reply_preview) + '</div>' : '';
    var fileUrl = m.file;
    if (!fileUrl && m.id && String(m.id).indexOf('pending-') !== 0) {
      if (m.is_image) fileUrl = getMessageFileUrl(m.id);
      else if (!m.content && !m.is_deleted) fileUrl = getMessageFileUrl(m.id);
    }
    if (m.is_image && !fileUrl && m.id) fileUrl = getMessageFileUrl(m.id);
    var body = '';
    if (m.is_deleted) {
      body = '<div class="time text-muted fst-italic">Message deleted</div>';
    } else {
      if (m.is_image && fileUrl) {
        body += '<img class="msg-img" src="' + (fileUrl || '').replace(/"/g, '&quot;') + '" alt="image" loading="eager" referrerpolicy="same-origin">';
      } else if (fileUrl) {
        body += '<a href="' + (fileUrl || '').replace(/"/g, '&quot;') + '" target="_blank" rel="noopener">Download file</a>';
      }
      if (m.content) body += '<div>' + escapeHtml(m.content) + '</div>';
      body += '<div class="time">' + escapeHtml(m.sender_name || '') + ' · ' + time + '</div>';
    }
    var canDeleteForAll = isSent || (currentConvDetail && currentConvDetail.is_group_admin);
    var deleteBtn = canDelete ? ' <button type="button" class="btn btn-link btn-sm p-0 ms-1 msg-delete-btn" data-id="' + m.id + '" data-can-delete-for-all="' + (canDeleteForAll ? '1' : '0') + '" title="Delete">Delete</button>' : '';
    var replyBtn = !m.is_deleted && !isSent ? '<button type="button" class="btn btn-link btn-sm p-0 ms-1 reply-btn" data-id="' + m.id + '" data-preview="' + escapeHtml((m.content || '(file)').substring(0, 50)) + '" title="Reply">Reply</button>' : '';
    var div = document.createElement('div');
    div.className = bubbleClass;
    div.setAttribute('data-message-id', m.id);
    div.innerHTML = replyPart + body + deleteBtn + replyBtn;
    var replyBtnEl = div.querySelector('.reply-btn');
    if (replyBtnEl) replyBtnEl.addEventListener('click', function () {
      replyToMessageId = parseInt(this.getAttribute('data-id'), 10);
      replyToPreview = (this.getAttribute('data-preview') || '').trim();
      var bar = document.getElementById('replyBar');
      var prev = document.getElementById('replyPreview');
      if (prev) prev.textContent = 'Replying to: ' + (replyToPreview || '(message)');
      if (bar) bar.style.display = 'flex';
      var inp = document.getElementById('messageInput');
      if (inp) inp.focus();
    });
    var delBtnEl = div.querySelector('.msg-delete-btn');
    if (delBtnEl && C.apiDeleteMessage && currentConversationId) {
      delBtnEl.addEventListener('click', function () {
        var rawId = this.getAttribute('data-id');
        if (String(rawId).indexOf('pending-') === 0) return;
        var mid = parseInt(rawId, 10);
        if (isNaN(mid)) return;
        var canDeleteForAll = this.getAttribute('data-can-delete-for-all') === '1';
        openDeleteMessageModal(mid, canDeleteForAll);
      });
    }
    if (atEnd !== false) container.appendChild(div);
    else {
      var ref = firstContentChild(container);
      if (ref) container.insertBefore(div, ref);
      else container.appendChild(div);
    }
  }

  function sendMessage() {
    var input = document.getElementById('messageInput');
    var text = (input && input.value || '').trim();
    if (!currentConversationId) return;
    if (!text) {
      var bar = document.getElementById('replyBar');
      if (bar && bar.style.display === 'flex') return;
      return;
    }
    var list = document.getElementById('messageList');
    if (list) {
      var prevErr = list.querySelector('.msg-send-error');
      if (prevErr) prevErr.remove();
    }
    var payload = { content: text };
    if (replyToMessageId) payload.reply_to = replyToMessageId;
    var url = conversationApiUrl(C.apiSend, currentConversationId);
    if (!url || url.indexOf('/conversations//') !== -1) {
      if (list) {
        var el = document.createElement('div');
        el.className = 'msg-send-error text-danger text-center py-2 small';
        el.textContent = 'Cannot send: invalid conversation. Please select a conversation again.';
        list.appendChild(el);
      }
      return;
    }
    var replyBar = document.getElementById('replyBar');
    if (input) input.value = '';
    if (replyBar) replyBar.style.display = 'none';
    var hadReplyTo = replyToMessageId;
    replyToMessageId = null;
    pendingSentContent = text;
    var optimisticId = 'pending-' + Date.now();
    var optimisticMsg = { id: optimisticId, sender_id: C.currentUserId, sender_name: 'You', content: text, reply_to_id: payload.reply_to || null, reply_preview: (hadReplyTo && replyToPreview) ? replyToPreview : null, file: null, is_image: false, created_at: new Date().toISOString() };
    appendMessage(list, optimisticMsg, true);
    list.scrollTop = list.scrollHeight;

    if (typeof navigator !== 'undefined' && !navigator.onLine && window.OfflineSync && typeof window.OfflineSync.queuePendingMessage === 'function') {
      window.OfflineSync.queuePendingMessage(url, payload, optimisticId).then(function () {
        var b = list && list.querySelector('[data-message-id="' + optimisticId + '"]');
        if (b) b.setAttribute('data-pending-sent', '1');
      }).catch(function () {});
      return;
    }

    function doSend(retried, rejoinRetried) {
      if (rejoinRetried === undefined) rejoinRetried = false;
      apiPost(url, payload).then(function (data) {
        if (data.error) {
          pendingSentContent = null;
          var b = document.getElementById('messageList') && document.getElementById('messageList').querySelector('[data-message-id="' + optimisticId + '"]');
          if (b) b.remove();
          if (input) { input.value = text; input.focus(); }
          if (hadReplyTo) { replyToMessageId = hadReplyTo; if (replyBar) replyBar.style.display = 'flex'; }
          return;
        }
        var listEl = document.getElementById('messageList');
        var bubble = listEl && listEl.querySelector('[data-message-id="' + optimisticId + '"]');
        if (bubble) {
          bubble.setAttribute('data-message-id', data.id);
          var timeEl = bubble.querySelector('.time');
          if (timeEl && data.created_at) timeEl.textContent = (timeEl.textContent.replace(/ · .*/, '') || 'You') + ' · ' + new Date(data.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' });
          var delBtn = bubble.querySelector('.msg-delete-btn');
          if (delBtn) delBtn.setAttribute('data-id', data.id);
        }
        if (data.created_at && (lastMessageTimestamp === null || new Date(data.created_at) > new Date(lastMessageTimestamp))) lastMessageTimestamp = data.created_at;
        pendingSentContent = null;
        replyToPreview = null;
        loadConversations(true);
      }).catch(function (err) {
        var listEl = document.getElementById('messageList');
        var bubble = listEl && listEl.querySelector('[data-message-id="' + optimisticId + '"]');
        var isCsrf403 = (err && err.status === 403) || (err && err.message && (err.message.indexOf('access') !== -1 || err.message.indexOf('Forbidden') !== -1));
        var willRetryCsrf = isCsrf403 && !retried && C.apiCsrf;
        var willRetryRejoin = isCsrf403 && !rejoinRetried && C.apiRejoin && currentConversationId;
        if (!willRetryCsrf && !willRetryRejoin) {
          pendingSentContent = null;
          replyToPreview = null;
          if (bubble) bubble.remove();
          if (input) { input.value = text; input.focus(); }
          if (hadReplyTo) { replyToMessageId = hadReplyTo; if (replyBar) replyBar.style.display = 'flex'; }
          showSendError(list, err);
          return;
        }
        if (willRetryCsrf) {
          fetch(C.apiCsrf, { method: 'GET', credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
              if (data.csrfToken) {
                if (typeof C !== 'undefined') C.csrfToken = data.csrfToken;
                var meta = document.querySelector('meta[name="csrf-token"]');
                if (meta) meta.setAttribute('content', data.csrfToken);
                doSend(true, false);
              } else {
                if (bubble) bubble.remove();
                if (input) { input.value = text; input.focus(); }
                if (hadReplyTo) { replyToMessageId = hadReplyTo; if (replyBar) replyBar.style.display = 'flex'; }
                showSendError(list, err);
              }
            })
            .catch(function () {
              if (bubble) bubble.remove();
              if (input) { input.value = text; input.focus(); }
              showSendError(list, err);
            });
          return;
        }
        if (willRetryRejoin) {
          var rejoinUrl = conversationApiUrl(C.apiRejoin, currentConversationId);
          apiPost(rejoinUrl, {}).then(function (r) {
            if (r.error) {
              pendingSentContent = null;
              if (bubble) bubble.remove();
              if (input) { input.value = text; input.focus(); }
              if (hadReplyTo) { replyToMessageId = hadReplyTo; if (replyBar) replyBar.style.display = 'flex'; }
              showSendError(list, err);
              return;
            }
            loadConversations(true);
            doSend(false, true);
          }).catch(function () {
            pendingSentContent = null;
            if (bubble) bubble.remove();
            if (input) { input.value = text; input.focus(); }
            if (hadReplyTo) { replyToMessageId = hadReplyTo; if (replyBar) replyBar.style.display = 'flex'; }
            showSendError(list, err);
          });
        }
      });
    }
    function showSendError(listEl, err) {
      if (!listEl || !document.getElementById('messageList')) return;
      var listErr = document.getElementById('messageList');
      var msg = (err && err.message) || 'Failed to send';
      if (msg.indexOf('no longer have access') !== -1 || msg.indexOf('Forbidden') !== -1 || (err && err.status === 403)) {
        msg = 'Message not sent. Please refresh the page and try again.';
      }
      if (listErr && !listErr.querySelector('.msg-send-error')) {
        var el = document.createElement('div');
        el.className = 'msg-send-error text-danger text-center py-2 small';
        el.textContent = msg;
        listErr.appendChild(el);
      }
    }
    doSend(false);
  }

  function uploadFile(file) {
    if (!currentConversationId || !file) return;
    if (!C.apiUpload) return;
    var url = conversationApiUrl(C.apiUpload, currentConversationId);
    if (!url || url.indexOf('/conversations//') !== -1) return;
    var listEl = document.getElementById('messageList');
    if (!listEl) return;

    var pendingId = 'pending-file-' + Date.now();
    var isImage = file.type && file.type.indexOf('image/') === 0;
    var objectUrl = null;
    var bodyHtml = '';
    if (isImage) {
      objectUrl = (typeof URL !== 'undefined' && URL.createObjectURL) ? URL.createObjectURL(file) : null;
      if (objectUrl) {
        bodyHtml = '<img class="msg-img msg-img-preview" src="' + objectUrl.replace(/"/g, '&quot;') + '" alt="image"><div class="time text-muted small">Sending…</div>';
      } else {
        bodyHtml = '<div class="time text-muted small">Sending image…</div>';
      }
    } else {
      bodyHtml = '<div class="time text-muted small">Sending ' + escapeHtml(file.name || 'file') + '…</div>';
    }
    var placeholder = document.createElement('div');
    placeholder.className = 'msg-bubble sent msg-animate';
    placeholder.setAttribute('data-message-id', pendingId);
    placeholder.innerHTML = bodyHtml;
    if (objectUrl) placeholder.setAttribute('data-object-url', objectUrl);
    listEl.appendChild(placeholder);
    listEl.scrollTop = listEl.scrollHeight;

    var form = new FormData();
    form.append('file', file);
    form.append('csrfmiddlewaretoken', getCsrfToken());
    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: form
    }).then(function (r) {
      return r.text().then(function (text) {
        var ct = (r.headers && r.headers.get('content-type')) ? r.headers.get('content-type') : '';
        var data = {};
        if (ct.indexOf('application/json') !== -1 && text) {
          try { data = JSON.parse(text); } catch (e) { data = {}; }
        }
        if (!r.ok) {
          var msg = (data && data.error) ? data.error : ('Upload failed (' + r.status + ')');
          throw new Error(msg);
        }
        return data;
      });
    }).then(function (data) {
      if (objectUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) URL.revokeObjectURL(objectUrl);
      var place = listEl.querySelector('[data-message-id="' + pendingId + '"]');
      if (place) place.remove();
      if (!data || data.id == null) {
        var errEl = document.createElement('div');
        errEl.className = 'msg-upload-error text-danger text-center py-2 small';
        errEl.textContent = 'Upload failed: invalid response.';
        listEl.appendChild(errEl);
        listEl.scrollTop = listEl.scrollHeight;
        return;
      }
      if (data.error) return;
      var payload = {
        id: data.id,
        sender_id: data.sender_id,
        sender_name: 'You',
        content: data.content || '',
        reply_to_id: data.reply_to_id || null,
        reply_preview: data.reply_preview || null,
        file: data.file || null,
        is_image: !!data.is_image,
        created_at: data.created_at
      };
      appendMessage(listEl, payload, true);
      listEl.scrollTop = listEl.scrollHeight;
      if (lastMessageTimestamp === null || (payload.created_at && new Date(payload.created_at) > new Date(lastMessageTimestamp))) {
        lastMessageTimestamp = payload.created_at;
      }
      loadConversations(true);
    }).catch(function (err) {
      if (objectUrl && typeof URL !== 'undefined' && URL.revokeObjectURL) URL.revokeObjectURL(objectUrl);
      var place = listEl.querySelector('[data-message-id="' + pendingId + '"]');
      if (place) place.remove();
      var prev = listEl.querySelector('.msg-upload-error');
      if (prev) prev.remove();
      var el = document.createElement('div');
      el.className = 'msg-upload-error text-danger text-center py-2 small';
      el.textContent = (err && err.message) ? err.message : 'Upload failed.';
      listEl.appendChild(el);
      listEl.scrollTop = listEl.scrollHeight;
    });
  }

  function pollMessages() {
    if (!currentConversationId) return Promise.resolve();
    if (messagePollInFlight) return Promise.resolve();
    messagePollInFlight = true;
    var url = conversationApiUrl(C.apiMessages, currentConversationId);
    if (lastMessageTimestamp) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'after=' + encodeURIComponent(lastMessageTimestamp);
    url += (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
    return apiGet(url).then(function (data) {
      var msgs = data.messages || [];
      var deletedIds = data.deleted_ids || [];
      var list = document.getElementById('messageList');
      var existingIds = {};
      if (list) list.querySelectorAll('[data-message-id]').forEach(function (el) { existingIds[el.getAttribute('data-message-id')] = true; });
      applyDeletedIdsToDom(deletedIds);
      var lastDateKey = null;
      var lastDateSep = list ? list.querySelector('.msg-date-sep:last-of-type') : null;
      if (lastDateSep) lastDateKey = lastDateSep.getAttribute('data-date-sep');
      msgs.forEach(function (m) {
        if (existingIds[m.id]) return;
        if (pendingSentContent && m.sender_id === C.currentUserId && (m.content || '').trim() === pendingSentContent) return;
        if (lastMessageTimestamp === null || new Date(m.created_at) > new Date(lastMessageTimestamp)) lastMessageTimestamp = m.created_at;
        var dateKey = m.created_at ? m.created_at.slice(0, 10) : '';
        if (dateKey && dateKey !== lastDateKey) {
          lastDateKey = dateKey;
          appendDateSeparator(list, m.created_at, false);
        }
        appendMessage(list, m, true);
        existingIds[m.id] = true;
      });
      if (list && (msgs.length || deletedIds.length)) list.scrollTop = list.scrollHeight;
      if (typeof updateBackToBottomVisibility === 'function') updateBackToBottomVisibility();
      setTimeout(function () { pollDeletedIds(); }, 0);
    }).catch(function (err) {
      if (err && (err.status === 403 || err.status === 404)) {
        stopPolling();
        stopCallPolling();
        var list = document.getElementById('messageList');
        if (list && !list.querySelector('.messaging-access-revoked')) {
          var el = document.createElement('div');
          el.className = 'messaging-access-revoked text-danger text-center py-3 small';
          el.textContent = err.message || 'You no longer have access to this conversation.';
          var ref = firstContentChild(list);
          list.insertBefore(el, ref || list.firstChild);
        }
      }
      /* Do not wipe the message list on poll failure - keep existing messages visible. */
    }).finally(function () {
      messagePollInFlight = false;
    });
  }

  function closeMessageWebSocket() {
    if (messageWs) {
      try { messageWs.close(); } catch (e) {}
      messageWs = null;
      messageWsConvId = null;
    }
  }

  function connectMessageWebSocket(convId) {
    if (!convId || messageWsConvId === convId) return;
    closeMessageWebSocket();
    var scheme = (typeof location !== 'undefined' && location.protocol === 'https:') ? 'wss:' : 'ws:';
    var host = (typeof location !== 'undefined' && location.host) ? location.host : 'localhost:8000';
    var wsUrl = scheme + '//' + host + '/ws/messaging/' + convId + '/';
    try {
      messageWs = new WebSocket(wsUrl);
      messageWsConvId = convId;
      messageWs.onopen = function () {
        startPolling();
      };
      messageWs.onmessage = function (event) {
        try {
          var data = JSON.parse(event.data);
          if (data.type !== 'message' || !data.message) return;
          if (currentConversationId !== convId) return;
          var m = data.message;
          var list = document.getElementById('messageList');
          if (!list) return;
          if (list.querySelector('[data-message-id="' + m.id + '"]')) return;
          if (lastMessageTimestamp === null || new Date(m.created_at) > new Date(lastMessageTimestamp)) lastMessageTimestamp = m.created_at;
          appendMessage(list, m, true);
          list.scrollTop = list.scrollHeight;
        } catch (err) {}
      };
      messageWs.onclose = function () { messageWs = null; messageWsConvId = null; startPolling(); };
      messageWs.onerror = function () { messageWs = null; messageWsConvId = null; startPolling(); };
    } catch (e) { messageWs = null; messageWsConvId = null; }
  }

  function schedulePollLoop() {
    if (!currentConversationId) return;
    var intervalMs = POLL_INTERVAL_MS;
    pollMessages().then(function () {
      pollTimer = setTimeout(schedulePollLoop, intervalMs);
    }, function () {
      pollTimer = setTimeout(schedulePollLoop, intervalMs);
    });
  }

  function startPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    startDeletedPolling();
    /* Ajax only: poll for new messages (no WebSocket) */
    pollMessages().then(function () {
      pollTimer = setTimeout(schedulePollLoop, POLL_INTERVAL_MS);
    }, function () {
      pollTimer = setTimeout(schedulePollLoop, POLL_INTERVAL_MS);
    });
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    stopDeletedPolling();
  }

  function applyDeletedIdsToDom(ids) {
    if (!ids || !ids.length) return;
    var list = document.getElementById('messageList');
    if (!list) return;
    ids.forEach(function (id) {
      var bubble = list.querySelector('[data-message-id="' + id + '"]');
      if (bubble && !bubble.querySelector('.fst-italic')) {
        bubble.innerHTML = '<div class="time text-muted fst-italic">Message deleted</div>';
        bubble.classList.remove('msg-animate');
      }
    });
  }

  function pollDeletedIds() {
    if (!currentConversationId || !C.apiDeletedIdsSince || deletedPollInFlight) return;
    var since = new Date(Date.now() - 10000).toISOString();
    var url = conversationApiUrl(C.apiDeletedIdsSince, currentConversationId) + '?since=' + encodeURIComponent(since) + '&_=' + Date.now();
    deletedPollInFlight = true;
    apiGet(url).then(function (data) {
      lastDeletedCheckAt = new Date().toISOString();
      var ids = data.deleted_ids || [];
      applyDeletedIdsToDom(ids);
      if (deletedPollTimer) setTimeout(pollDeletedIds, 80);
    }).catch(function () {}).finally(function () {
      deletedPollInFlight = false;
    });
  }

  function startDeletedPolling() {
    if (deletedPollTimer) clearInterval(deletedPollTimer);
    deletedPollTimer = null;
    if (!currentConversationId || !C.apiDeletedIdsSince) return;
    lastDeletedCheckAt = new Date(Date.now() - 15000).toISOString();
    pollDeletedIds();
    deletedPollTimer = setInterval(pollDeletedIds, 250);
  }

  function stopDeletedPolling() {
    if (deletedPollTimer) { clearInterval(deletedPollTimer); deletedPollTimer = null; }
  }

  function startCallPolling() {
    stopCallPolling();
    if (!currentConversationId || !C.apiCallStatus) return;
    function poll() {
      if (!currentConversationId) return;
      var url = conversationApiUrl(C.apiCallStatus || '', currentConversationId);
      if (!url) return;
      fetch(url, { method: 'GET', headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
        .then(function (r) {
          if (r.status === 403) {
            stopCallPolling();
            var overlay = document.getElementById('callOverlay');
            if (overlay) overlay.style.display = 'none';
            var btnStart = document.getElementById('btnStartCall');
            var btnEndCall = document.getElementById('btnEndCall');
            if (btnStart) btnStart.style.display = '';
            if (btnEndCall) btnEndCall.style.display = 'none';
            throw new Error('Forbidden');
          }
          var ct = (r.headers && r.headers.get('content-type')) ? r.headers.get('content-type') : '';
          if (ct.indexOf('application/json') === -1) {
            stopCallPolling();
            return { call: null };
          }
          return r.text().then(function (text) {
            try { return text ? JSON.parse(text) : {}; } catch (e) { return {}; }
          });
        })
        .then(function (data) {
          var call = data.call;
          if (!call) return;
          var overlay = document.getElementById('callOverlay');
          var textEl = document.getElementById('callOverlayText');
          var acceptReject = document.getElementById('callOverlayActions');
          var inProgress = document.getElementById('callInProgressActions');
          var btnEnd = document.getElementById('callEnd');
          var btnStart = document.getElementById('btnStartCall');
          var btnEndCall = document.getElementById('btnEndCall');
          if (call.status === 'calling' && call.started_by_id !== C.currentUserId) {
            if (overlay) overlay.style.display = 'flex';
            if (textEl) textEl.textContent = 'Incoming call…';
            if (acceptReject) acceptReject.style.display = 'block';
            if (inProgress) inProgress.style.display = 'none';
          } else if (call.status === 'active' || (call.status === 'calling' && call.started_by_id === C.currentUserId)) {
            if (overlay) overlay.style.display = 'flex';
            if (textEl) textEl.textContent = 'Call in progress…';
            if (acceptReject) acceptReject.style.display = 'none';
            if (inProgress) inProgress.style.display = 'block';
            if (btnStart) btnStart.style.display = 'none';
            if (btnEndCall) btnEndCall.style.display = 'inline-block';
          } else if (call.status === 'ended') {
            if (overlay) overlay.style.display = 'none';
            if (btnStart) btnStart.style.display = '';
            if (btnEndCall) btnEndCall.style.display = 'none';
            stopCallPolling();
          }
        }).catch(function () {});
    }
    poll();
    callPollTimer = setInterval(poll, CALL_POLL_MS);
  }

  function stopCallPolling() {
    if (callPollTimer) { clearInterval(callPollTimer); callPollTimer = null; }
  }

  function startTypingPoll() {
    if (typingPollTimer) clearInterval(typingPollTimer);
    if (!currentConversationId || !C.apiTypingList) return;
    function poll() {
      if (!currentConversationId) return;
      var url = conversationApiUrl(C.apiTypingList || '', currentConversationId);
      apiGet(url).then(function (data) {
        var names = (data.typing || []).map(function (t) { return t.name; });
        var el = document.getElementById('typingIndicator');
        if (el) {
          if (names.length) { el.textContent = names.join(', ') + ' typing…'; el.style.display = ''; }
          else el.style.display = 'none';
        }
      }).catch(function () {});
    }
    poll();
    typingPollTimer = setInterval(poll, TYPING_POLL_MS);
  }

  function heartbeatPresence() {
    apiPost(C.apiPresence, {}).then(function () {});
  }

  function reportPresenceOffline() {
    if (!C.apiPresenceOffline) return;
    try {
      fetch(C.apiPresenceOffline, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: '{}',
        credentials: 'same-origin',
        keepalive: true
      }).catch(function () {});
    } catch (e) {}
  }

  function loadPresenceList() {
    apiGet(C.apiPresenceList).then(function (data) {
      onlineUserIds = data.online_user_ids || [];
      loadConversations();
      if (currentConversationId) loadConversationDetail(currentConversationId);
    });
  }

  function initPresence() {
    heartbeatPresence();
    loadPresenceList();
    if (presenceTimer) clearInterval(presenceTimer);
    presenceTimer = setInterval(function () {
      heartbeatPresence();
      loadPresenceList();
    }, PRESENCE_INTERVAL_MS);
  }

  function escapeHtml(s) {
    if (!s) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function escapeRegex(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function highlightSnippet(snippet, searchWords) {
    if (!snippet) return '';
    var escaped = escapeHtml(snippet);
    if (!searchWords || !searchWords.length) return escaped;
    searchWords.forEach(function (word) {
      var re = new RegExp(escapeRegex(escapeHtml(word)), 'gi');
      escaped = escaped.replace(re, '<mark class="msg-search-highlight">$&</mark>');
    });
    return escaped;
  }

  var pendingDeleteMessageId = null;
  var deleteModalPendingOpen = null;
  var deleteModalIsClosing = false;

  function getOrCreateDeleteModal() {
    var modalEl = document.getElementById('modalDeleteMessage');
    if (!modalEl) return null;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      var existing = bootstrap.Modal.getInstance(modalEl);
      if (existing) return existing;
      return new bootstrap.Modal(modalEl, { backdrop: true, keyboard: true });
    }
    return null;
  }

  function doOpenDeleteModal(messageId, canDeleteForAll) {
    pendingDeleteMessageId = messageId;
    var btnForAll = document.getElementById('deleteForAllBtn');
    if (btnForAll) btnForAll.style.display = canDeleteForAll ? '' : 'none';
    var modal = getOrCreateDeleteModal();
    if (modal) {
      modal.show();
    } else {
      var modalEl = document.getElementById('modalDeleteMessage');
      if (modalEl) {
        modalEl.classList.add('show');
        modalEl.style.display = 'block';
      }
    }
  }

  function openDeleteMessageModal(messageId, canDeleteForAll) {
    if (deleteModalIsClosing) {
      deleteModalPendingOpen = { messageId: messageId, canDeleteForAll: canDeleteForAll };
      return;
    }
    doOpenDeleteModal(messageId, canDeleteForAll);
  }

  function closeDeleteMessageModal() {
    pendingDeleteMessageId = null;
    deleteModalIsClosing = false;
    var modalEl = document.getElementById('modalDeleteMessage');
    if (!modalEl) return;
    modalEl.classList.remove('show');
    modalEl.style.display = 'none';
    modalEl.setAttribute('aria-hidden', 'true');
    document.querySelectorAll('.modal-backdrop').forEach(function (b) { b.remove(); });
    document.body.classList.remove('modal-open');
    document.body.style.removeProperty('overflow');
    document.body.style.removeProperty('padding-right');
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      var m = bootstrap.Modal.getInstance(modalEl);
      if (m) m.dispose();
    }
    var pending = deleteModalPendingOpen;
    deleteModalPendingOpen = null;
    if (pending) {
      setTimeout(function () { doOpenDeleteModal(pending.messageId, pending.canDeleteForAll); }, 0);
    }
  }

  function showDeleteError(msg) {
    var list = document.getElementById('messageList');
    if (!list) return;
    var existing = list.querySelector('.msg-delete-error');
    if (existing) existing.remove();
    var el = document.createElement('div');
    el.className = 'msg-delete-error text-danger text-center py-2 small';
    el.textContent = msg || 'Could not delete message. Please try again.';
    list.appendChild(el);
    setTimeout(function () { if (el.parentNode) el.remove(); }, 4000);
  }

  function updateBubbleAsDeleted(mid) {
    var bubble = document.querySelector('[data-message-id="' + mid + '"]');
    if (bubble) {
      bubble.innerHTML = '<div class="time text-muted fst-italic">Message deleted</div>';
      bubble.classList.remove('msg-animate');
    }
  }

  function performDeleteMessage(deleteFor) {
    if (!pendingDeleteMessageId || !C.apiDeleteMessage || !currentConversationId) return;
    var mid = pendingDeleteMessageId;
    updateBubbleAsDeleted(mid);
    closeDeleteMessageModal();
    var url = conversationApiUrl(C.apiDeleteMessage, currentConversationId);
    apiPost(url, { message_id: mid, delete_for: deleteFor }).then(function (data) {
      if (data && data.error) {
        showDeleteError(data.error);
        loadMessages(currentConversationId);
        return;
      }
    }).catch(function (err) {
      showDeleteError((err && err.message) ? err.message : 'Could not delete message.');
      loadMessages(currentConversationId);
    });
  }

  var emojiModalBuilt = false;

  function buildEmojiModal() {
    var modal = document.getElementById('modalEmoji');
    var tabsWrap = document.getElementById('emojiModalTabs');
    var panelsWrap = document.getElementById('emojiModalPanels');
    if (!modal || !tabsWrap || !panelsWrap) return;
    if (emojiModalBuilt) return;
    emojiModalBuilt = true;

    var targetInput = document.getElementById('messageInput');

    var placeholderGifs = [
      { label: 'Wave', icon: '👋' },
      { label: 'Thumbs up', icon: '👍' },
      { label: 'Happy', icon: '😄' },
      { label: 'Love', icon: '❤️' },
      { label: 'Laugh', icon: '😂' },
      { label: 'Celebrate', icon: '🎉' },
      { label: 'Cool', icon: '😎' },
      { label: 'Wow', icon: '😮' }
    ];
    var placeholderAvatars = ['😀', '😊', '🥳', '😎', '🤗', '😇', '🥰', '😁', '🙂', '🤩', '😄', '👍'];

    EMOJI_CATEGORIES.forEach(function (cat, idx) {
      var tabBtn = document.createElement('button');
      tabBtn.type = 'button';
      tabBtn.className = 'emoji-tab-btn' + (idx === 0 ? ' active' : '');
      tabBtn.setAttribute('data-tab', cat.id);
      tabBtn.setAttribute('role', 'tab');
      tabBtn.setAttribute('aria-selected', idx === 0 ? 'true' : 'false');
      tabBtn.setAttribute('aria-label', cat.label);
      tabBtn.innerHTML = '<span class="emoji-tab-icon">' + cat.icon + '</span>';
      tabBtn.title = cat.label;
      tabsWrap.appendChild(tabBtn);

      var panel = document.createElement('div');
      panel.className = 'emoji-modal-panel' + (idx === 0 ? ' active' : '') + (cat.special ? ' emoji-panel-special' : '');
      panel.id = 'emojiPanel-' + cat.id;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-label', cat.label);
      panel.hidden = idx !== 0;

      if (cat.id === 'gif') {
        var gifInner = document.createElement('div');
        gifInner.className = 'emoji-modal-panel-inner';
        gifInner.innerHTML = '<p class="emoji-gif-placeholder">Search or pick a GIF</p>' +
          '<div class="emoji-gif-grid" id="emojiGifGrid"></div>';
        panel.appendChild(gifInner);
        var gifGrid = panel.querySelector('#emojiGifGrid');
        placeholderGifs.forEach(function (g) {
          var cell = document.createElement('button');
          cell.type = 'button';
          cell.className = 'emoji-gif-item';
          cell.setAttribute('aria-label', g.label);
          cell.innerHTML = '<span class="gif-icon">' + g.icon + '</span>';
          cell.addEventListener('click', function () {
            if (targetInput) {
              targetInput.value += g.icon;
              targetInput.focus();
            }
          });
          gifGrid.appendChild(cell);
        });
      } else if (cat.id === 'avatars') {
        var avInner = document.createElement('div');
        avInner.className = 'emoji-modal-panel-inner';
        avInner.innerHTML = '<p class="emoji-avatars-placeholder">Choose an avatar style</p>' +
          '<div class="emoji-avatars-grid" id="emojiAvatarsGrid"></div>';
        panel.appendChild(avInner);
        var avGrid = panel.querySelector('#emojiAvatarsGrid');
        placeholderAvatars.forEach(function (av) {
          var cell = document.createElement('button');
          cell.type = 'button';
          cell.className = 'emoji-avatar-item';
          cell.setAttribute('aria-label', 'Avatar ' + av);
          cell.innerHTML = '<span class="avatar-icon">' + av + '</span>';
          cell.addEventListener('click', function () {
            if (targetInput) {
              targetInput.value += av;
              targetInput.focus();
            }
          });
          avGrid.appendChild(cell);
        });
      } else {
        var list = (EMOJI_DATA[cat.id] || []).filter(function (e) { return e && String(e).trim(); });
        var inner = document.createElement('div');
        inner.className = 'emoji-modal-panel-inner';
        inner.innerHTML = list.map(function (e) {
          return '<button type="button" class="emoji-cell" data-emoji="' + escapeHtml(e) + '" aria-label="Emoji ' + escapeHtml(e) + '">' + e + '</button>';
        }).join('');
        panel.appendChild(inner);
        panel.querySelectorAll('.emoji-cell').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var em = this.getAttribute('data-emoji');
            if (targetInput && em) {
              targetInput.value += em;
              targetInput.focus();
            }
          });
        });
      }
      panelsWrap.appendChild(panel);
    });

    tabsWrap.querySelectorAll('.emoji-tab-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var tabId = this.getAttribute('data-tab');
        tabsWrap.querySelectorAll('.emoji-tab-btn').forEach(function (b) {
          b.classList.remove('active');
          b.setAttribute('aria-selected', 'false');
        });
        this.classList.add('active');
        this.setAttribute('aria-selected', 'true');
        panelsWrap.querySelectorAll('.emoji-modal-panel').forEach(function (p) {
          var isActive = p.id === 'emojiPanel-' + tabId;
          p.classList.toggle('active', isActive);
          p.hidden = !isActive;
        });
      });
    });

    /* Mouse wheel: ensure the active emoji panel scrolls (Bootstrap/parent can steal wheel) */
    var emojiBody = panelsWrap.parentElement;
    if (emojiBody) {
      emojiBody.addEventListener('wheel', function (e) {
        var activePanel = emojiBody.querySelector('.emoji-modal-panel.active');
        if (!activePanel) return;
        var maxScroll = activePanel.scrollHeight - activePanel.clientHeight;
        if (maxScroll <= 0) return;
        var next = activePanel.scrollTop + e.deltaY;
        activePanel.scrollTop = Math.max(0, Math.min(maxScroll, next));
        e.preventDefault();
        e.stopPropagation();
      }, { passive: false, capture: true });
    }
  }

  var emojiModalInstance = null;

  function getOrCreateEmojiModal() {
    var modalEl = document.getElementById('modalEmoji');
    if (!modalEl) return null;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      emojiModalInstance = bootstrap.Modal.getInstance(modalEl) || new bootstrap.Modal(modalEl, { backdrop: true, keyboard: true });
      return emojiModalInstance;
    }
    return null;
  }

  function closeEmojiModal() {
    var modalEl = document.getElementById('modalEmoji');
    if (!modalEl) return;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      var instance = bootstrap.Modal.getInstance(modalEl);
      if (instance) instance.hide();
    } else {
      modalEl.classList.remove('show');
      modalEl.style.display = 'none';
      modalEl.setAttribute('aria-hidden', 'true');
      var backdrop = document.getElementById('emojiModalBackdrop');
      if (backdrop && backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
    }
  }

  function openEmojiModal() {
    buildEmojiModal();
    var modalEl = document.getElementById('modalEmoji');
    if (!modalEl) return;
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
      var modal = getOrCreateEmojiModal();
      if (modal) modal.show();
    } else {
      var existing = document.getElementById('emojiModalBackdrop');
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      modalEl.classList.add('show');
      modalEl.style.display = 'block';
      modalEl.setAttribute('aria-hidden', 'false');
      var backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop fade show';
      backdrop.id = 'emojiModalBackdrop';
      backdrop.setAttribute('aria-hidden', 'true');
      document.body.appendChild(backdrop);
      backdrop.addEventListener('click', function () { closeEmojiModal(); });
    }
  }

  var BACK_TO_BOTTOM_THRESHOLD = 50;

  function updateBackToBottomVisibility() {
    var paneChat = document.getElementById('paneChat');
    var list = document.getElementById('messageList');
    var btn = document.getElementById('btnBackToBottom');
    if (!btn) return;
    var chatVisible = paneChat && paneChat.style.display !== 'none' && currentConversationId;
    if (!chatVisible) {
      btn.classList.remove('is-visible');
      return;
    }
    /* Show button whenever chat is open; only hide when clearly at bottom of a scrollable list */
    btn.classList.add('is-visible');
    if (!list) return;
    var distanceFromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
    var atBottom = distanceFromBottom <= BACK_TO_BOTTOM_THRESHOLD;
    var canScroll = list.scrollHeight > list.clientHeight;
    if (canScroll && atBottom) {
      btn.classList.remove('is-visible');
    }
  }

  function getScrollableMessageContainer() {
    var list = document.getElementById('messageList');
    if (!list) return null;
    var el = list;
    while (el && el !== document.body) {
      if (el.scrollHeight > el.clientHeight && (el === list || (window.getComputedStyle(el).overflowY || '').match(/auto|scroll|overlay/))) {
        return el;
      }
      el = el.parentElement;
    }
    return list;
  }

  function scrollToBottom() {
    var list = document.getElementById('messageList');
    if (!list) return;
    var scrollable = getScrollableMessageContainer();
    function doScroll() {
      if (scrollable) {
        scrollable.scrollTop = scrollable.scrollHeight;
      }
      var last = list.lastElementChild;
      if (last && last.scrollIntoView) {
        last.scrollIntoView({ block: 'end', behavior: 'auto' });
      }
      updateBackToBottomVisibility();
    }
    doScroll();
    requestAnimationFrame(function () {
      scrollable = getScrollableMessageContainer();
      if (scrollable) scrollable.scrollTop = scrollable.scrollHeight;
      doScroll();
    });
    setTimeout(function () {
      scrollable = getScrollableMessageContainer();
      if (scrollable) scrollable.scrollTop = scrollable.scrollHeight;
      var last = list.lastElementChild;
      if (last && last.scrollIntoView) last.scrollIntoView({ block: 'end', behavior: 'auto' });
      updateBackToBottomVisibility();
    }, 100);
  }

  function startListRefresh() {
    if (listRefreshTimer) clearInterval(listRefreshTimer);
    listRefreshTimer = setInterval(loadConversations, LIST_REFRESH_INTERVAL_MS);
  }

  function stopListRefresh() {
    if (listRefreshTimer) { clearInterval(listRefreshTimer); listRefreshTimer = null; }
  }

  function applyInitialConversation() {
    if (!C.initialConversationId) {
      if (document.getElementById('paneEmpty')) document.getElementById('paneEmpty').style.display = 'flex';
      if (document.getElementById('paneChat')) document.getElementById('paneChat').style.display = 'none';
      return;
    }
    var el = document.querySelector('.messaging-list-item[data-id="' + C.initialConversationId + '"]');
    if (el && el.getAttribute('data-left') === '1' && C.apiRejoin) {
      rejoinConversation(C.initialConversationId);
      return;
    }
    selectConversation(C.initialConversationId);
  }

  function init() {
    var list = document.getElementById('conversationList');
    if (!list) return;
    if (!(window.MESSAGING_CONFIG && window.MESSAGING_CONFIG.apiConversations)) {
      var tries = (window._messagingInitTries || 0);
      window._messagingInitTries = tries + 1;
      if (tries < 20) setTimeout(init, 50);
      return;
    }
    window._messagingInitTries = 0;
    var loadPromise = loadConversations();
    if (loadPromise && typeof loadPromise.then === 'function') {
      loadPromise.then(applyInitialConversation, applyInitialConversation);
    } else {
      applyInitialConversation();
    }
    startListRefresh();
    initPresence();

    document.getElementById('btnEmoji') && document.getElementById('btnEmoji').addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      openEmojiModal();
    });
    document.getElementById('deleteForMeBtn') && document.getElementById('deleteForMeBtn').addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      performDeleteMessage('me');
    });
    document.getElementById('deleteForAllBtn') && document.getElementById('deleteForAllBtn').addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      performDeleteMessage('all');
    });
    document.getElementById('modalEmojiClose') && document.getElementById('modalEmojiClose').addEventListener('click', function () {
      closeEmojiModal();
    });
    document.getElementById('modalEmojiDone') && document.getElementById('modalEmojiDone').addEventListener('click', function () {
      closeEmojiModal();
    });

    document.getElementById('btnAttach') && document.getElementById('btnAttach').addEventListener('click', function () {
      document.getElementById('fileInput').click();
    });
    document.getElementById('fileInput') && document.getElementById('fileInput').addEventListener('change', function () {
      var f = this.files && this.files[0];
      if (f) uploadFile(f);
      this.value = '';
    });

    document.getElementById('btnSend') && document.getElementById('btnSend').addEventListener('click', sendMessage);
    document.getElementById('messageInput') && document.getElementById('messageInput').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    window.addEventListener('offlineQueuesProcessed', function () {
      pendingSentContent = null;
      var list = document.getElementById('messageList');
      if (list) list.querySelectorAll('[data-pending-sent="1"]').forEach(function (el) { el.remove(); });
      if (typeof pollMessages === 'function') pollMessages();
    });

    document.getElementById('cancelReply') && document.getElementById('cancelReply').addEventListener('click', function () {
      replyToMessageId = null;
      replyToPreview = null;
      var rb = document.getElementById('replyBar');
      if (rb) rb.style.display = 'none';
    });

    document.getElementById('btnNewChat') && document.getElementById('btnNewChat').addEventListener('click', function () {
      apiGet(C.apiAccountUsers).then(function (data) {
        var sel = document.getElementById('newChatUser');
        var users = data.users || [];
        sel.innerHTML = '<option value="">Select…</option>' + users.map(function (u) { return '<option value="' + u.id + '">' + escapeHtml(u.name || u.email) + '</option>'; }).join('');
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          new bootstrap.Modal(document.getElementById('modalNewChat')).show();
        } else document.getElementById('modalNewChat').classList.add('show');
      });
    });
    document.getElementById('modalNewChatStart') && document.getElementById('modalNewChatStart').addEventListener('click', function () {
      var sel = document.getElementById('newChatUser');
      var uid = sel && sel.value;
      if (!uid) return;
      apiPost(C.apiCreateConversation, { other_user_id: parseInt(uid, 10) }).then(function (data) {
        if (data.error) return;
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          var modal = bootstrap.Modal.getInstance(document.getElementById('modalNewChat'));
          if (modal) modal.hide();
        } else document.getElementById('modalNewChat').classList.remove('show');
        var convId = data.conversation_id;
        loadConversations(true).then(function () { selectConversation(convId); }, function () { selectConversation(convId); });
      });
    });

    document.getElementById('btnNewGroup') && document.getElementById('btnNewGroup').addEventListener('click', function () {
      apiGet(C.apiAccountUsers).then(function (data) {
        var sel = document.getElementById('newGroupMembers');
        var users = data.users || [];
        sel.innerHTML = users.map(function (u) { return '<option value="' + u.id + '">' + escapeHtml(u.name || u.email) + '</option>'; }).join('');
        document.getElementById('newGroupName').value = '';
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          new bootstrap.Modal(document.getElementById('modalNewGroup')).show();
        } else document.getElementById('modalNewGroup').classList.add('show');
      });
    });
    document.getElementById('modalNewGroupCreate') && document.getElementById('modalNewGroupCreate').addEventListener('click', function () {
      var name = (document.getElementById('newGroupName').value || '').trim();
      var sel = document.getElementById('newGroupMembers');
      var memberIds = [];
      if (sel) for (var i = 0; i < sel.options.length; i++) if (sel.options[i].selected) memberIds.push(parseInt(sel.options[i].value, 10));
      if (!name) return;
      apiPost(C.apiCreateConversation, { name: name, member_ids: memberIds }).then(function (data) {
        if (data.error) return;
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          var modal = bootstrap.Modal.getInstance(document.getElementById('modalNewGroup'));
          if (modal) modal.hide();
        } else document.getElementById('modalNewGroup').classList.remove('show');
        var convId = data.conversation_id;
        loadConversations(true).then(function () { selectConversation(convId); }, function () { selectConversation(convId); });
      });
    });

    document.getElementById('btnLoadOlder') && document.getElementById('btnLoadOlder').addEventListener('click', function () {
      var wrap = document.getElementById('loadOlderWrap');
      var beforeId = wrap && wrap.getAttribute('data-before-id');
      var before = wrap && wrap.getAttribute('data-before');
      if (!currentConversationId || (!beforeId && !before)) return;
      wrap.style.display = 'none';
      loadMessages(currentConversationId, null, before, beforeId);
    });

    document.getElementById('btnStartCall') && document.getElementById('btnStartCall').addEventListener('click', function () {
      if (!currentConversationId || !C.apiCallStart) return;
      var url = conversationApiUrl(C.apiCallStart, currentConversationId);
      apiPost(url, {}).then(function () {
        startCallPolling();
        document.getElementById('btnStartCall').style.display = 'none';
        document.getElementById('btnEndCall').style.display = 'inline-block';
        var overlay = document.getElementById('callOverlay');
        var textEl = document.getElementById('callOverlayText');
        var acceptReject = document.getElementById('callOverlayActions');
        var inProgress = document.getElementById('callInProgressActions');
        if (overlay) overlay.style.display = 'flex';
        if (textEl) textEl.textContent = 'Call in progress…';
        if (acceptReject) acceptReject.style.display = 'none';
        if (inProgress) inProgress.style.display = 'block';
      }).catch(function () {});
    });
    document.getElementById('btnEndCall') && document.getElementById('btnEndCall').addEventListener('click', function () {
      if (!currentConversationId || !C.apiCallEnd) return;
      var url = conversationApiUrl(C.apiCallEnd, currentConversationId);
      apiPost(url, {}).then(function () {
        stopCallPolling();
        document.getElementById('btnStartCall').style.display = '';
        document.getElementById('btnEndCall').style.display = 'none';
        var overlay = document.getElementById('callOverlay');
        if (overlay) overlay.style.display = 'none';
      }).catch(function () {});
    });
    document.getElementById('callEnd') && document.getElementById('callEnd').addEventListener('click', function () {
      if (!currentConversationId || !C.apiCallEnd) return;
      var url = conversationApiUrl(C.apiCallEnd, currentConversationId);
      apiPost(url, {}).then(function () {
        stopCallPolling();
        document.getElementById('btnStartCall').style.display = '';
        document.getElementById('btnEndCall').style.display = 'none';
        var overlay = document.getElementById('callOverlay');
        if (overlay) overlay.style.display = 'none';
      }).catch(function () {});
    });
    document.getElementById('callAccept') && document.getElementById('callAccept').addEventListener('click', function () {
      var overlay = document.getElementById('callOverlay');
      var acceptReject = document.getElementById('callOverlayActions');
      var inProgress = document.getElementById('callInProgressActions');
      if (acceptReject) acceptReject.style.display = 'none';
      if (inProgress) inProgress.style.display = 'block';
      if (document.getElementById('callOverlayText')) document.getElementById('callOverlayText').textContent = 'Call in progress…';
    });
    document.getElementById('callReject') && document.getElementById('callReject').addEventListener('click', function () {
      if (!currentConversationId || !C.apiCallEnd) return;
      var url = conversationApiUrl(C.apiCallEnd, currentConversationId);
      apiPost(url, {}).then(function () {
        stopCallPolling();
        var overlay = document.getElementById('callOverlay');
        if (overlay) overlay.style.display = 'none';
        document.getElementById('btnStartCall').style.display = '';
        document.getElementById('btnEndCall').style.display = 'none';
      }).catch(function () {});
    });

    document.getElementById('btnLeaveConv') && document.getElementById('btnLeaveConv').addEventListener('click', function () {
      if (!currentConversationId || !C.apiLeave) return;
      if (!confirm('Leave this conversation? You can rejoin anytime to continue from where you left off.')) return;
      var url = conversationApiUrl(C.apiLeave, currentConversationId);
      apiPost(url, {}).then(function (data) {
        if (data.error) {
          if (typeof alert !== 'undefined') alert(data.error); else if (document.getElementById('messageList')) {
            var el = document.createElement('div');
            el.className = 'text-danger text-center py-2 small';
            el.textContent = data.error;
            document.getElementById('messageList').appendChild(el);
          }
          return;
        }
        stopPolling();
        stopCallPolling();
        closeMessageWebSocket();
        reportPresenceOffline();
        currentConversationId = null;
        if (C.inboxUrl) window.location.href = C.inboxUrl;
        else {
          var root = document.querySelector('.chat-app') || document.querySelector('.messaging-root');
          if (root) root.classList.remove('chat-open');
          document.getElementById('paneEmpty').style.display = 'flex';
          document.getElementById('paneChat').style.display = 'none';
          loadConversations();
        }
      }).catch(function (err) {
        var msg = (err && err.message) ? err.message : 'Could not leave conversation.';
        if (typeof alert !== 'undefined') alert(msg); else if (document.getElementById('messageList')) {
          var el = document.createElement('div');
          el.className = 'text-danger text-center py-2 small';
          el.textContent = msg;
          document.getElementById('messageList').appendChild(el);
        }
      });
    });

    document.getElementById('btnRenameConv') && document.getElementById('btnRenameConv').addEventListener('click', function () {
      if (!currentConversationId || !currentConvDetail || !C.apiRename) return;
      document.getElementById('renameGroupName').value = currentConvDetail.name || '';
      if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        new bootstrap.Modal(document.getElementById('modalRenameGroup')).show();
      } else document.getElementById('modalRenameGroup').classList.add('show');
    });
    document.getElementById('modalRenameGroupSave') && document.getElementById('modalRenameGroupSave').addEventListener('click', function () {
      var name = (document.getElementById('renameGroupName').value || '').trim();
      if (!name || !currentConversationId || !C.apiRename) return;
      var url = conversationApiUrl(C.apiRename, currentConversationId);
      apiPost(url, { name: name }).then(function (data) {
        if (data.error) return;
        if (currentConvDetail) currentConvDetail.name = name;
        document.getElementById('chatTitle').textContent = name;
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          var modal = bootstrap.Modal.getInstance(document.getElementById('modalRenameGroup'));
          if (modal) modal.hide();
        } else document.getElementById('modalRenameGroup').classList.remove('show');
        loadConversations();
      }).catch(function () {});
    });

    document.getElementById('btnMembers') && document.getElementById('btnMembers').addEventListener('click', function () {
      if (!currentConvDetail || !currentConvDetail.members) return;
      var ul = document.getElementById('membersList');
      var members = currentConvDetail.members;
      var isGroupAdmin = currentConvDetail.is_group_admin;
      var canRemove = isGroupAdmin && members.length > 1;
      ul.innerHTML = members.map(function (m) {
        var removeBtn = canRemove && m.user_id !== C.currentUserId
          ? ' <button type="button" class="btn btn-sm btn-outline-danger remove-member-btn" data-user-id="' + m.user_id + '">Remove</button>'
          : '';
        return '<li class="list-group-item d-flex justify-content-between align-items-center">' + escapeHtml(m.name) + (m.is_admin ? ' <span class="badge bg-secondary">Admin</span>' : '') + removeBtn + '</li>';
      }).join('');
      ul.querySelectorAll('.remove-member-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var uid = parseInt(this.getAttribute('data-user-id'), 10);
          if (!currentConversationId || !C.apiRemoveMember) return;
          if (!confirm('Remove this member from the conversation?')) return;
          var url = conversationApiUrl(C.apiRemoveMember, currentConversationId);
          apiPost(url, { user_id: uid }).then(function (data) {
            if (data.error) return;
            loadConversationDetail(currentConversationId);
            loadConversations();
            if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
              var modal = bootstrap.Modal.getInstance(document.getElementById('modalMembers'));
              if (modal) modal.hide();
            }
          }).catch(function () {});
        });
      });
      if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        new bootstrap.Modal(document.getElementById('modalMembers')).show();
      } else document.getElementById('modalMembers').classList.add('show');
    });

    document.getElementById('btnAddMember') && document.getElementById('btnAddMember').addEventListener('click', function () {
      if (!currentConversationId || !C.apiAccountUsers) return;
      apiGet(C.apiAccountUsers).then(function (data) {
        var members = (currentConvDetail && currentConvDetail.members) || [];
        var memberIds = members.map(function (m) { return m.user_id; });
        var users = (data.users || []).filter(function (u) { return memberIds.indexOf(u.id) < 0; });
        var sel = document.getElementById('addMemberUser');
        sel.innerHTML = '<option value="">Select…</option>' + users.map(function (u) { return '<option value="' + u.id + '">' + escapeHtml(u.name || u.email) + '</option>'; }).join('');
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          new bootstrap.Modal(document.getElementById('modalAddMember')).show();
        } else document.getElementById('modalAddMember').classList.add('show');
      });
    });
    document.getElementById('modalAddMemberConfirm') && document.getElementById('modalAddMemberConfirm').addEventListener('click', function () {
      var uid = document.getElementById('addMemberUser').value;
      if (!uid || !currentConversationId || !C.apiAddMember) return;
      var url = conversationApiUrl(C.apiAddMember, currentConversationId);
      apiPost(url, { user_id: parseInt(uid, 10) }).then(function (data) {
        if (data.error) return;
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
          var modal = bootstrap.Modal.getInstance(document.getElementById('modalAddMember'));
          if (modal) modal.hide();
        } else document.getElementById('modalAddMember').classList.remove('show');
        loadConversationDetail(currentConversationId);
        loadConversations();
      }).catch(function () {});
    });

    document.getElementById('btnSearchMessages') && document.getElementById('btnSearchMessages').addEventListener('click', function () {
      if (!currentConversationId) return;
      document.getElementById('searchMessagesQuery').value = '';
      document.getElementById('searchMessagesResults').innerHTML = '';
      if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        new bootstrap.Modal(document.getElementById('modalSearchMessages')).show();
      } else document.getElementById('modalSearchMessages').classList.add('show');
    });
    var searchMessagesDebounce = null;
    document.getElementById('searchMessagesQuery') && document.getElementById('searchMessagesQuery').addEventListener('input', function () {
      var q = (this.value || '').trim();
      var resultsEl = document.getElementById('searchMessagesResults');
      if (!currentConversationId) { resultsEl.innerHTML = ''; return; }
      if (searchMessagesDebounce) clearTimeout(searchMessagesDebounce);
      if (!q) { resultsEl.innerHTML = '<div class="list-group-item text-muted">Type to search messages in this conversation.</div>'; return; }
      resultsEl.innerHTML = '<div class="list-group-item text-muted">Searching…</div>';
      searchMessagesDebounce = setTimeout(function () {
        searchMessagesDebounce = null;
        var url = conversationApiUrl(C.apiMessages, currentConversationId) + '?q=' + encodeURIComponent(q);
        apiGet(url).then(function (data) {
          var msgs = data.messages || [];
          var words = q.split(/\s+/).filter(function (w) { return w.length > 0; });
          resultsEl.innerHTML = msgs.length === 0
            ? '<div class="list-group-item text-muted">No messages match your search.</div>'
            : msgs.map(function (m) {
                var snippet = m.snippet || (m.content || '(file)').substring(0, 100);
                if ((m.content || '').length > 100 && !m.snippet) snippet += '…';
                var snippetHtml = highlightSnippet(snippet, words);
                var createdAt = m.created_at || '';
                return '<a href="#" class="list-group-item list-group-item-action search-result-item" data-id="' + m.id + '" data-created-at="' + escapeHtml(createdAt) + '">' +
                  '<div class="small text-muted mb-1">' + escapeHtml(m.sender_name) + '</div>' +
                  '<div class="search-snippet">' + snippetHtml + '</div></a>';
              }).join('');
          resultsEl.querySelectorAll('a.search-result-item').forEach(function (a) {
            a.addEventListener('click', function (e) {
              e.preventDefault();
              var id = parseInt(this.getAttribute('data-id'), 10);
              var createdStr = this.getAttribute('data-created-at');
              var bubble = document.getElementById('messageList') && document.getElementById('messageList').querySelector('[data-message-id="' + id + '"]');
              function scrollToAndHighlight() {
                var b = document.getElementById('messageList') && document.getElementById('messageList').querySelector('[data-message-id="' + id + '"]');
                if (b) {
                  b.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  b.classList.add('msg-search-highlight-bubble');
                  setTimeout(function () { b.classList.remove('msg-search-highlight-bubble'); }, 2500);
                }
                if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                  var modal = bootstrap.Modal.getInstance(document.getElementById('modalSearchMessages'));
                  if (modal) modal.hide();
                }
              }
              if (bubble) {
                scrollToAndHighlight();
              } else if (createdStr) {
                try {
                  var d = new Date(createdStr);
                  d.setMilliseconds(d.getMilliseconds() - 1);
                  var afterIso = d.toISOString();
                  loadMessages(currentConversationId, afterIso).then(function () { scrollToAndHighlight(); });
                } catch (err) {
                  loadMessages(currentConversationId).then(function () { scrollToAndHighlight(); });
                }
              } else {
                loadMessages(currentConversationId).then(function () { scrollToAndHighlight(); });
              }
            });
          });
        }).catch(function () { resultsEl.innerHTML = '<div class="list-group-item text-danger">Search failed. Try again.</div>'; });
      }, 280);
    });

    document.getElementById('btnBackChat') && document.getElementById('btnBackChat').addEventListener('click', function () {
      var root = document.querySelector('.chat-app') || document.querySelector('.messaging-root');
      if (root) root.classList.remove('chat-open');
      var paneEmpty = document.getElementById('paneEmpty');
      var paneChat = document.getElementById('paneChat');
      var list = document.getElementById('messageList');
      if (currentConversationId && list) {
        scrollPosByConv[currentConversationId] = { scrollTop: list.scrollTop, scrollHeight: list.scrollHeight };
      }
      if (paneEmpty) paneEmpty.style.display = 'flex';
      if (paneChat) paneChat.style.display = 'none';
      if (backToBottomCheckTimer) { clearInterval(backToBottomCheckTimer); backToBottomCheckTimer = null; }
      if (typeof updateBackToBottomVisibility === 'function') updateBackToBottomVisibility();
    });

    document.getElementById('conversationSearch') && document.getElementById('conversationSearch').addEventListener('input', function () {
      conversationSearchQuery = (this.value || '').trim();
      loadConversations();
    });

    document.getElementById('btnBackToBottom') && document.getElementById('btnBackToBottom').addEventListener('click', function () {
      scrollToBottom();
    });
    var listEl = document.getElementById('messageList');
    if (listEl) {
      listEl.addEventListener('scroll', function () { updateBackToBottomVisibility(); });
    }

    var messageInputEl = document.getElementById('messageInput');
    if (messageInputEl) {
      messageInputEl.addEventListener('input', function () {
        if (!currentConversationId || !C.apiTypingStart) return;
        var url = conversationApiUrl(C.apiTypingStart, currentConversationId);
        apiPost(url, {}).catch(function () {});
      });
      messageInputEl.addEventListener('blur', function () {
        if (!currentConversationId || !C.apiTypingStop) return;
        var url = conversationApiUrl(C.apiTypingStop, currentConversationId);
        apiPost(url, {}).catch(function () {});
      });
    }

    /* Do not request browser notification permission on load; in-app toasts work without it. */
    var lastNotifiedMessageId = {};
    function maybeNotify(convId, m) {
      if (document.visibilityState === 'visible') return;
      if (m.sender_id === C.currentUserId) return;
      if (!lastNotifiedMessageId[convId]) lastNotifiedMessageId[convId] = 0;
      if (m.id <= lastNotifiedMessageId[convId]) return;
      lastNotifiedMessageId[convId] = m.id;
      if (Notification.permission !== 'granted') return;
      try {
        new Notification('New message', { body: (m.sender_name || 'Someone') + ': ' + (m.content || '(file)').substring(0, 50), tag: 'msg-' + convId });
      } catch (e) {}
    }
    var originalAppendMessage = appendMessage;
    appendMessage = function (container, m, atEnd) {
      if (currentConversationId && atEnd && container.id === 'messageList') maybeNotify(currentConversationId, m);
      return originalAppendMessage.apply(this, arguments);
    };

    window.addEventListener('beforeunload', function () { reportPresenceOffline(); stopPolling(); stopListRefresh(); });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') {
        conversationsLoadRetryCount = 0;
        heartbeatPresence();
        loadPresenceList();
        loadConversations(true);
        if (currentConversationId) pollMessages();
        startPolling();
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
