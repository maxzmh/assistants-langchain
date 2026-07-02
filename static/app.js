    const messagesEl = document.getElementById('messages');
    const textEl = document.getElementById('text');
    const sendBtn = document.getElementById('send');
    const fileInput = document.getElementById('file');
    const uploadBtn = document.getElementById('uploadBtn');
    const preview = document.getElementById('preview');
    const previewImg = document.getElementById('previewImg');
    const removeImg = document.getElementById('removeImg');
    const newChatBtn = document.getElementById('newChat');
    const sessionItems = document.getElementById('sessionItems');

    let selectedFile = null;
    let sessionId = null;       // 当前会话 id
    let dirty = false;          // 当前会话是否已产生过消息

    const WELCOME = '你好！我可以回答你的问题，也可以帮你分析图片。有什么想聊的？';

    function newId() {
      return 'web-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }

    // —— 新建会话：立即在后端登记保存，并刷新列表 ——
    // 若当前已是一个空会话（还没发过消息），则直接复用，避免连点产生一堆空会话。
    async function createSession() {
      if (sessionId && !dirty) {
        // 当前会话还是空的，无需再新建，给个提示即可
        messagesEl.innerHTML = '';
        addMessage('bot', { text: WELCOME });
        await loadSessions();
        return;
      }
      sessionId = newId();
      dirty = false;
      const form = new FormData();
      form.append('session_id', sessionId);
      try { await fetch('/api/session', { method: 'POST', body: form }); } catch (_) {}
      messagesEl.innerHTML = '';
      addMessage('bot', { text: WELCOME });
      await loadSessions();
    }
    newChatBtn.onclick = createSession;

    // —— 加载并渲染历史会话列表 ——
    async function loadSessions() {
      let sessions = [];
      try {
        const r = await fetch('/api/sessions');
        sessions = (await r.json()).sessions || [];
      } catch (_) {}
      sessionItems.innerHTML = '';
      if (!sessions.length) {
        sessionItems.innerHTML = '<div class="empty-tip">还没有历史会话</div>';
        return;
      }
      for (const s of sessions) {
        const item = document.createElement('div');
        item.className = 'session-item' + (s.session_id === sessionId ? ' active' : '');
        const title = document.createElement('span');
        title.className = 'title';
        title.textContent = s.title || '新对话';
        const del = document.createElement('button');
        del.className = 'del';
        del.textContent = '🗑';
        del.title = '删除会话';
        del.onclick = (e) => { e.stopPropagation(); deleteSession(s.session_id); };
        item.appendChild(title);
        item.appendChild(del);
        item.onclick = () => switchSession(s.session_id);
        sessionItems.appendChild(item);
      }
    }

    // —— 切换会话：拉取该会话历史并回显 ——
    async function switchSession(id) {
      if (id === sessionId) return;
      sessionId = id;
      dirty = true; // 已有历史的会话
      messagesEl.innerHTML = '';
      let msgs = [];
      try {
        const r = await fetch('/api/history?session_id=' + encodeURIComponent(id));
        msgs = (await r.json()).messages || [];
      } catch (_) {}
      if (!msgs.length) {
        addMessage('bot', { text: WELCOME });
      } else {
        for (const m of msgs) {
          addMessage(m.role, { text: m.text, imageUrl: m.image, id: m.id });
        }
      }
      loadSessions();
    }

    // —— 删除会话 ——
    async function deleteSession(id) {
      if (!confirm('确定删除这个会话吗？')) return;
      const form = new FormData();
      form.append('session_id', id);
      try { await fetch('/api/delete', { method: 'POST', body: form }); } catch (_) {}
      if (id === sessionId) {
        await createSession();  // 删的是当前会话则新建一个
      } else {
        await loadSessions();
      }
    }

    // —— 图片选择与预览 ——
    uploadBtn.onclick = () => fileInput.click();
    fileInput.onchange = () => {
      const f = fileInput.files[0];
      if (!f) return;
      selectedFile = f;
      previewImg.src = URL.createObjectURL(f);
      preview.style.display = 'block';
    };
    removeImg.onclick = () => {
      selectedFile = null;
      fileInput.value = '';
      preview.style.display = 'none';
    };

    // —— 文本框自适应高度 ——
    textEl.addEventListener('input', () => {
      textEl.style.height = 'auto';
      textEl.style.height = Math.min(textEl.scrollHeight, 120) + 'px';
    });

    // —— Enter 发送 / Shift+Enter 换行 ——
    textEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    sendBtn.onclick = send;

    // —— 轻量 Markdown 渲染器（内置，无外部依赖；先转义 HTML 再解析，避免 XSS）——
    function escapeHtml(s) {
      return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function renderInline(s) {
      // 行内：代码、粗体、斜体、链接
      let out = s.replace(/`([^`]+)`/g, (_, c) => '<code>' + c + '</code>');
      out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
      out = out.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>');
      return out;
    }
    function renderMarkdown(src) {
      const text = escapeHtml(src);
      const lines = text.split('\n');
      let html = '', i = 0;
      let listType = null; // 'ul' | 'ol'
      const closeList = () => { if (listType) { html += '</' + listType + '>'; listType = null; } };
      while (i < lines.length) {
        let line = lines[i];
        // 代码块 ```
        if (/^```/.test(line)) {
          closeList();
          i++;
          let code = '';
          while (i < lines.length && !/^```/.test(lines[i])) { code += lines[i] + '\n'; i++; }
          i++;
          html += '<pre><code>' + code.replace(/\n$/, '') + '</code></pre>';
          continue;
        }
        // 分隔线
        if (/^\s*---\s*$/.test(line)) { closeList(); html += '<hr>'; i++; continue; }
        // 标题
        const h = line.match(/^(#{1,4})\s+(.*)$/);
        if (h) { closeList(); const lv = h[1].length; html += '<h' + lv + '>' + renderInline(h[2]) + '</h' + lv + '>'; i++; continue; }
        // 引用（注意：此时 '>' 已被转义为 '&gt;'）
        if (/^&gt;\s?/.test(line)) {
          closeList();
          let quote = '';
          while (i < lines.length && /^&gt;\s?/.test(lines[i])) { quote += lines[i].replace(/^&gt;\s?/, '') + '\n'; i++; }
          html += '<blockquote>' + renderInline(quote.trim()).replace(/\n/g, '<br>') + '</blockquote>';
          continue;
        }
        // 有序列表
        const ol = line.match(/^\s*\d+\.\s+(.*)$/);
        if (ol) { if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + renderInline(ol[1]) + '</li>'; i++; continue; }
        // 无序列表
        const ul = line.match(/^\s*[-*+]\s+(.*)$/);
        if (ul) { if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + renderInline(ul[1]) + '</li>'; i++; continue; }
        // 空行
        if (/^\s*$/.test(line)) { closeList(); i++; continue; }
        // 普通段落（合并连续非空行）
        closeList();
        let para = line;
        i++;
        while (i < lines.length && !/^\s*$/.test(lines[i]) &&
               !/^(#{1,4}\s|&gt;\s?|```|\s*---\s*$|\s*\d+\.\s|\s*[-*+]\s)/.test(lines[i])) {
          para += '\n' + lines[i]; i++;
        }
        html += '<p>' + renderInline(para).replace(/\n/g, '<br>') + '</p>';
      }
      closeList();
      return html;
    }

    function addMessage(role, { text = '', imageUrl = null, id = null } = {}) {
      const msg = document.createElement('div');
      msg.className = 'msg ' + role;
      if (id) msg.dataset.msgId = id;
      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.textContent = role === 'user' ? '🙂' : '🤖';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      // 悬停删除按钮：欢迎语气泡（没有 id 时也挂上，但点击会 no-op）
      const delBtn = document.createElement('button');
      delBtn.className = 'del-msg';
      delBtn.title = '删除这条消息';
      delBtn.textContent = '🗑';
      delBtn.onclick = (e) => { e.stopPropagation(); deleteMessage(msg); };
      bubble.appendChild(delBtn);
      if (imageUrl) {
        const img = document.createElement('img');
        img.src = imageUrl;
        bubble.appendChild(img);
      }
      // 助手消息：思考区 + 工具区 + 正文区（三段结构，都可能为空）
      let thinking = null, tools = null;
      if (role === 'bot') {
        bubble.classList.add('md');
        thinking = createThinkingBlock();
        tools = createToolsBlock();
        bubble.appendChild(thinking.root);
        bubble.appendChild(tools.root);
      }
      // 正文容器：助手渲染 Markdown，用户保持纯文本
      const content = document.createElement('div');
      content.style.display = role === 'bot' ? 'block' : 'inline';
      if (role === 'bot') {
        if (text) content.innerHTML = renderMarkdown(text);
      } else {
        content.textContent = text;
      }
      bubble.appendChild(content);
      msg.appendChild(avatar);
      msg.appendChild(bubble);
      messagesEl.appendChild(msg);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return { msgEl: msg, bubble, content, thinking, tools };
    }

    // —— 单条消息删除：确认 → 调后端（同步删 message_store + 软删 checkpoint）→ 删 DOM ——
    async function deleteMessage(msgEl) {
      const id = msgEl.dataset.msgId;
      if (!id) return;   // 欢迎语等无 id 气泡不可删
      if (!confirm('删除这条消息？删除后 AI 将不再记得它。')) return;
      const form = new FormData();
      form.append('session_id', sessionId);
      form.append('message_id', id);
      try {
        const r = await fetch('/api/message/delete', { method: 'POST', body: form });
        const data = await r.json();
        if (data.ok) msgEl.remove();
      } catch (_) {}
    }

    // —— 思考区：一个可折叠的灰色小块，实时追加 reasoning delta ——
    function createThinkingBlock() {
      const root = document.createElement('details');
      root.className = 'thinking hidden';
      root.open = true;
      const summary = document.createElement('summary');
      summary.innerHTML = '<span class="dot"></span><span class="label">思考中…</span>';
      const body = document.createElement('div');
      body.className = 'thinking-body';
      root.appendChild(summary);
      root.appendChild(body);
      let acc = '';
      let started = null;
      return {
        root,
        append(delta) {
          if (started === null) started = performance.now();
          root.classList.remove('hidden');
          acc += delta;
          body.textContent = acc;
          messagesEl.scrollTop = messagesEl.scrollHeight;
        },
        finish() {
          if (started === null) return;               // 从未收到 reasoning
          const secs = Math.max(1, Math.round((performance.now() - started) / 1000));
          summary.querySelector('.label').textContent = `已思考 ${secs} 秒`;
          summary.querySelector('.dot').classList.add('done');
          root.open = false;                           // 结束后自动收起
        },
      };
    }

    // —— 工具区：一条工具一张小卡片，运行中转圈，结束后展示耗时 + 结果预览 ——
    function createToolsBlock() {
      const root = document.createElement('div');
      root.className = 'tools hidden';
      const cards = new Map();   // run_id -> {card, statusEl, outEl, startedAt}
      return {
        root,
        start({ id, name, input }) {
          root.classList.remove('hidden');
          const card = document.createElement('div');
          card.className = 'tool running';
          const inputStr = input ? JSON.stringify(input) : '';
          card.innerHTML =
            '<div class="tool-head">' +
              '<span class="spin"></span>' +
              '<span class="name">🔧 ' + escapeHtml(name || 'tool') + '</span>' +
              '<span class="args">' + escapeHtml(inputStr) + '</span>' +
              '<span class="status">运行中…</span>' +
            '</div>' +
            '<pre class="tool-out"></pre>';
          root.appendChild(card);
          const statusEl = card.querySelector('.status');
          const outEl = card.querySelector('.tool-out');
          outEl.style.display = 'none';
          cards.set(id, { card, statusEl, outEl, startedAt: performance.now() });
          messagesEl.scrollTop = messagesEl.scrollHeight;
        },
        end({ id, output }) {
          const c = cards.get(id);
          if (!c) return;
          const secs = ((performance.now() - c.startedAt) / 1000).toFixed(1);
          c.card.classList.remove('running');
          c.card.classList.add('done');
          c.card.querySelector('.spin')?.remove();
          c.statusEl.textContent = `完成 · ${secs}s`;
          const outStr = typeof output === 'string' ? output : JSON.stringify(output, null, 2);
          if (outStr && outStr !== 'null' && outStr !== '""') {
            c.outEl.textContent = outStr.length > 800 ? outStr.slice(0, 800) + ' …' : outStr;
            c.outEl.style.display = 'block';
          }
          messagesEl.scrollTop = messagesEl.scrollHeight;
        },
      };
    }

    // —— 从文本里抽取图片 URL（与后端 media.extract_image_urls 保持一致的规则）——
    //   A) Markdown ![alt](url)  B) <img src="url">
    //   C) 裸 URL 命中「扩展名 或 图床/CDN 主机白名单」
    const URL_TOKEN = /https?:\/\/[^\s<>"'，,、]+/g;
    const MD_IMAGE_RE = /!\[[^\]]*\]\((https?:\/\/[^\s<>"'，,、]+)\)/g;
    const HTML_IMG_RE = /<img\b[^>]*?\bsrc\s*=\s*['"](https?:\/\/[^\s<>"'，,、]+)['"][^>]*>/gi;
    const IMAGE_EXT_RE = /\.(?:jpg|jpeg|png|webp|gif|bmp|svg|avif|heic|heif|tiff)(?:$|[?#])/i;
    const IMAGE_HOST_SUFFIXES = [
      'imgur.com', 'sinaimg.cn', 'qpic.cn', 'qlogo.cn', 'hdslb.com',
      'cdn.discordapp.com', 'pbs.twimg.com',
    ];
    function looksLikeImageUrl(url) {
      if (IMAGE_EXT_RE.test(url)) return true;
      let u;
      try { u = new URL(url); } catch (_) { return false; }
      const host = (u.hostname || '').toLowerCase();
      if (IMAGE_HOST_SUFFIXES.some(s => host === s || host.endsWith('.' + s))) return true;
      if (host.endsWith('aliyuncs.com') && (u.search || '').includes('x-oss-process=image')) return true;
      if (host.endsWith('cloudinary.com') && (u.pathname || '').includes('/image/upload/')) return true;
      return false;
    }
    function extractImageUrls(text) {
      if (!text) return { text, urls: [] };
      const urls = [];
      const seen = new Set();
      const push = (u) => { if (u && !seen.has(u)) { seen.add(u); urls.push(u); } };
      let cleaned = text.replace(MD_IMAGE_RE, (_, u) => { push(u); return ''; });
      cleaned = cleaned.replace(HTML_IMG_RE, (_, u) => { push(u); return ''; });
      cleaned = cleaned.replace(URL_TOKEN, (u) => {
        if (looksLikeImageUrl(u)) { push(u); return ''; }
        return u;
      });
      cleaned = cleaned.replace(/[ \t]+/g, ' ').trim();
      return { text: cleaned, urls };
    }

    async function send() {
      const raw = textEl.value.trim();
      if (!raw && !selectedFile) return;

      // 优先展示用户本地选的图；否则从文本里抽第一个图片 URL 展示在气泡里
      const { text: cleanText, urls: pastedUrls } = extractImageUrls(raw);
      const bubbleImg = selectedFile
        ? URL.createObjectURL(selectedFile)
        : (pastedUrls[0] || null);
      const bubbleText = selectedFile ? raw : cleanText;

      addMessage('user', { text: bubbleText, imageUrl: bubbleImg });
      // 记录当前这条用户气泡，等 SSE 里 ids 帧下发后补 uuid
      const userMsgEl = messagesEl.lastElementChild;

      const form = new FormData();
      form.append('message', raw);      // 原始文本给后端（含 URL，后端会自行解析）
      form.append('session_id', sessionId);
      if (selectedFile) form.append('image', selectedFile);

      textEl.value = '';
      textEl.style.height = 'auto';
      selectedFile = null;
      fileInput.value = '';
      preview.style.display = 'none';
      sendBtn.disabled = true;

      const wasFirst = !dirty;  // 首条消息发送后需刷新列表（标题会更新）
      dirty = true;

      const { msgEl: botMsgEl, bubble, content, thinking, tools } = addMessage('bot', { text: '' });
      bubble.classList.add('streaming');
      let acc = '';  // 累积的最终正文 Markdown

      try {
        const resp = await fetch('/api/chat', { method: 'POST', body: form });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop();
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6);
            if (payload === '[DONE]') continue;
            let evt;
            try { evt = JSON.parse(payload); } catch (_) { continue; }
            // 事件类型分发；旧格式 {delta:"..."} 也兼容一下
            if (evt.type === 'reasoning' && evt.delta) {
              thinking.append(evt.delta);
            } else if (evt.type === 'tool_start') {
              tools.start(evt);
            } else if (evt.type === 'tool_end') {
              tools.end(evt);
            } else if (evt.type === 'ids') {
              // 成功跑完后的 uuid 下发：挂到当前两个气泡上，此后单条删除才可用
              if (evt.user_id && userMsgEl) userMsgEl.dataset.msgId = evt.user_id;
              if (evt.ai_id && botMsgEl) botMsgEl.dataset.msgId = evt.ai_id;
            } else if (evt.type === 'error') {
              acc += '\n\n[出错了：' + evt.message + ']';
              content.innerHTML = renderMarkdown(acc);
            } else {
              const delta = evt.type === 'delta' ? evt.text : evt.delta;
              if (delta) {
                acc += delta;
                content.innerHTML = renderMarkdown(acc) + '<span class="cursor"></span>';
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }
            }
          }
        }
        thinking.finish();
        content.innerHTML = renderMarkdown(acc);  // 收尾：去掉光标
      } catch (err) {
        thinking.finish();
        content.innerHTML = renderMarkdown(acc + '\n\n[出错了：' + err.message + ']');
      } finally {
        bubble.classList.remove('streaming');
        sendBtn.disabled = false;
        textEl.focus();
        if (wasFirst) loadSessions();  // 标题已生成，刷新侧边栏
      }
    }

    // —— 初始化：有历史会话则打开最近一个，否则新建一个 ——
    (async function init() {
      let sessions = [];
      try {
        const r = await fetch('/api/sessions');
        sessions = (await r.json()).sessions || [];
      } catch (_) {}
      if (sessions.length) {
        await switchSession(sessions[0].session_id);
      } else {
        await createSession();
      }
    })();
