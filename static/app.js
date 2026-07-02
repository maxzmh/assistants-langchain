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

    const WELCOME = '你好！我是你的美食家助手。问我任何做菜问题，也可以上传照片，或直接把图片链接贴在消息里让我帮你分析～';

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
          addMessage(m.role, { text: m.text, imageUrl: m.image });
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

    function addMessage(role, { text = '', imageUrl = null } = {}) {
      const msg = document.createElement('div');
      msg.className = 'msg ' + role;
      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.textContent = role === 'user' ? '🙂' : '🍳';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      if (imageUrl) {
        const img = document.createElement('img');
        img.src = imageUrl;
        bubble.appendChild(img);
      }
      // 内容容器：助手消息渲染 Markdown，用户消息保持纯文本
      const content = document.createElement('div');
      content.style.display = 'inline';
      if (role === 'bot') {
        bubble.classList.add('md');
        content.style.display = 'block';
        if (text) content.innerHTML = renderMarkdown(text);
      } else {
        content.textContent = text;
      }
      bubble.appendChild(content);
      msg.appendChild(avatar);
      msg.appendChild(bubble);
      messagesEl.appendChild(msg);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return { bubble, content };
    }

    // —— 从文本里抽取图片 URL（与后端 _IMAGE_URL_RE 保持一致的规则）——
    const IMAGE_URL_RE = /https?:\/\/[^\s<>"'，,、]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\s<>"'，,、]*)?/gi;
    function extractImageUrls(text) {
      const urls = (text || '').match(IMAGE_URL_RE) || [];
      if (!urls.length) return { text, urls: [] };
      const cleaned = text.replace(IMAGE_URL_RE, '').trim();
      return { text: cleaned, urls: [...new Set(urls)] };
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

      const { bubble, content } = addMessage('bot', { text: '' });
      bubble.classList.add('streaming');
      let acc = '';  // 累积的原始 Markdown 文本

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
            try {
              const { delta } = JSON.parse(payload);
              acc += delta;
              // 流式过程中实时渲染 Markdown，并在末尾显示闪烁光标
              content.innerHTML = renderMarkdown(acc) + '<span class="cursor"></span>';
              messagesEl.scrollTop = messagesEl.scrollHeight;
            } catch (_) {}
          }
        }
        content.innerHTML = renderMarkdown(acc);  // 收尾：去掉光标
      } catch (err) {
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
