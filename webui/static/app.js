// ===== TrueAgent v5.9 WebUI 前端 =====
const $ = id => document.getElementById(id);

// ===== 状态 =====
let isProcessing = false;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let dashTimer = null;
let currentSession = localStorage.getItem('trueagent_session') || 'default';
let sessions = [];

// ===== 自动排队 =====
let messageQueue = [];  // {text, el, id}
let _qid = 0;

function renderQueueBar() {
  // 移除旧排队条
  document.querySelectorAll('.queue-item').forEach(el => el.remove());
  if (messageQueue.length === 0) return;
  // 在最后一条用户消息后插入排队条
  const msgs = $('messages').querySelectorAll('.message');
  let anchor = null;
  for (let i = msgs.length-1; i >=0; i--) {
    if (msgs[i].classList.contains('msg-user') || msgs[i].classList.contains('queue-item')) {
      anchor = msgs[i]; break;
    }
  }
  messageQueue.forEach((q, i) => {
    const div = document.createElement('div');
    div.className = 'message queue-item';
    div.id = 'queue-' + q.id;
    div.innerHTML = '<div class="queue-bubble">'
      + '<span class="queue-label">排队 #' + (i+1) + '</span>'
      + '<span class="queue-text">' + escHtml(q.text.substring(0,80)) + '</span>'
      + '<button class="queue-cancel" data-qid="' + q.id + '">✕</button>'
      + '</div>';
    if (anchor) anchor.after(div);
    else $('messages').appendChild(div);
    anchor = div;
  });
  scrollToBottom();
  // 绑定取消
  document.querySelectorAll('.queue-cancel').forEach(btn => {
    btn.onclick = function(e) {
      e.stopPropagation();
      const qid = parseInt(this.dataset.qid);
      messageQueue = messageQueue.filter(q => q.id !== qid);
      renderQueueBar();
    };
  });
}

async function dequeueNext() {
  if (messageQueue.length === 0) return;
  const next = messageQueue.shift();
  renderQueueBar();
  await sendMessageDirect(next.text);
  // 继续下一个
  if (messageQueue.length > 0 && !isProcessing) dequeueNext();
}

// ===== 主题 =====
let isLightTheme = localStorage.getItem('trueagent_theme') === 'light';
function toggleTheme() {
  isLightTheme = !isLightTheme;
  document.body.classList.toggle('light-theme', isLightTheme);
  localStorage.setItem('trueagent_theme', isLightTheme ? 'light' : 'dark');
  $('themeBtn').textContent = isLightTheme ? '\u2600' : '\uD83C\uDF19';
}
if (isLightTheme) { document.body.classList.add('light-theme'); $('themeBtn').textContent = '\u2600'; }
$('themeBtn').addEventListener('click', toggleTheme);

// ===== 侧面板折叠 =====
let sidebarVisible = localStorage.getItem('trueagent_sidebar') !== 'hidden';
function toggleSidebar() {
  sidebarVisible = !sidebarVisible;
  $('left-panel').classList.toggle('collapsed', !sidebarVisible);
  localStorage.setItem('trueagent_sidebar', sidebarVisible ? 'visible' : 'hidden');
}
$('sidebarToggle').addEventListener('click', toggleSidebar);
if (!sidebarVisible) $('left-panel').classList.add('collapsed');

// ===== 面板区块折叠（事件委托，稳定可靠）=====
document.addEventListener('click', function(e) {
  var hdr = e.target.closest('.section-header');
  if (!hdr) return;
  var bodyId = 'sec-' + hdr.dataset.section;
  var body = $(bodyId);
  hdr.classList.toggle('collapsed');
  if (body) body.classList.toggle('hidden');
  localStorage.setItem('trueagent_section_' + hdr.dataset.section,
    hdr.classList.contains('collapsed') ? 'collapsed' : 'open');
});

// 恢复折叠状态
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.section-header').forEach(function(hdr) {
    var saved = localStorage.getItem('trueagent_section_' + hdr.dataset.section);
    if (saved === 'collapsed') {
      hdr.classList.add('collapsed');
      var body = $('sec-' + hdr.dataset.section);
      if (body) body.classList.add('hidden');
    }
  });
});

// ===== 核心工具库 =====
async function loadSessions() {
  try {
    const r = await fetch('/api/conversations');
    const d = await r.json();
    sessions = d.sessions || [];
    renderSessionList();
  } catch(e) {}
}

function renderSessionList() {
  const list = $('sessionList');
  if (!list) return;
  list.innerHTML = sessions.map(s => `
    <div class="session-item ${s.id === currentSession ? 'active' : ''}" data-sid="${s.id}">
      <span class="session-title">${s.title}</span>
      <button class="del-btn" data-sid="${s.id}">✅?/button>
    </div>
  `).join('');

  // 点击切换会话
  list.querySelectorAll('.session-item').forEach(el => {
    el.addEventListener('click', e => {
      if (e.target.classList.contains('del-btn')) return;
      switchSession(el.dataset.sid);
    });
  });
  // 删除会话
  list.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const sid = btn.dataset.sid;
      if (sid === currentSession) return;
      await fetch(`/api/conversations/${sid}`, {method:'DELETE'});
      loadSessions();
    });
  });
}

async function switchSession(sid) {
  if (sid === currentSession) return;
  currentSession = sid;
  localStorage.setItem('trueagent_session', sid);
  renderSessionList();
  await loadHistory();
}

async function newSession() {
  try {
    const r = await fetch('/api/conversations/new', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title: `会话 ${sessions.length+1}`})
    });
    const d = await r.json();
    currentSession = d.session_id;
    localStorage.setItem('trueagent_session', currentSession);
    // 清空消息区域
    $('messages').innerHTML = '';
    addMessage('system', '💬 新会话已创建');
    await loadSessions();
  } catch(e) {}
}

// ===== 加载历史 =====
async function loadHistory() {
  $('messages').innerHTML = '';
  try {
    const r = await fetch(`/api/conversations/${currentSession}`);
    const d = await r.json();
    if (d.messages && d.messages.length) {
      d.messages.forEach(m => {
        if (m.role === 'user') addMessage('user', m.content);
        else if (m.role === 'assistant') addMessage('agent', m.content);
      });
      addMessage('system', 'Loaded ' + d.messages.length + ' history messages');
    } else {
      addMessage('system', 'New session');
    }
  } catch(e) {
    addMessage('system', 'New session');
  }
}

// ===== @ 自动补全 =====
var atMentionTimer = null;
var atMenuVisible = false;
var atMenuSelected = 0;
var atMenuAgents = [];

function showAtMenu(agents, atIdx, cursorPos) {
  atMenuAgents = agents;
  atMenuSelected = 0;
  atMenuVisible = true;
  
  var existing = $('at-menu');
  if (!existing) {
    existing = document.createElement('div');
    existing.id = 'at-menu';
    existing.className = 'at-menu';
    document.getElementById('input-bar').appendChild(existing);
  }
  
  existing.innerHTML = agents.map(function(a, i) {
    return '<div class="at-item' + (i === 0 ? ' selected' : '') + '" data-idx="' + i + '">' +
      '<span class="at-name">' + a.alias + '</span>' +
      '<span class="at-id">' + a.id + '</span></div>';
  }).join('');
  existing.style.display = 'block';
  
  existing.querySelectorAll('.at-item').forEach(function(el) {
    el.addEventListener('click', function() {
      atMenuSelected = parseInt(el.dataset.idx);
      selectAtMention();
    });
    el.addEventListener('mouseenter', function() {
      atMenuSelected = parseInt(el.dataset.idx);
      updateAtMenuSelection();
    });
  });
}

function hideAtMenu() {
  atMenuVisible = false;
  var el = $('at-menu');
  if (el) el.style.display = 'none';
}

function updateAtMenuSelection() {
  var el = $('at-menu');
  if (!el) return;
  el.querySelectorAll('.at-item').forEach(function(item, i) {
    item.className = 'at-item' + (i === atMenuSelected ? ' selected' : '');
  });
}

function selectAtMention() {
  if (!atMenuVisible || !atMenuAgents.length) return;
  var selected = atMenuAgents[atMenuSelected];
  var input = $('inputText');
  var text = input.value;
  var cursor = input.selectionStart;
  
  var beforeCursor = text.substring(0, cursor);
  var afterCursor = text.substring(cursor);
  var atIdx = beforeCursor.lastIndexOf('@');
  
  // 替换 @xxx 涓?@agent_id + 空格
  var newText = text.substring(0, atIdx) + '@' + selected.id + ' ' + afterCursor;
  input.value = newText;
  input.selectionStart = input.selectionEnd = atIdx + selected.id.length + 2;
  input.focus();
  hideAtMenu();
}

// ===== 黑板通道 Orchestrator 发言 =====
async function sendBlackboardViaOrchestrator(text) {
  if (!text.trim() || isProcessing) return;
  isProcessing = true;
  
  addMessage('user', text);
  $('inputText').value = '';
  $('inputText').style.height = 'auto';
  
  try {
    var r = await fetch('/api/orchestrator/speak', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        from_id: 'agent_main',
        content: text
      })
    });
    var d = await r.json();
    if (d.success) {
      var route = d.route;
      var target = route.target === '__public__' ? '全体' : getCloneName(target);
      addMessage('system', '[黑板] 消息已发送(目标: ' + target + ')');
      
      if (d.mentions && d.mentions.length) {
        d.mentions.forEach(function(m) {
          addMessage('system', '[@] 已通知 ' + getCloneName(m));
        });
      }
    } else {
      addMessage('error', '[黑板发言失败] ' + (d.error || ''));
    }
  } catch(e) {
    addMessage('error', '请求异常: ' + e.message);
  }
  
  isProcessing = false;
  $('sendBtn').disabled = false;
  $('stopBtn').disabled = true;
  $('inputText').focus();
}

// ===== 发言统计轮询 =====
var speakStatsTimer = null;

function startSpeakStats() {
  speakStatsTimer = setInterval(pollSpeakStats, 5000);
}

async function pollSpeakStats() {
  try {
    var r = await fetch('/api/orchestrator/stats');
    var d = await r.json();
    if (!d.success) return;
    var data = d.data;
    
    // 更新标签栏上的 @ 通知 badge
    var pings = await fetch('/api/orchestrator/pings?agent_id=agent_main');
    var pd = await pings.json();
    if (pd.success && pd.pings && pd.pings.length) {
      var badge = $('ping-badge');
      if (!badge) {
        badge = document.createElement('span');
        badge.id = 'ping-badge';
        badge.className = 'ping-badge';
        var bbTab = document.querySelector('.agent-tab[data-agent="__blackboard__"]');
        if (bbTab) bbTab.appendChild(badge);
      }
      badge.textContent = pd.pings.length;
    } else {
      var badge = $('ping-badge');
      if (badge) badge.remove();
    }
    
    // 更新侧栏发言状?
    var statsEl = $('speak-stats');
    if (statsEl && data.priority && data.speak_counts) {
      statsEl.innerHTML = Object.entries(data.speak_counts)
        .sort(function(a, b) { return (data.penalty_scores[a[0]] || 0) - (data.penalty_scores[b[0]] || 0); })
        .map(function(entry) {
          var id = entry[0];
          var count = entry[1];
          var can = true;
          if (data.my && data.my.can_speak) can = data.my.can_speak[0];
          return '<div class="speak-row' + (id === 'agent_main' ? ' self' : '') + '">' +
            '<span class="speak-name">' + getCloneName(id) + '</span>' +
            '<span class="speak-count">' + count + '次?/span>' +
            '<span class="speak-penalty" style="width:' + Math.min((data.penalty_scores[id] || 0) * 5, 100) + 'px"></span>' +
            '</div>';
        }).join('');
    }
  } catch(e) {}
}

// ===== 强制停止 =====
async function stopProcessing() {
  try {
    $('stopBtn').disabled = true;
    await fetch('/api/stop', {method:'POST'});
    addMessage('system', 'Stop signal sent');
    isProcessing = false;
    $('sendBtn').disabled = false;
    const ti = $('typing-indicator');
    if (ti) ti.remove();
  } catch(e) {}
}

// ===== 主动消息轮询 =====
async function pollProactive() {
  try {
    const r = await fetch('/api/proactive');
    const d = await r.json();
    if (d.messages && d.messages.length) {
      d.messages.forEach(m => {
        const content = m.content || '';
        const type = m.type || '';
        // 审批类消息不显示在聊天区（审批面板自己轮询）
        if (type === 'approval_request' || type === 'approval_result') return;
        if (type === 'clone_result') {
          addProactive('🤖 分身汇报', content);
        } else if (type === 'health_alert') {
          addProactive('⚠️ 健康提醒', content);
        } else if (type === 'evolution') {
          addProactive('📈 进化', content);
        } else {
          addProactive('📡 系统', content);
        }
      });
    }
  } catch(e) {}
}

// 主动消息专用渲染：比普通系统消息更醒目
function addProactive(title, content) {
  const div = document.createElement('div');
  div.className = 'message msg-proactive';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble proactive-bubble';
  // 换行符转 <br>，保留普通文本格式
  const safeContent = escapeHtml(content).replace(/\n/g, '<br>');
  bubble.innerHTML = '<div class="proactive-title">' + escapeHtml(title) + '</div>' +
    '<div class="proactive-body">' + safeContent + '</div>';
  div.appendChild(bubble);
  $('messages').appendChild(div);
  scrollToBottom();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 页面加载时拉取历史主动消息
async function loadProactiveHistory() {
  try {
    const r = await fetch('/api/proactive-history');
    const d = await r.json();
    if (d.messages && d.messages.length) {
      d.messages.forEach(m => {
        const content = m.content || '';
        if (content.indexOf('🧠') === 0) {
          addProactive('🧠 认知', content.substring(2));
        } else if (content.indexOf('📄') === 0) {
          addProactive('📄 整理', content.substring(3));
        } else {
          addProactive('📡 系统', content);
        }
      });
    }
  } catch(e) {}
}

// ===== 消息系统 =====
const MAX_MESSAGES = 300;  // DOM中最多保留300条消息
let _prunedCount = 0;

function addMessage(role, content) {
  // 自动裁剪旧消息（保留最近300条，超出时删最旧的）
  const allMsgs = $('messages').querySelectorAll('.message:not(.queue-item)');
  if (allMsgs.length >= MAX_MESSAGES) {
    const toRemove = allMsgs.length - MAX_MESSAGES + 1;
    for (let i = 0; i < toRemove; i++) {
      if (allMsgs[i]) allMsgs[i].remove();
    }
    _prunedCount += toRemove;
    // 插入提示条
    let tip = document.getElementById('prune-tip');
    if (!tip) {
      tip = document.createElement('div');
      tip.id = 'prune-tip';
      tip.className = 'message msg-system';
      tip.innerHTML = '<div class="msg-bubble" style="opacity:0.5;font-size:10px;text-align:center">📜 已自动隐藏旧消息</div>';
      const first = $('messages').querySelector('.message');
      if (first) first.before(tip);
    } else {
      tip.querySelector('.msg-bubble').textContent = '📜 已自动隐藏 ' + _prunedCount + ' 条旧消息（保留最近 ' + MAX_MESSAGES + ' 条）';
    }
  }

  const div = document.createElement('div');
  div.className = `message msg-${role}`;
  const time = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = new Date().toLocaleTimeString();
  div.appendChild(time);
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (role === 'user') {
    bubble.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
  } else if (role === 'user-img') {
    // 用户上传的图片预览
    bubble.className = 'msg-bubble msg-img';
    bubble.innerHTML = `<img src="${content}" style="max-width:100%; max-height:400px; border-radius:8px; cursor:pointer" onclick="window.open('${content}')" alt="用户上传图片">`;
  } else if (role === 'error') {
    bubble.innerHTML = escapeHtml('❌ ' + content).replace(/\n/g, '<br>');
  } else if (role === 'system') {
    // 系统消息保留换行格式
    bubble.style.opacity = '0.7';
    bubble.style.fontSize = '11px';
    bubble.innerHTML = escapeHtml(content).replace(/\n/g, '<br>');
  } else {
    bubble.innerHTML = markedParse(content);
    // Copy button
    const cb = document.createElement('button');
    cb.className = 'copy-btn';
    cb.textContent = 'Copy';
    cb.addEventListener('click', function() {
      navigator.clipboard.writeText(content).then(() => {
        this.textContent = 'Copied!';
        this.classList.add('copied');
        setTimeout(() => { this.textContent = 'Copy'; this.classList.remove('copied'); }, 2000);
      }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = content; document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
        this.textContent = 'Copied!'; this.classList.add('copied');
        setTimeout(() => { this.textContent = 'Copy'; this.classList.remove('copied'); }, 2000);
      });
    });
    bubble.appendChild(cb);
  }
  div.appendChild(bubble);
  $('messages').appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  const p = $('chat-panel');
  if (p) p.scrollTop = p.scrollHeight;
}

// ===== Markdown =====
function escapeHtml(t) {
  const m = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'};
  return t.replace(/[&<>"']/g, c => m[c]);
}
function inlineFormat(t) {
  return t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          .replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
}
function markedParse(text) {
  if (!text) return '';
  let h = escapeHtml(text);
  h = h.replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => {
    const lc = l ? ` class="language-${l}"` : '';
    return `<pre><code${lc}>${escapeHtml(c.trim())}</code></pre>`;
  });
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/\n\|(.+)\|\n\|[-| :]+\|\n((?:\|.+\|\n?)*)/g, m => {
    const ls = m.trim().split('\n'); if (ls.length<2) return m;
    let tbl = '<table><thead><tr>';
    const hdrs = ls[0].split('|').filter(c=>c.trim()).map(c=>inlineFormat(c.trim()));
    tbl += hdrs.map(h=>`<th>${h}</th>`).join('')+'</tr></thead>';
    if (ls.length>2) {
      tbl += '<tbody>';
      for (let i=2;i<ls.length;i++) {
        const cells = ls[i].split('|').filter(c=>c.trim()).map(c=>inlineFormat(c.trim()));
        if (cells.length) tbl += '<tr>'+cells.map(c=>`<td>${c}</td>`).join('')+'</tr>';
      }
      tbl += '</tbody>';
    }
    return tbl+'</table>';
  });
  h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>').replace(/^## (.+)$/gm, '<h2>$1</h2>').replace(/^# (.+)$/gm, '<h1>$1</h1>');
  h = h.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
  h = h.replace(/^[-*] (.+)$/gm, '<li>$1</li>').replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  h = h.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  h = h.replace(/(<li>.*<\/li>\n?)+/g, m => m.includes('<ul>') ? m : '<ol>'+m+'</ol>');
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\*(.+?)\*/g, '<em>$1</em>');
  h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  h = h.replace(/\n\n+/g, '</p><p>').replace(/\n/g, '<br>');
  h = '<p>'+h+'</p>'.replace(/<p><\/p>/g,'').replace(/<br><\/p>/g,'</p>');
  return h;
}

// ===== 发送消息 =====
// 直接发送（供队列调用，不检查队列模式）
async function sendMessageDirect(text) {
  if (!text.trim() || isProcessing) return;
  isProcessing = true; $('sendBtn').disabled = true;
  $('stopBtn').disabled = false;

  addMessage('user', text);
  $('inputText').value = ''; $('inputText').style.height = 'auto';

  const td = document.createElement('div');
  td.className = 'message msg-agent'; td.id = 'typing-indicator';
  td.innerHTML = '<div class="msg-bubble typing-dots"><span>·</span><span>·</span><span>·</span></div>';
  $('messages').appendChild(td); scrollToBottom();

  try {
    const r = await fetch('/api/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text, session: currentSession})
    });
    const d = await r.json();
    const ti = $('typing-indicator'); if (ti) ti.remove();
    if (d.error) addMessage('error', d.error);
    else {
      addMessage('agent', d.reply || '(无响应)');
      if (d.files && d.files.length) {
        const fm = document.createElement('div');
        fm.className = 'message msg-system';
        fm.innerHTML = `<div class="msg-bubble" style="opacity:0.7;font-size:11px">📄 生成 ${d.files.length} 个文件</div>`;
        $('messages').appendChild(fm);
        d.files.forEach(f => {
          const ext = f.name.split('.').pop().toLowerCase();
          const sz = f.size>1024 ? (f.size/1024).toFixed(1)+'KB' : f.size+'B';
          const fd = document.createElement('div');
          
          if (['png','jpg','jpeg','gif','webp','svg'].includes(ext)) {
            // 图片 → 内联预览 + 下载
            fd.className = 'message msg-agent';
            fd.innerHTML = `<div class="msg-bubble file-preview">
              <img src="${f.url}" style="max-width:100%; max-height:360px; border-radius:8px; cursor:pointer" 
                   onclick="window.open('${f.url}')" alt="${f.name}">
              <div class="file-meta">📷 ${f.name} · ${sz} <a href="${f.url}" download="${f.name}" class="download-link">⬇ 下载</a></div>
            </div>`;
          } else if (['mp3','wav','ogg','m4a','aac'].includes(ext)) {
            // 音频 → 播放器 + 下载
            fd.className = 'message msg-agent';
            fd.innerHTML = `<div class="msg-bubble file-preview">
              <audio controls style="width:100%;max-width:400px"><source src="${f.url}"></audio>
              <div class="file-meta">🎵 ${f.name} · ${sz} <a href="${f.url}" download="${f.name}" class="download-link">⬇ 下载</a></div>
            </div>`;
          } else if (['mp4','webm','mov'].includes(ext)) {
            // 视频 → 播放器 + 下载
            fd.className = 'message msg-agent';
            fd.innerHTML = `<div class="msg-bubble file-preview">
              <video controls style="max-width:100%; max-height:400px; border-radius:8px"><source src="${f.url}"></video>
              <div class="file-meta">🎬 ${f.name} · ${sz} <a href="${f.url}" download="${f.name}" class="download-link">⬇ 下载</a></div>
            </div>`;
          } else {
            // 其他文件 → 下载链接
            fd.className = 'message msg-agent';
            fd.innerHTML = `<div class="msg-bubble file-download"><a href="${f.url}" download="${f.name}" class="download-link">📥 <span class="file-name">${f.name}</span><span class="file-size">${sz}</span><span class="download-btn">⬇ 下载</span></a></div>`;
          }
          $('messages').appendChild(fd);
        });
        scrollToBottom();
      }
    }
  } catch(e) {
    const ti = $('typing-indicator'); if (ti) ti.remove();
    addMessage('error', '网络错误: '+e.message);
  }

  isProcessing = false;
  $('sendBtn').disabled = false;
  $('stopBtn').disabled = true;
  $('inputText').focus();

  // 自动出队：继续处理下一个排队消息
  dequeueNext();
}

// 自动排队的发送入口
async function sendMessage(text) {
  if (!text.trim()) return;
  if (isProcessing) {
    // 自动入队
    messageQueue.push({text, id: ++_qid});
    renderQueueBar();
    return;
  }
  await sendMessageDirect(text);
}

// ===== 事件绑定 =====
function doSend() {
  var text = $('inputText').value;
  if (!text.trim()) return;
  $('inputText').value = ''; $('inputText').style.height = 'auto';
  // v5.9: 无黑板/分身切换，始终走主智能体通道
  sendMessage(text);
}
$('inputText').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
});
$('sendBtn').addEventListener('click', doSend);
$('inputText').addEventListener('input', () => {
  $('inputText').style.height = 'auto';
  $('inputText').style.height = Math.min($('inputText').scrollHeight, 200)+'px';
});
$('stopBtn').addEventListener('click', stopProcessing);
$('newSessionBtn').addEventListener('click', newSession);

// ===== 文件上传（支持图片预览 + OCR + 文本）=====
$('attachBtn').addEventListener('click', () => $('fileInput').click());
$('fileInput').addEventListener('change', async () => {
  const files = $('fileInput').files;
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  addMessage('system', `📦 正在上传 ${files.length} 个文件...`);
  try {
    const r = await fetch('/api/upload', {method:'POST', body:fd});
    const d = await r.json();
    if (d.error) { addMessage('error', d.error); }
    else {
      if (d.images && d.images.length) {
        d.images.forEach(url => addMessage('user-img', url));
      }
      if (d.reply) addMessage('agent', d.reply);
    }
  } catch(e) { addMessage('error', '上传失败: '+e.message); }
  $('fileInput').value = '';
});

// ===== Screenshot OCR =====
$('screenshotBtn').addEventListener('click', async () => {
  addMessage('system', 'Taking screenshot...');
  try {
    const r = await fetch('/api/screenshot-ocr', {method:'POST'});
    const d = await r.json();
    if (d.error) addMessage('error', d.error);
    else addMessage('user', '[Screenshot OCR]\n' + (d.text||'(no text)'));
  } catch(e) { addMessage('error', 'Screenshot failed: '+e.message); }
});

// ===== 语音 =====
function showVoice() { $('voiceModal').style.display = 'flex'; }
function hideVoice() { $('voiceModal').style.display = 'none'; isRecording = false; }
$('voiceBtn').addEventListener('click', showVoice);
$('voiceCancelBtn').addEventListener('click', hideVoice);
$('voiceRecordBtn').addEventListener('click', async () => {
  if (isRecording) { mediaRecorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const blob = new Blob(audioChunks, {type:'audio/wav'});
      const fd = new FormData(); fd.append('audio', blob, 'voice.wav');
      $('voiceStatus').textContent = '正在识别...';
      try {
        const r = await fetch('/api/transcribe', {method:'POST', body:fd});
        const d = await r.json();
        if (d.text) { $('inputText').value = d.text; hideVoice(); $('inputText').dispatchEvent(new Event('input')); $('inputText').focus(); }
        else $('voiceStatus').textContent = '识别失败，请重试';
      } catch(e) { $('voiceStatus').textContent = '错误: '+e.message; }
      stream.getTracks().forEach(t => t.stop());
    };
    mediaRecorder.start(); isRecording = true;
    $('voiceRecordBtn').textContent = '🔴 停止';
    $('voiceStatus').textContent = '录音中...';
  } catch(e) { $('voiceStatus').textContent = '无法录音: '+e.message; }
});

// ===== 仪表盘轮询 =====
function startDashboard() {
  if (dashTimer) clearInterval(dashTimer);
  updateDashboard();
  dashTimer = setInterval(updateDashboard, 10000);
}
async function updateDashboard() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (!d || d.error) { console.warn('[浠仪〃鐩榏 状错?', d?.error); return; }
    $('statusDot').style.color = d.running ? 'var(--success)' : 'var(--error)';
    $('statusText').textContent = d.running ? 'Running' : 'Stopped';
    const up = (v) => { if (v !== undefined && v !== null) return v; return '-'; };
    setDash('dash-model', up(d.model_name));
    setDash('dash-cpu', up(d.cpu_usage != null ? d.cpu_usage.toFixed(0)+'%' : '-'));
    setDash('dash-mem', up(d.mem_usage != null ? d.mem_usage.toFixed(0)+'MB' : '-'));
    setDash('dash-tools', up(d.tool_calls));
    setDash('dash-api', up(d.api_calls));
    setDash('dash-conv', up(d.conversation_count));
    setDash('dash-uptime', up(d.uptime));
    setDash('dash-energy', up(d.energy_level != null ? d.energy_level.toFixed(2) : '-'));
    if (d.cpu_usage != null) { $('dash-cpu-bar').style.width = Math.min(d.cpu_usage,100)+'%'; }
    if (d.mem_usage != null && d.mem_total) {
      $('dash-mem-bar').style.width = Math.min((d.mem_usage/d.mem_total)*100,100)+'%';
    }
    if (d.kg_nodes) setDash('dash-kg-nodes', d.kg_nodes);
    if (d.kg_edges) setDash('dash-kg-edges', d.kg_edges);
    if (d.causal_count) setDash('dash-causal', d.causal_count);
    if (d.mem_working) setDash('dash-mem-work', d.mem_working);
    if (d.mem_long) setDash('dash-mem-long', d.mem_long);
    if (d.traces) setDash('dash-traces', d.traces);
    if (d.avg_quality) setDash('dash-quality', d.avg_quality);
    if (d.anchors) setDash('dash-anchors', d.anchors);
    if (d.evolution) setDash('dash-evolution', d.evolution);
    if (d.knowledge_hits) setDash('dash-kb', d.knowledge_hits);
    if (d.model_name && d.model_name !== $('cfg-model').textContent) {
      $('cfg-model').textContent = d.model_name;
    }
    
    // 更新运行模式指示（前端无 mode-dot/mode-label 元素，已停用）
    // updateModeIndicator(d);
  } catch(e) {}
}
function updateModeIndicator(d) {
  var dot = document.getElementById('mode-dot');
  var label = document.getElementById('mode-label');
  if (dot && label) {
    // /api/status 不返回 mode，单独从 /api/mode 获取
    fetch('/api/mode')
      .then(function(r) { return r.json(); })
      .then(function(m) {
        if (m.single_instance) {
          dot.textContent = '🟢';
          label.textContent = '单实例模式';
        } else {
          dot.textContent = '🟡';
          label.textContent = '多实例模式（高阶）';
        }
      })
      .catch(function() {});
  }
}
function setDash(id, val) {
  const el = $(id);
  if (el) el.textContent = val;
}

// ===== 成长趋势图表 =====
let trendTimer = null;
function startTrendChart() {
  updateTrendChart();
  trendTimer = setInterval(updateTrendChart, 120000); // 姣?分钟更新
}
async function updateTrendChart() {
  try {
    const r = await fetch('/api/trends');
    const d = await r.json();
    if (!d.trends || d.trends.length < 2) {
      const el = $('trendLegend');
      if (el) el.textContent = '暂无数据（系统运行后将自动累积）';
      return;
    }
    renderTrendChart(d.trends);
  } catch(e) {}
}
function renderTrendChart(data) {
  const canvas = $('trendChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width = Math.max(canvas.offsetWidth * 2, 400);
  const H = canvas.height = Math.max(canvas.offsetHeight * 2, 200);
  ctx.clearRect(0, 0, W, H);

  if (!data || data.length < 2) {
    ctx.fillStyle = 'rgba(255,255,255,0.3)';
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('📈 运行几分钟后将自动累积数据', W/2, H/2);
    const legend = $('trendLegend');
    if (legend) legend.textContent = '暂无数据（系统运行后将自动累积）';
    return;
  }

  // 提取数据
  const causal = data.map(p => p.causal || 0);
  const kgNodes = data.map(p => p.kg_nodes || 0);
  const memLong = data.map(p => p.mem_long || 0);
  const kbHits = data.map(p => p.knowledge_hits || 0);
  const cpuVals = data.map(p => p.cpu_usage || 0);
  const energyVals = data.map(p => p.energy_level || 0);

  const padding = { top: 20, right: 20, bottom: 28, left: 40 };
  const plotW = W - padding.left - padding.right;
  const plotH = H - padding.top - padding.bottom;

  // Y轴双刻度：左轴（绝对数量），右轴（0-100 百分比/0-1 能量）
  const allCounts = [...causal, ...kgNodes, ...memLong, ...kbHits].filter(v => v > 0);
  const yMax = Math.max(1, ...allCounts) * 1.15;
  const xStep = plotW / Math.max(1, data.length - 1);

  function drawLine(values, color, dashed, useRightAxis) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    if (dashed) ctx.setLineDash([4, 3]);
    else ctx.setLineDash([]);
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = padding.left + i * xStep;
      let y;
      if (useRightAxis) {
        // 右轴：CPU(0-100) 或 能量(0-1)
        const maxVal = Math.max(...values.filter(v => v > 0), 1);
        y = padding.top + plotH - (v / (maxVal * 1.1)) * plotH;
      } else {
        y = padding.top + plotH - (v / yMax) * plotH;
      }
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // 网格
  ctx.strokeStyle = 'rgba(255,255,255,0.06)';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (plotH / 4) * i;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(W - padding.right, y); ctx.stroke();
  }

  // 左轴：数量折线
  drawLine(causal, '#f59e0b', false, false);     // 因果链 橙
  drawLine(kgNodes, '#3b82f6', false, false);     // 知识节点 蓝
  drawLine(memLong, '#10b981', false, false);     // 长期记忆 绿
  drawLine(kbHits, '#ef4444', false, false);      // 知识命中 红
  // 右轴：百分比/比率折线（虚线）
  drawLine(cpuVals, '#a78bfa', true, true);      // CPU% 紫虚线
  drawLine(energyVals, '#fbbf24', true, true);   // 能量 金虚线

  // 图例
  const legend = $('trendLegend');
  if (legend) {
    const last = (arr) => (arr && arr.length) ? arr[arr.length - 1] : 0;
    legend.innerHTML =
      '<span style="color:#f59e0b">🔍 因果 ' + last(causal) + '</span>' +
      '<span style="color:#3b82f6">🧩 节点 ' + last(kgNodes) + '</span>' +
      '<span style="color:#10b981">📚 记忆 ' + last(memLong) + '</span>' +
      '<span style="color:#ef4444">🎯 命中 ' + last(kbHits) + '</span>' +
      '<span style="color:#a78bfa;opacity:0.7">··· CPU ' + last(cpuVals) + '%</span>' +
      '<span style="color:#fbbf24;opacity:0.7">⚡ 能量 ' + (typeof last(energyVals) === 'number' ? last(energyVals).toFixed(2) : '0') + '</span>';
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 俱ꔹ批UI =====
let approvalTimer = null;
function startApprovalPolling() {
  pollApprovals();
  approvalTimer = setInterval(pollApprovals, 5000);
}
async function pollApprovals() {
  try {
    const r = await fetch('/api/pending-modify');
    const d = await r.json();
    renderApprovals(d.proposals || []);
  } catch(e) {}
}
function renderApprovals(proposals) {
  const list = $('approvalList');
  if (!list) return;
  if (!proposals.length) {
    list.style.display = 'none';
    return;
  }
  list.style.display = '';
  list.innerHTML = proposals.map(p => {
    const remaining = Math.max(0, Math.round((p.expire - Date.now()/1000) / 60));
    return '<div class="approval-item">' +
      '<div class="approval-title">' + (p.summary || 'System modify') + '</div>' +
      '<div class="approval-detail">' + ((p.analysis || '').slice(0,200)) + '</div>' +
      '<div class="approval-actions">' +
        '<span class="approval-remaining">' + remaining + 'min auto-decide</span>' +
        '<button class="approval-btn approve" onclick="sendDecision(\'' + p.id + '\',\'approve\')">Approve</button>' +
        '<button class="approval-btn reject" onclick="sendDecision(\'' + p.id + '\',\'reject\')">Reject</button>' +
      '</div>' +
    '</div>';
  }).join('');
}
async function sendDecision(id, decision) {
  const btn = event?.target;
  if (btn) btn.disabled = true;  // 防连击
  try {
    await fetch('/api/modify-decision', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({proposal_id: id, decision})
    });
    pollApprovals();
  } catch(e) {}
}

// ===== API 配置 =====
function loadConfig() {
  try {
    const s = localStorage.getItem('trueagent_api_config');
    if (s) {
      const c = JSON.parse(s);
      if (c.apiKey) $('cfg-api-key').value = c.apiKey;
      if (c.apiUrl) $('cfg-api-url').value = c.apiUrl;
      if (c.apiKeysText && document.getElementById('cfg-api-keys')) {
        document.getElementById('cfg-api-keys').value = c.apiKeysText;
      }
      if (c.model) {
        const knownModels = ['deepseek-v4-flash','deepseek-chat','deepseek-reasoner','gpt-4o','gpt-4o-mini'];
        if (knownModels.includes(c.model)) {
          $('cfg-model-select').value = c.model;
        } else {
          $('cfg-model-select').value = 'custom';
          $('cfg-custom-row').style.display = 'flex';
          $('cfg-custom-model').value = c.model;
        }
      }
      if (c.temperature != null) { $('cfg-temp').value = Math.round(c.temperature*10); $('cfg-temp-val').textContent = c.temperature.toFixed(1); }
    }
  } catch(e) {}
}
$('cfg-model-select').addEventListener('change', () => {
  $('cfg-custom-row').style.display = $('cfg-model-select').value === 'custom' ? 'flex' : 'none';
});
$('cfg-temp').addEventListener('input', () => {
  $('cfg-temp-val').textContent = (parseInt($('cfg-temp').value)/10).toFixed(1);
});
$('cfg-apply').addEventListener('click', async () => {
  const model = $('cfg-model-select').value === 'custom' ? $('cfg-custom-model').value.trim() : $('cfg-model-select').value;
  const apiKey = $('cfg-api-key').value.trim();
  const apiKeysEl = document.getElementById('cfg-api-keys');
  const apiKeysText = apiKeysEl ? apiKeysEl.value.trim() : '';
  const apiUrl = $('cfg-api-url').value.trim();
  const temp = parseInt($('cfg-temp').value)/10;
  if (!model || (!apiKey && !apiKeysText)) { showCfg('请填写模型和 API Key', 'error'); return; }
  localStorage.setItem('trueagent_api_config', JSON.stringify({model, apiKey, apiKeysText, apiUrl, temperature: temp}));
  showCfg('正在应用...', 'pending'); $('cfg-apply').disabled = true;
  try {
    const r = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model, api_key:apiKey, api_keys:apiKeysText, api_url:apiUrl, temperature:temp})});
    const d = await r.json();
    if (d.success) {
      const keyCount = d.key_count || (apiKeysText ? apiKeysText.split('\n').filter(k=>k.trim()).length : (apiKey ? 1 : 0));
      showCfg(`✅ 已切换至 ${model}（${keyCount}把钥匙）`, 'success');
      $('cfg-model').textContent = model;
      // 在聊天区显示反馈
      addMessage('system', `✅ API 已配备，待用\n   模型：${model}\n   钥匙：${keyCount} 把${d.message ? ' · ' + d.message : ''}`);
      // 多Key框：掩码 + 锁定
      maskAndLockKeys();
    }
    else showCfg(`❌ ${d.error||'失败'}`, 'error');
  } catch(e) { showCfg(`❌ ${e.message}`, 'error'); }
  $('cfg-apply').disabled = false;
});
// 多Key掩码显示
function maskAndLockKeys() {
  const ta = document.getElementById('cfg-api-keys'), lbl = document.getElementById('cfg-keys-label');
  if (!ta || ta.readOnly) return;
  const raw = ta.value.trim();
  if (!raw) return;
  const lines = raw.split('\n').filter(l => l.trim());
  const masked = lines.map(k => k.length > 15 ? k.substring(0,8)+'...'+k.slice(-4) : k.substring(0,5)+'...');
  ta.value = masked.join('\n');
  ta.readOnly = true;
  ta.style.background = '#1a1a2e';
  ta.style.color = '#888';
  ta.style.cursor = 'not-allowed';
  // 显示编辑按钮
  let editBtn = document.getElementById('cfg-keys-edit');
  if (!editBtn) {
    editBtn = document.createElement('button');
    editBtn.id = 'cfg-keys-edit';
    editBtn.textContent = '✏️ 编辑';
    editBtn.className = 'cfg-btn';
    editBtn.style.cssText = 'margin-top:4px;font-size:11px;padding:2px 8px';
    editBtn.onclick = function() {
      ta.value = raw;
      ta.readOnly = false;
      ta.style.background = '';
      ta.style.color = '';
      ta.style.cursor = '';
      editBtn.remove();
      showCfg('已解锁，可编辑 Key', 'pending');
    };
    ta.parentNode.appendChild(editBtn);
  }
}
$('cfg-test').addEventListener('click', async () => {
  showCfg('正在测试...', 'pending'); $('cfg-test').disabled = true;
  try {
    const r = await fetch('/api/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({api_key:$('cfg-api-key').value.trim(), api_url:$('cfg-api-url').value.trim()})});
    const d = await r.json();
    if (d.success) showCfg(`鉁?${d.message||'连接成功'}`, 'success');
    else showCfg(`❌?${d.error||'失败'}`, 'error');
  } catch(e) { showCfg(`❌?${e.message}`, 'error'); }
  $('cfg-test').disabled = false;
});
function showCfg(msg, type) {
  const el = $('cfg-status');
  el.textContent = msg; el.className = 'cfg-status '+type;
}

// ===== 鍒濆始鍖?=====
loadConfig();
loadSessions();
loadHistory();
startDashboard();
startTrendChart();
startApprovalPolling();

// 压缩按钮
if ($('compressBtn')) $('compressBtn').addEventListener('click', compressOldMessages);

// 主动消息轮询（每10秒）
setInterval(pollProactive, 10000);
// 页面加载时拉取历史主动消息（防止错过启动时的消息）
setTimeout(loadProactiveHistory, 2000);

// 定期更新模型显示
setInterval(() => {
  fetch('/api/status').then(r=>r.json()).then(d => {
    if (d.model_name && d.model_name !== $('cfg-model').textContent) $('cfg-model').textContent = d.model_name;
  }).catch(()=>{});
}, 15000);

// ============================================================
// 任务进度面板
// ============================================================
function renderTaskSessions(data) {
  const list = $('taskList');
  if (!list) return;
  const sessions = data.sessions || [];
  if (sessions.length === 0) {
    list.innerHTML = '<div class="task-empty">暂无运行中的任务</div>';
    return;
  }
  list.innerHTML = sessions.map(s => {
    const pct = Math.round((s.progress || 0) * 100);
    const cls = s.status === 'running' ? 'running' :
               s.status === 'completed' || s.status === 'completed_with_warnings' ? 'completed' :
               s.status === 'failed' ? 'failed' : 'paused';
    const barCls = cls === 'completed' ? 'completed' :
                   cls === 'failed' ? 'failed' : '';
    const statusLabels = {
      running: 'Running', paused: 'Paused', completed: 'Done',
      completed_with_warnings: 'Warn', failed: 'Failed',
      user_intervention: 'Need user', pending: 'Pending'
    };
    return '<div class="task-item">' +
      '<div class="task-header">' +
        '<span>' + (s.phase ? s.phase.substring(0, 50) : '...') + '</span>' +
        '<span class="task-status ' + cls + '">' + (statusLabels[s.status] || s.status) + '</span>' +
      '</div>' +
      '<div class="task-phase">' + s.completed + '/' + s.total + ' steps, API:' + s.api_calls + (s.failed > 0 ? ', failed:' + s.failed : '') + '</div>' +
      '<div class="task-progress-bar">' +
        '<div class="task-progress-fill ' + barCls + '" style="width:' + pct + '%"></div>' +
      '</div>' +
      '<div class="task-progress-text">' +
        '<span>' + pct + '%</span>' +
        '<span class="task-id">' + (s.session_id ? s.session_id.substring(0, 12) : '') + '</span>' +
      '</div>' +
    '</div>';
  }).join('');
}

function pollTaskSessions() {
  fetch('/api/task-sessions')
    .then(r => r.json())
    .then(data => renderTaskSessions(data))
    .catch(() => {});
}

// 任务进度轮询已停用（前端无对应面板）
// setInterval(pollTaskSessions, 10000);
// setTimeout(pollTaskSessions, 500);

// ============================================================
// 分身管理系统
// ============================================================

// 分身状?
let clones = [];
let currentAgent = 'agent_main';
let cloneNames = {};
let cloneHistory = {};
let cloneScrollPos = {};
let clonePollTimer = null;
let currentClonePort = '';

// 私聊模式
let currentPrivateTarget = null;  // null=缂囥倛浜, 'agent_xxx'=私聊

// 黑板消息
let blackboardMessages = [];
let blackboardPollTimer = null;

// 终端
let terminalTimer = null;
let terminalVisible = false;

// 加载保存的分Ј?
try {
  const saved = localStorage.getItem('trueagent_clone_names');
  if (saved) cloneNames = JSON.parse(saved);
} catch(e) {}

function saveCloneNames() {
  localStorage.setItem('trueagent_clone_names', JSON.stringify(cloneNames));
}

function getCloneName(agentId) {
  // 优先黑板注册表的 alias（持久化），其次 localStorage，最后默认
  var fromBoard = null;
  clones.forEach(function(c) {
    if (c.id === agentId && c.alias) fromBoard = c.alias;
  });
  return fromBoard || cloneNames[agentId] || agentId.replace('agent_', '分身');
}

// ===== 渲染分身标签栏 =====
function renderAgentTabs() {
  const tabs = $('agent-tabs');
  if (!tabs) return;
  let html = '<div class="agent-tab ' + (currentAgent === 'agent_main' ? 'active' : '') + '" data-agent="agent_main" data-port="">' +
    '<span class="tab-icon">' + '\u25C7' + '</span><span class="tab-name">' + '主智能体</span></div>';
  clones.forEach(function(c) {
    var name = getCloneName(c.id);
    var active = c.id === currentAgent ? 'active' : '';
    html += '<div class="agent-tab ' + active + '" data-agent="' + c.id + '" data-port="' + (c.port||'') + '" draggable="true">' +
      '<span class="tab-icon">' + '\uD83E\uDDEC' + '</span>' +
      '<span class="tab-name">' + name + '</span>' +
      '<span class="tab-popout" data-agent="' + c.id + '" data-port="' + (c.port||'') + '" title="拖拽弹出独立窗口">\u2B1C</span>' +
      '<span class="tab-close" data-agent="' + c.id + '">\u2715</span></div>';
  });
  // 共享黑板 tab（始终保留）
  html += '<div class="agent-tab ' + (currentAgent === '__blackboard__' ? 'active' : '') + '" data-agent="__blackboard__" data-port="">' +
    '<span class="tab-icon">\uD83D\uDCCB</span>' +
    '<span class="tab-name">共享黑板</span>' +
    '<span class="tab-badge" id="bb-badge" style="display:none;background:#ef4444;color:#fff;font-size:10px;border-radius:8px;padding:0 5px;margin-left:4px;">0</span>' +
    '</div>';
  tabs.innerHTML = html;

  tabs.querySelectorAll('.agent-tab').forEach(function(el) {
    el.addEventListener('click', function(e) {
      if (e.target.classList.contains('tab-close')) return;
      if (e.target.classList.contains('tab-popout')) return;
      switchAgent(el.dataset.agent, el.dataset.port);
    });
    
    // 拖拽弹出
    if (el.getAttribute('draggable') === 'true') {
      el.addEventListener('dragstart', function(e) {
        e.dataTransfer.setData('text/plain', el.dataset.agent + '||' + (el.dataset.port||''));
        e.dataTransfer.effectAllowed = 'move';
        el.classList.add('dragging');
        window._dragPopout = { agent: el.dataset.agent, port: el.dataset.port || '18770', dropped: false };
        setTimeout(function() { el.classList.remove('dragging'); }, 0);
      });
      el.addEventListener('dragend', function(e) {
        el.classList.remove('dragging');
        if (window._dragPopout && !window._dragPopout.dropped) {
          popoutAgentTab(window._dragPopout.agent, window._dragPopout.port);
        }
        window._dragPopout = null;
      });
    }
  });
  
  // 标ǩ栏作为拖拽目?
  var tabBar = $('agent-tabs');
  if (tabBar) {
    tabBar.addEventListener('dragover', function(e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });
    tabBar.addEventListener('drop', function(e) {
      e.preventDefault();
      if (window._dragPopout) window._dragPopout.dropped = true;
    });
  }
  
  tabs.querySelectorAll('.tab-close').forEach(function(el) {
    el.addEventListener('click', function(e) {
      e.stopPropagation();
      var aid = el.dataset.agent;
      stopClone(aid);
    });
  });
  
  // 弹出按钮
  tabs.querySelectorAll('.tab-popout').forEach(function(el) {
    el.addEventListener('click', function(e) {
      e.stopPropagation();
      var aid = el.dataset.agent;
      var port = el.dataset.port || '18770';
      popoutAgentTab(aid, port);
    });
  });
}

// ===== 停止分身 =====
async function stopClone(agentId) {
  if (!confirm('\u26A0 \u786E\u5B9A\u505C\u6B62\u5206\u8EAB "' + getCloneName(agentId) + '"\uFF1F\n\n\u505C\u6B62\u540E\u8BE5\u5206\u8EAB\u7684\u72EC\u7ACB\u8BB0\u5FC6\u3001\u77E5\u8BC6\u56FE\u8C31\u3001\u56E0\u679C\u94FE\u5C06\u88AB\u5220\u9664\u3002\n\u6B64\u64CD\u4F5C\u4E0D\u53EF\u64A4\u9500\u3002')) return;
  try {
    var c = clones.find(function(x) { return x.id === agentId; });
    var r = await fetch('/api/clone-stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({agent_id: agentId, port: c ? c.port : 0})
    });
    var d = await r.json();
    if (d.success) {
      addMessage('system', '\u26D4 ' + getCloneName(agentId) + ' \u5DF2\u505C\u6B62');
      // 从列表中移除
      clones = clones.filter(function(x) { return x.id !== agentId; });
      if (currentAgent === agentId) switchAgent('agent_main', '');
      renderAgentTabs();
      renderCloneList();
    } else {
      addMessage('error', '\u505C\u6B62\u5931\u8D25: ' + (d.error || ''));
    }
  } catch(e) {
    addMessage('error', '\u505C\u6B62\u5931\u8D25: ' + e.message);
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 重启分身 =====
async function restartClone(agentId) {
  var name = getCloneName(agentId);
  if (!confirm('\u786E\u5B9A\u91CD\u542F ' + name + '\uFF1F')) return;
  addMessage('system', '\uD83D\uDD04 \u6B63\u5728\u91CD\u542F ' + name + '...');
  try {
    var c = clones.find(function(x) { return x.id === agentId; });
    var r = await fetch('/api/clone-restart', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({agent_id: agentId, port: c ? c.port : 0})
    });
    var d = await r.json();
    if (d.success) {
      addMessage('system', '\u2705 ' + name + ' \u5DF2\u91CD\u542F');
      // 等待重新注册
      for (var i = 0; i < 6; i++) {
        await new Promise(function(r) { setTimeout(r, 2000); });
        await pollBlackboard();
        var found = clones.find(function(x) { return x.id === agentId; });
        if (found) break;
      }
      renderAgentTabs();
      renderCloneList();
    } else {
      addMessage('error', '\u91CD\u542F\u5931\u8D25: ' + (d.error || ''));
    }
  } catch(e) {
    addMessage('error', '\u91CD\u542F\u5931\u8D25: ' + e.message);
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 切换智能?=====
async function switchAgent(agentId, port) {
  if (agentId === currentAgent) return;
  exitPrivateChat();  // 退出私聊模式
  var chatPanel = $('chat-panel');
  var msgsEl = $('messages');
  var bbPanel = $('blackboard-panel');

  // 保存当前会话
  if (msgsEl && chatPanel && currentAgent !== '__blackboard__') {
    cloneHistory[currentAgent] = msgsEl.innerHTML;
    cloneScrollPos[currentAgent] = chatPanel.scrollTop;
  }
  if (bbPanel && currentAgent === '__blackboard__') {
    // blackboard 不需要保?总是从API鎷?
  }

  currentAgent = agentId;
  currentClonePort = port || '';

  // 更新标题
  var name;
  if (agentId === 'agent_main') name = 'TrueAgent';
  else if (agentId === '__blackboard__') name = '共享黑板';
  else name = getCloneName(agentId);
  document.title = name;
  var titleEl = document.querySelector('.title-text');
  if (titleEl) titleEl.textContent = name;

  renderAgentTabs();
  renderCloneList();

  // 显示/隐藏聊天容器和黑板容器
  var chatPanel = $('chat-panel');
  var bbPanel = $('blackboard-panel');
  var inputBar = $('input-bar');
  var terminalPanel = $('terminal-panel');
  
  if (agentId === '__blackboard__') {
    // 显示黑板、隐藏聊天
    if (chatPanel) chatPanel.style.display = 'none';
    if (inputBar) inputBar.style.display = 'none';
    if (terminalPanel) terminalPanel.style.display = 'none';  // 黑板模式下隐藏终端
    if (bbPanel) {
      bbPanel.style.display = 'flex';
      renderBlackboardMessages();
    }
  } else {
    if (bbPanel) bbPanel.style.display = 'none';
    if (inputBar) inputBar.style.display = 'flex';
    if (terminalPanel) terminalPanel.style.display = '';  // 恢复终端（用户可手动开关）
    if (chatPanel) {
      chatPanel.style.display = 'flex';
      var msgsEl = $('messages');
      if (cloneHistory[agentId] && msgsEl) {
        msgsEl.innerHTML = cloneHistory[agentId];
        if (cloneScrollPos[agentId] !== undefined) {
          setTimeout(function() { chatPanel.scrollTop = cloneScrollPos[agentId]; }, 10);
        }
      } else if (msgsEl) {
        msgsEl.innerHTML = '<div class="message msg-system"><div class="msg-time"></div>' +
          '<div class="msg-bubble welcome">\uD83D\uDC4B \u6B63\u5728\u8FDE\u63A5 ' +
          (agentId === 'agent_main' ? '\u4E3B\u667A\u80FD\u4F53' : getCloneName(agentId)) + '...</div></div>';
        if (agentId !== 'agent_main') {
          try {
            var r = await fetch('http://127.0.0.1:' + port + '/api/conversations/default');
            var d = await r.json();
            msgsEl.innerHTML = '';
            if (d.messages && d.messages.length) {
              d.messages.forEach(function(m) {
                if (m.role === 'user') addMessage('user', m.content);
                else if (m.role === 'assistant') addMessage('agent', m.content);
                else if (m.role === 'system') addMessage('system', m.content);
              });
            } else {
              msgsEl.innerHTML = '<div class="message msg-system"><div class="msg-time"></div>' +
                '<div class="msg-bubble welcome">\uD83D\uDCAC \u5206\u8EAB ' + getCloneName(agentId) + ' \u5DF2\u5C31\u7EEA</div></div>';
            }
          } catch(e) {
            msgsEl.innerHTML = '<div class="message msg-system"><div class="msg-time"></div>' +
              '<div class="msg-bubble welcome">\uD83D\uDCAC \u5206\u8EAB ' + getCloneName(agentId) + '</div></div>';
          }
        }
        scrollToBottom();
      }
    }
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 渲染分身列表（侧栏） =====
function renderCloneList() {
  var list = $('cloneList');
  if (!list) return;
  if (!clones.length) {
    list.innerHTML = '<div class="clone-empty">\u6682\u65E0\u5206\u8EAB\uFF0C\u70B9\u51FB\u4E0A\u65B9\u6309\u94AE\u521B\u5EFA</div>';
    return;
  }
  var now = Date.now() / 1000;
  list.innerHTML = clones.map(function(c) {
    var name = getCloneName(c.id);
    var isActive = c.id === currentAgent;
    var isOnline = c.status === 'running' && (now - c.last_seen) < 60;
    var style = isActive ? 'background:var(--accent-dim);' : '';
    return '<div class="clone-item" data-agent="' + c.id + '" data-port="' + c.port + '" style="' + style + '">' +
      '<span class="clone-status-dot' + (isOnline ? '' : ' offline') + '"></span>' +
      '<span class="clone-name">' + name + '</span>' +
      '<div class="clone-actions">' +
      '<button class="rename-btn" title="\u91CD\u547D\u540D" data-agent="' + c.id + '">\u270F\uFE0F</button>' +
      '<button class="clone-private-btn" title="私聊" data-agent="' + c.id + '" data-name="' + name + '">\uD83D\uDCAC</button>' +
      '<button class="restart-btn" title="重启分身" data-agent="' + c.id + '">\uD83D\uDD04</button>' +
      '<button class="stop-btn" title="停止分身" data-agent="' + c.id + '">\u26D4</button>' +
      '</div></div>';
  }).join('');

  list.querySelectorAll('.clone-item').forEach(function(el) {
    el.addEventListener('click', function(e) {
      if (e.target.classList.contains('rename-btn') ||
          e.target.classList.contains('restart-btn') || e.target.classList.contains('stop-btn') ||
          e.target.classList.contains('clone-private-btn')) return;
      switchAgent(el.dataset.agent, el.dataset.port);
    });
  });
  list.querySelectorAll('.rename-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      showRenameModal(btn.dataset.agent);
    });
  });
  list.querySelectorAll('.restart-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      restartClone(btn.dataset.agent);
    });
  });
  list.querySelectorAll('.stop-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      stopClone(btn.dataset.agent);
    });
  });
  list.querySelectorAll('.clone-private-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      enterPrivateChat(btn.dataset.agent, btn.dataset.name);
    });
  });
}

// ===== 黑板轮询 =====
function startClonePolling() {
  pollBlackboard();
  clonePollTimer = setInterval(pollBlackboard, 5000);
}

async function pollBlackboard() {
  try {
    var r = await fetch('/api/blackboard');
    var d = await r.json();
    var agents = d.agents || [];
    var newClones = agents.filter(function(a) { return a.id !== 'agent_main'; });
    var changed = false;

    newClones.forEach(function(nc) {
      var existing = clones.find(function(c) { return c.id === nc.id; });
      if (existing) {
        // 更新别名：黑板是权威来源
        if (nc.alias && nc.alias !== existing.alias) {
          existing.alias = nc.alias;
          cloneNames[nc.id] = nc.alias;
          saveCloneNames();
        }
        Object.assign(existing, nc);
      } else {
        // 新分身：设置 last_seen 为当前时间（避免被后续 filter 立即清除）
        nc.last_seen = Date.now() / 1000;
        clones.push(nc);
        // 从黑板读取别名，覆盖 localStorage
        if (nc.alias) {
          cloneNames[nc.id] = nc.alias;
          saveCloneNames();
        }
        changed = true;
      }
    });

    var now = Date.now() / 1000;
    var beforeCount = clones.length;
    // 过滤离线分身：status !== 'running' 或心跳超过 300 秒（5分钟）
    clones = clones.filter(function(c) { 
      return c.status === 'running' && (now - c.last_seen) < 300; 
    });
    if (clones.length < beforeCount) changed = true;

    if (changed) {
      renderAgentTabs();
      renderCloneList();
    }
  } catch(e) {}
}

// ===== 创建分身 =====
async function spawnClone() {
  if (isProcessing) {
    addMessage('system', '\u23F3 \u8BF7\u7B49\u5F85\u5F53\u524D\u4EFB\u52A1\u5B8C\u6210');
    return;
  }
  // 创建确认：说明分身能力
  if (!confirm(
    '\uD83E\uDDEC \u521B\u5EFA\u667A\u80FD\u5206\u8EAB\n\n' +
    '\u5206\u8EAB\u5177\u5907\u4EE5\u4E0B\u80FD\u529B\uFF1A\n' +
    '\u2022 \u72EC\u7ACB\u601D\u8003\u4E0E\u5BF9\u8BDD\uFF08\u89D2\u8272\u626E\u6F14\uFF09\n' +
    '\u2022 \u591A\u4EFB\u52A1\u5E76\u884C\u5904\u7406\n' +
    '\u2022 \u534F\u540C\u673A\u5236\uFF08\u5171\u4EAB\u9ED1\u677F\u901A\u4FE1\uFF09\n' +
    '\u2022 \u72EC\u7ACB\u8BB0\u5FC6\u4E0E\u77E5\u8BC6\u5B66\u4E60\n' +
    '\u2022 \u5B8C\u6574\u5DE5\u5177\u64CD\u4F5C\u80FD\u529B\n\n' +
    '\u521B\u5EFA\u540E\u5C06\u81EA\u52A8\u52A0\u5165\u5171\u4EAB\u9ED1\u677F\uFF0C' +
    '\u4E3B\u667A\u80FD\u4F53\u53EF\u5206\u914D\u4EFB\u52A1\u3002'
  )) return;
  addMessage('system', '\uD83E\uDDEC \u6B63\u5728\u521B\u5EFA\u5206\u8EAB...');
  try {
    var r = await fetch('/api/spawn-clone', { method: 'POST' });
    var d = await r.json();
    if (d.success) {
      var agentId = 'agent_' + d.port;
      var num = clones.length + 1;
      cloneNames[agentId] = '\u5206\u8EAB' + num;
      saveCloneNames();

      addMessage('system', '\u2705 \u5206\u8EAB\u5DF2\u521B\u5EFA (\u7AEF\u53E3 ' + d.port + ')');

      if (d.shared_api_key && d.warning) {
        addMessage('system', '\u26A0\uFE0F \u5F53\u524D\u5206\u8EAB\u4F7F\u7528\u5171\u4EAB API Key\uFF0C\u591A\u4E2A\u5206\u8EAB\u540C\u65F6\u8C03\u7528\u6709\u540E\u53F0\u9650\u6D41\u98CE\u9669\u3002\u5EFA\u8BAE\u4E3A\u5206\u8EAB\u7533\u8BF7\u72EC\u7ACB Key');
      }

      // 先触发分身初始化
      try {
        await fetch('http://127.0.0.1:' + d.port + '/api/status');
      } catch(e) {}
      
      // 等黑板注册
      await new Promise(function(resolve) { setTimeout(resolve, 2000); });
      for (var i = 0; i < 6; i++) {
        await pollBlackboard();
        var found = clones.find(function(x) { return x.id === agentId; });
        if (found) {
          // 自动切换到共享黑板（展示所有分身协作空间）
          switchAgent('__blackboard__', '');
          addMessage('system', '\uD83D\uDC4D \u5206\u8EAB\u5DF2\u5C31\u7EEA\uFF0C\u5DF2\u52A0\u5165\u5171\u4EAB\u9ED1\u677F');
          // 向黑板发送系统通知
          try {
            await fetch('/api/blackboard', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({source: '__system__', content: '\uD83E\uDDEC \u65B0\u5206\u8EAB ' + agentId.replace('agent_','') + ' \u5DF2\u52A0\u5165\u5171\u4EAB\u7A7A\u95F4'})
            });
          } catch(e) {}
          return;
        }
        await new Promise(function(resolve) { setTimeout(resolve, 2000); });
      }
      addMessage('system', '\u26A0\uFE0F \u5206\u8EAB\u521B\u5EFA\u6210\u529F\u4F46\u672A\u6CE8\u518C\u5230\u9ED1\u677F\uFF0C\u8BF7\u7A0D\u540E\u5237\u65B0');
    } else {
      addMessage('error', '\u521B\u5EFA\u5206\u8EAB\u5931\u8D25: ' + (d.error || '\u672A\u77E5\u9519\u8BEF'));
    }
  } catch(e) {
    addMessage('error', '\u521B\u5EFA\u5206\u8EAB\u5931\u8D25: ' + e.message);
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 重命?=====
var renameTarget = '';

function showRenameModal(agentId) {
  renameTarget = agentId;
  $('renameInput').value = getCloneName(agentId);
  $('renameInput').type = 'text';
  $('renameInput').placeholder = '\u8F93\u5165\u65B0\u7684\u5206\u8EAB\u540D\u79F0';
  var h3 = $('renameModal').querySelector('h3');
  if (h3) h3.textContent = '\u91CD\u547D\u540D\u5206\u8EAB';
  $('renameModal').style.display = 'flex';
  $('renameInput').focus();
  $('renameInput').select();
}

$('renameCancelBtn').addEventListener('click', function() {
  $('renameModal').style.display = 'none';
});

$('renameConfirmBtn').addEventListener('click', function() {
  var newName = $('renameInput').value.trim();
  if (newName) {
    // 持久化写入黑板注册表
    var aid = renameTarget;
    cloneNames[aid] = newName;
    saveCloneNames();
    if (currentAgent === aid) {
      document.title = newName;
      var titleEl = document.querySelector('.title-text');
      if (titleEl) titleEl.textContent = newName;
    }
    renderAgentTabs();
    renderCloneList();
    
    // 同步到服务器（持久化）
    fetch('/api/clone-alias', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({agent_id: aid, alias: newName})
    }).catch(function() {});
  }
  $('renameModal').style.display = 'none';
});

$('renameInput').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') $('renameConfirmBtn').click();
});

// ===== 发送消息（通用） =====
var oldSendMessage = sendMessage;
sendMessage = async function(text) {
  if (!text || !text.trim() || isProcessing) return;
  
  // 确保默认值
  if (typeof currentAgent === 'undefined') currentAgent = 'agent_main';
  if (typeof currentPrivateTarget === 'undefined') currentPrivateTarget = null;
  if (typeof currentClonePort === 'undefined') currentClonePort = null;
  
  try {
    // 私聊模式
    if (currentPrivateTarget && currentPrivateTarget !== 'agent_main') {
      await sendPrivateMessage(currentPrivateTarget, text);
      return;
    }
    
    if (currentAgent === '__blackboard__') {
      sendBlackboardViaOrchestrator(text);
      return;
    }
    if (currentAgent !== 'agent_main' && currentClonePort) {
      await sendToClone(currentAgent, currentClonePort, text);
      return;
    }
    await oldSendMessage(text);
  } catch(e) {
    console.error('[sendMessage] error:', e);
    try { await oldSendMessage(text); } catch(e2) {
      addMessage('error', '发送失败: ' + (e.message || e));
      isProcessing = false;
      if ($('sendBtn')) $('sendBtn').disabled = false;
    }
  }
};

async function sendToClone(agentId, port, text) {
  isProcessing = true;
  $('sendBtn').disabled = true;
  $('stopBtn').disabled = false;

  addMessage('user', text);
  $('inputText').value = '';
  $('inputText').style.height = 'auto';

  var td = document.createElement('div');
  td.className = 'message msg-agent';
  td.id = 'typing-indicator';
  td.innerHTML = '<div class="msg-bubble typing-dots"><span>\u00B7</span><span>\u00B7</span><span>\u00B7</span></div>';
  $('messages').appendChild(td);
  scrollToBottom();

  try {
    var r = await fetch('http://127.0.0.1:' + port + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: text, session: 'default'})
    });
    var d = await r.json();
    var ti = $('typing-indicator');
    if (ti) ti.remove();
    if (d.error) addMessage('error', d.error);
    else addMessage('agent', d.reply || '(\u65E0\u54CD\u5E94)');
  } catch(e) {
    var ti = $('typing-indicator');
    if (ti) ti.remove();
    addMessage('error', '\u5206\u8EAB\u901A\u4FE1\u9519\u8BEF: ' + e.message);
  }

  isProcessing = false;
  $('sendBtn').disabled = false;
  $('stopBtn').disabled = true;
  $('inputText').focus();
}

// ===== 黑板消息渲染 =====
function renderBlackboardMessages() {
  var el = $('blackboard-messages');
  if (!el) return;
  if (!blackboardMessages.length) {
    el.innerHTML = '<div class="blackboard-entry bb-system"><div class="bb-source">系统</div>' +
      '<div class="bb-text">暂无公开消息。当智能体在此发言时，所有分身都能看到。</div></div>';
    return;
  }
  el.innerHTML = blackboardMessages.map(function(m) {
    var time = m.time ? new Date(m.time * 1000).toLocaleTimeString() : '';
    var source = m.source === '__system__' ? '系统' : getCloneName(m.source);
    var cls = m.source === '__system__' ? 'bb-system' : '';
    return '<div class="blackboard-entry ' + cls + '">' +
      '<span class="bb-time">' + time + '</span>' +
      '<div class="bb-source">' + source + '</div>' +
      '<div class="bb-text">' + highlightMentions(markedParse(m.content || '')) + '</div></div>';
  }).join('');
  el.scrollTop = el.scrollHeight;
}

// ===== 黑板轮询 =====
function startBlackboardPolling() {
  blackboardMessages = [{source: '__system__', content: '共享黑板监控已启动', time: Date.now()/1000}];
  blackboardPollTimer = setInterval(pollBlackboardMessages, 3000);
}

async function pollBlackboardMessages() {
  try {
    var r = await fetch('/api/blackboard');
    var d = await r.json();
    var msgs = d.messages || [];
    if (msgs.length > 0) {
      var oldLen = blackboardMessages.length;
      blackboardMessages = msgs;
      // 更新通知 badge（非黑板页面时显示未读数）
      var badge = $('bb-badge');
      if (badge && currentAgent !== '__blackboard__') {
        var newMsgs = msgs.length - oldLen;
        if (newMsgs > 0) {
          badge.style.display = 'inline';
          badge.textContent = newMsgs;
        }
      }
      if (currentAgent === '__blackboard__') {
        renderBlackboardMessages();
        if (badge) badge.style.display = 'none';
      }
    }
  } catch(e) {}
}

// ===== 黑板发送消息 =====
try {
  $('bb-send-btn').addEventListener('click', sendBlackboardMessage);
  $('bb-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendBlackboardMessage();
    }
  });
} catch(e) { console.warn('[bb] event bind failed, retrying via DOMContentLoaded');
  // 冗余：如果元素还没渲染，等 DOM 完全加载后再绑
  document.addEventListener('DOMContentLoaded', function() {
    try {
      var bbs = $('bb-send-btn');
      var bbi = $('bb-input');
      if (bbs) bbs.addEventListener('click', sendBlackboardMessage);
      if (bbi) bbi.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendBlackboardMessage(); }
      });
    } catch(e2) {}
  });
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



async function sendBlackboardMessage() {
  var el = $('bb-input');
  var text = el.value.trim();
  if (!text) return;
  el.value = '';
  el.style.height = 'auto';
  
  // 解析 @mention：提取被 @ 的智能体
  var mentions = [];
  var mentionRegex = /@(\S+)/g;
  var match;
  while ((match = mentionRegex.exec(text)) !== null) {
    mentions.push(match[1]);
  }
  
  // 以当前选中的 agent 身份发送到黑板
  var source = currentAgent || 'agent_main';
  try {
    var r = await fetch('/api/blackboard', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        source: source, 
        content: text,
        mentions: mentions  // 被 @ 的智能体列表
      })
    });
    // 通知被 @ 的分身（通过克隆 API 推送提醒）
    if (mentions.length > 0) {
      clones.forEach(function(c) {
        var cname = getCloneName(c.id);
        if (mentions.indexOf(cname) >= 0 || mentions.indexOf(c.id) >= 0) {
          // 异步推送唤醒通知
          fetch('http://127.0.0.1:' + c.port + '/api/notify', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'mention', from: source, content: text})
          }).catch(function(){});
        }
      });
    }
    setTimeout(pollBlackboardMessages, 500);
  } catch(e) {
    blackboardMessages.push({source: source, content: text + ' (本地)', time: Date.now()/1000, mentions: mentions});
    if (currentAgent === '__blackboard__') renderBlackboardMessages();
  }
}

// ===== @mention 渲染增强 =====
function highlightMentions(content) {
  // 将 @name 渲染为高亮标签
  return content.replace(/@(\S+)/g, '<span class="mention-tag">@$1</span>');
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 终面板 =====
$('terminalBtn').addEventListener('click', toggleTerminal);
$('terminalCloseBtn').addEventListener('click', function() {
  if (terminalVisible) toggleTerminal();
});

function toggleTerminal() {
  var panel = $('terminal-panel');
  var btn = $('terminalBtn');
  terminalVisible = !terminalVisible;
  panel.style.display = terminalVisible ? 'flex' : 'none';
  btn.style.color = terminalVisible ? 'var(--accent)' : '';
  
  if (terminalVisible) {
    pollTerminal();
    terminalTimer = setInterval(pollTerminal, 1000);
  } else {
    clearInterval(terminalTimer);
  }
}

// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



async function pollTerminal() {
  try {
    var r = await fetch('/api/terminal-log');
    var d = await r.json();
    var out = $('terminal-output');
    if (out && d.log) {
      // 仅在内容真正变化时才更新，避免破坏用户的文本选择
      if (out.textContent !== d.log) {
        out.textContent = d.log;
        out.scrollTop = out.scrollHeight;
      }
    }
  } catch(e) {}
}

// ===== 分身按钮点击 =====
$('cloneBtn').addEventListener('click', async function() {
  var clonesSec = document.querySelector('[data-section="clones"]');
  if (clonesSec && clonesSec.classList.contains('collapsed')) {
    clonesSec.click();
  }
  if (!sidebarVisible) toggleSidebar();

  if (clones.length === 0) {
    await spawnClone();
  } else {
    // 如果有分Ј衱打开侧栏让用户?
    toggleSidebar();
  }
});

// ===== @ 自动补全 =====
var atMentionTimer = null;
var atMenuVisible = false;
var atMenuSelected = 0;
var atMenuAgents = [];

$('inputText').addEventListener('input', function() {
  var text = this.value;
  var cursor = this.selectionStart;
  
  // 检测 @ 触发
  var beforeCursor = text.substring(0, cursor);
  var atIdx = beforeCursor.lastIndexOf('@');
  if (atIdx >= 0 && (atIdx === 0 || text[atIdx-1] === ' ' || text[atIdx-1] === '\n')) {
    var query = beforeCursor.substring(atIdx + 1).toLowerCase();
    // 如果查询中包含空格或太长就关闭
    if (query.includes(' ') || query.length > 20) {
      hideAtMenu();
      return;
    }
    
    // 构建候项
    var candidates = [];
    candidates.push({id: 'agent_main', alias: '主智能体'});
    clones.forEach(function(c) {
      candidates.push({id: c.id, alias: getCloneName(c.id)});
    });
    }
  });





// ===== 黑板通道 Orchestrator 发言 =====

// ===== 发言统计轮询 =====
var speakStatsTimer = null;



// ===== 分身/黑板/发言统计初始化已停用（v5.9 前端无对应面板，后端接口已删除）=====
// setTimeout(function() {
//   startClonePolling();
//   startBlackboardPolling();
//   startSpeakStats();
//   startPrivatePolling();
//   renderAgentTabs();
//   renderCloneList();
// }, 2000);

// ===== 发言配置已停用（v5.9 前端无对应面板，后端 /api/orchestrator/config 不存在） =====
/*
var speakConfigBtn = $('speak-config-btn');
... (已停用)
*/

// ===== 私聊功能 =====

// 进入˽ģʽ
function enterPrivateChat(targetId, targetName) {
  currentPrivateTarget = targetId;
  var bar = $('private-bar');
  var nameEl = $('private-target-name');
  if (bar) {
    bar.classList.add('visible');
    bar.style.display = 'flex';
  }
  if (nameEl) nameEl.textContent = targetName || targetId;
  
  // л壨壩
  if (currentAgent !== 'agent_main') {
    switchAgent('agent_main', '');
  }
  
  // 清空并加载私聊历史
  var msgsEl = $('messages');
  if (msgsEl) {
    msgsEl.innerHTML = '<div class="message msg-system"><div class="msg-bubble" style="opacity:0.6;font-size:12px">\uD83D\uDCAC 私聊模式 - 消息?' + (targetName || targetId) + ' 可见</div></div>';
  }
  
  // 加载私聊历史
  loadPrivateHistory(targetId);
  
  // 更新私聊按钮高亮
  document.querySelectorAll('.clone-private-btn').forEach(function(btn) {
    btn.classList.toggle('active', btn.dataset.agent === targetId);
  });
}

// 退出私聊模式
function exitPrivateChat() {
  if (!currentPrivateTarget) return;
  currentPrivateTarget = null;
  var bar = $('private-bar');
  if (bar) {
    bar.classList.remove('visible');
    bar.style.display = 'none';
  }
  document.querySelectorAll('.clone-private-btn').forEach(function(btn) {
    btn.classList.remove('active');
  });
}

// 加载私聊历史
async function loadPrivateHistory(targetId) {
  try {
    var r = await fetch('/api/private/messages?agent_id=agent_main&other_id=' + targetId + '&count=30');
    var d = await r.json();
    if (d.success && d.messages && d.messages.length) {
      d.messages.forEach(function(m) {
        var role = m.from === 'agent_main' ? 'user' : 'agent';
        var label = m.from === targetId ? (getCloneName(targetId) + ' ') : '';
        var bubble = '<div class="msg-bubble" style="border-left:3px solid var(--accent);background:var(--bg-elevated)">';
        if (label) bubble += '<span style="font-size:10px;color:var(--accent);margin-right:6px">' + label + '</span>';
        bubble += escapeHtml(m.content) + '</div>';
        var el = document.createElement('div');
        el.className = 'message msg-' + role + ' msg-private';
        el.innerHTML = bubble;
        $('messages').appendChild(el);
      });
      scrollToBottom();
    }
  } catch(e) {}
}

// 发送私聊消息
async function sendPrivateMessage(toId, text) {
  if (!text.trim() || isProcessing) return;
  isProcessing = true;
  
  addMessage('user', text);
  $('inputText').value = '';
  $('inputText').style.height = 'auto';
  
  var td = document.createElement('div');
  td.className = 'message msg-agent';
  td.id = 'typing-indicator';
  td.innerHTML = '<div class="msg-bubble typing-dots"><span>\u00B7</span><span>\u00B7</span><span>\u00B7</span></div>';
  $('messages').appendChild(td);
  scrollToBottom();
  
  try {
    var r = await fetch('/api/private/send', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({from_id: 'agent_main', to_id: toId, content: text})
    });
    var d = await r.json();
    var ti = $('typing-indicator');
    if (ti) ti.remove();
    
    if (d.success) {
      addMessage('agent', '\u2705 \u5DF2\u53D1\u9001\u79C1\u804A\u6D88\u606F\u5230 ' + getCloneName(toId));
    } else {
      addMessage('error', '\u79C1\u804A\u53D1\u9001\u5931\u8D25: ' + (d.error || ''));
    }
  } catch(e) {
    var ti = $('typing-indicator');
    if (ti) ti.remove();
    addMessage('error', '\u79C1\u804A\u7F51\u7EDC\u9519\u8BEF: ' + e.message);
  }
  
  isProcessing = false;
  $('sendBtn').disabled = false;
  $('stopBtn').disabled = true;
  $('inputText').focus();
}

// 私聊轮询
var privatePollTimer = null;

function startPrivatePolling() {
  privatePollTimer = setInterval(pollPrivateMessages, 3000);
}

async function pollPrivateMessages() {
  if (!currentPrivateTarget) return;
  try {
    var r = await fetch('/api/private/messages?agent_id=agent_main&other_id=' + currentPrivateTarget + '&count=3');
    var d = await r.json();
    if (d.success && d.messages && d.messages.length) {
      // 只显示新消息（不在当前消息列表中的）
      var lastMsg = d.messages[d.messages.length - 1];
      if (lastMsg.from !== 'agent_main' && lastMsg.from === currentPrivateTarget) {
        // 检查是否已经显示了
        var el = $('messages');
        if (el && !el.innerHTML.includes(lastMsg.time ? String(lastMsg.time) : lastMsg.content.slice(0, 20))) {
          addMessage('agent', lastMsg.content);
        }
      }
    }
  } catch(e) {}
}

// 私聊消息通知 badge（更新分身标签）
function updatePrivateBadge(agentId, count) {
  var tab = document.querySelector('.agent-tab[data-agent="' + agentId + '"]');
  if (!tab) return;
  var existing = tab.querySelector('.private-badge');
  if (!existing && count > 0) {
    var badge = document.createElement('span');
    badge.className = 'ping-badge private-badge';
    badge.textContent = count;
    tab.appendChild(badge);
  } else if (existing && count > 0) {
    existing.textContent = count;
  } else if (existing) {
    existing.remove();
  }
}

// 绑定出˽聊按?
(function() {
  var exitBtn = $('private-exit-btn');
  if (exitBtn) {
    exitBtn.addEventListener('click', function() {
      exitPrivateChat();
      loadMainHistory();
    });
  }
})();

// 加载主智能体对话历史
async function loadMainHistory() {
  try {
    var r = await fetch('/api/history?session=' + currentSession);
    var d = await r.json();
    var msgsEl = $('messages');
    if (!msgsEl) return;
    msgsEl.innerHTML = '';
    
    if (d.messages && d.messages.length) {
      d.messages.forEach(function(m) {
        addMessage(m.role || 'agent', m.content);
      });
    } else {
      msgsEl.innerHTML = '<div class="message msg-system"><div class="msg-bubble welcome">\uD83D\uDC4B TrueAgent \u667A\u80FD\u7BA1\u5BB6\u5DF2\u542F\u52A8\uFF01\u8F93\u5165\u6D88\u606F\u5F00\u59CB\u5BF9\u8BDD\u3002</div></div>';
    }
    scrollToBottom();
  } catch(e) {}
}

// ===== 任务编排 / 引擎 / 弹窗（v5.9 已停用——前端无对应 HTML 元素，调用会抛 TypeError 阻断后续代码） =====
// 以下 ~600 行已注释，保留函数体供未来可能的补丁恢复
/*
var orchPackages = [];

// 新建任务
$('orch-new-btn').addEventListener('click', function() {
  $('orch-goal').value = '';
  $('orch-bg').value = '';
  $('orch-quality').value = '';
  $('orch-files').value = '';
  $('orchModal').style.display = 'flex';
});

$('orch-create-btn').addEventListener('click', async function() {
  var goal = $('orch-goal').value.trim();
  if (!goal) { alert('Please enter goal'); return; }
  var bg = $('orch-bg').value.trim();
  var quality = $('orch-quality').value.trim();
  var files = $('orch-files').value.trim().split('\n').map(function(f) { return f.trim(); }).filter(Boolean);
  
  $('orchModal').style.display = 'none';
  addMessage('system', '\uD83D\uDCCB 正在创建任务编排: ' + goal.slice(0, 50) + '...');
  
  try {
    var r = await fetch('/api/orchestrator/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({goal: goal, background: bg, quality: quality, files: files})
    });
    var d = await r.json();
    if (d.success) {
      addMessage('system', '\u2705 任务包已创建: ' + d.package.id);
      // 打开详情
      showOrchDetail(d.package.id);
      pollOrchPackages();
    } else {
      addMessage('error', '创建失败: ' + d.error);
    }
  } catch(e) {
    addMessage('error', '创建失败: ' + e.message);
  }
});

// ѯ任务列表
function startOrchPolling() {
  orchPollTimer = setInterval(pollOrchPackages, 5000);
}

async function pollOrchPackages() {
  try {
    var r = await fetch('/api/orchestrator/packages');
    var d = await r.json();
    if (!d.success) return;
    orchPackages = d.packages || [];
    renderOrchList();
  } catch(e) {}
}

function renderOrchList() {
  var list = $('orch-list');
  if (!list) return;
  if (!orchPackages.length) {
    list.innerHTML = '<div class="orch-empty">暂无编排任务</div>';
    return;
  }
  list.innerHTML = orchPackages.map(function(pkg) {
    var progress = 0;
    var subtasks = pkg.subtasks || [];
    if (subtasks.length) {
      var done = subtasks.filter(function(s) { return s.status === 'completed'; }).length;
      progress = Math.round(done / subtasks.length * 100);
    }
    var statusMap = {
      'pending': '\u23F3 \u7B49\u5F85\u4E2D',
      'decomposing': '\uD83D\uDD04 \u5206\u89E3\u4E2D',
      'decomposed': '\uD83D\uDCCC \u5DF2\u5206\u89E3',
      'assigned': '\uD83D\uDCE6 \u5DF2\u5206\u914D',
      'in_progress': '\uD83D\uDD17 \u8FDB\u884C\u4E2D',
      'completed': '\u2705 \u5DF2\u5B8C\u6210',
      'assembling': '\uD83D\uDD27 \u6574\u5408\u4E2D',
      'done': '\uD83C\uDFC1 \u5DF2\u5B8C\u6210',
      'done_with_errors': '\u26A0\uFE0F \u6709\u9519\u8BEF'
    };
    var statusText = statusMap[pkg.status] || pkg.status;
    var color = progress === 100 ? '#4caf50' : progress > 0 ? '#ff9800' : '#9e9e9e';
    return '<div class="orch-item" data-pkg="' + pkg.id + '">' +
      '<div class="orch-item-title">' + pkg.title.slice(0, 40) + '</div>' +
      '<div class="orch-item-status">' +
        '<span style="color:' + color + '">' + statusText + '</span>' +
        '<span style="margin-left:auto;color:var(--text-muted)">' + progress + '%</span>' +
      '</div>' +
      '<div class="orch-item-progress"><div class="orch-item-progress-bar" style="width:' + progress + '%;background:' + color + '"></div></div>' +
      '</div>';
  }).join('');
  
  list.querySelectorAll('.orch-item').forEach(function(el) {
    el.addEventListener('click', function() {
      showOrchDetail(el.dataset.pkg);
    });
  });
}

// 任务详情
async function showOrchDetail(pkgId) {
  try {
    var r = await fetch('/api/orchestrator/package/' + pkgId);
    var d = await r.json();
    if (!d.success) { addMessage('error', '加载失败: ' + d.error); return; }
    var pkg = d.package;
    
    // 更新详情标
    $('orch-detail-title').textContent = '\uD83D\uDCCB ' + pkg.title;
    
    var html = '';
    
    // 基本信息
    html += '<div style="margin-bottom:12px;padding:8px 12px;background:var(--bg-elevated);border-radius:6px">';
    html += '<div><strong>\u76EE\u6807:</strong> ' + pkg.goal + '</div>';
    if (pkg.background) html += '<div style="margin-top:4px;color:var(--text-muted)"><strong>\u80CC\u666F:</strong> ' + pkg.background + '</div>';
    if (pkg.quality_standards) html += '<div style="margin-top:4px;color:var(--text-muted)"><strong>\u8D28\u91CF\u8981\u6C42:</strong> ' + pkg.quality_standards + '</div>';
    html += '<div style="margin-top:4px;font-size:11px;color:var(--text-muted)">\u72B6\u6001: ' + pkg.status + '</div>';
    html += '</div>';
    
    // 子任务列?
    var subtasks = pkg.subtasks || [];
    if (subtasks.length) {
      html += '<div style="margin-bottom:8px;font-weight:500">\u5B50\u4EFB\u52A1 (' + subtasks.length + ')</div>';
      
      // 分析并分配按?
      html += '<div style="margin-bottom:8px;display:flex;gap:6px">';
      html += '<button class="cfg-btn" id="orch-analyze-btn" data-pkg="' + pkgId + '">\uD83D\uDD0D \u5206\u6790\u667A\u80FD\u4F53</button>';
      html += '<button class="cfg-btn primary" id="orch-assign-all-btn" data-pkg="' + pkgId + '" style="' + (subtasks.length === 0 ? 'display:none' : '') + '">\uD83D\uDCE6 \u81EA\u52A8\u5206\u914D</button>';
      html += '<button class="cfg-btn" id="orch-monitor-btn" data-pkg="' + pkgId + '">\uD83D\uDD0D \u76D1\u63A7\u8FDB\u5EA6</button>';
      html += '<button class="cfg-btn" id="orch-collect-btn" data-pkg="' + pkgId + '">\uD83D\uDCE5 \u6536\u96C6\u7ED3\u679C</button>';
      html += '<button class="cfg-btn" id="orch-report-btn" data-pkg="' + pkgId + '">\uD83D\uDCCA \u62A5\u544A</button>';
      html += '</div>';
      html += '<div style="margin-bottom:8px;display:flex;gap:6px">';
      html += '<button class="cfg-btn primary" id="orch-engine-start-btn" data-pkg="' + pkgId + '" style="background:#8b5cf6;color:#fff">\uD83D\uDE80 \u542F\u52A8\u5FAA\u73AF\u5F15\u64CE</button>';
      html += '<button class="cfg-btn" id="orch-pipeline-btn" data-pkg="' + pkgId + '">\u26A1 \u4E00\u952E\u5B8C\u6574\u7F16\u6392</button>';
      html += '</div>';
      
      // Subtasks table
      subtasks.forEach(function(st, i) {
        var statusMap = {pending:'pending', assigned:'assigned', in_progress:'in_progress', completed:'done', failed:'failed'};
        var icon = statusMap[st.status] || '?';
        var cls = st.status === 'completed' ? ' done' : (st.status === 'failed' ? ' failed' : '');
        var agents = orchPackages.length ? getAvailableAgentOptions(st.assigned_to) : '<span style="color:var(--text-muted)">Waiting analysis</span>';
        
        html += '<div class="orch-subtask' + cls + '">';
        html += '<span>' + icon + '</span>';
        html += '<span class="st-name">' + st.description.slice(0, 40) + '</span>';
        html += '<select class="assign-select" data-st="' + st.id + '">' + agents + '</select>';
        html += '<span class="st-agent" style="font-size:11px;color:var(--text-muted)">' + 
          (st.assigned_to ? getCloneName(st.assigned_to) : 'unassigned') + '</span>';
        html += '<span class="st-status">' + Math.round(st.progress) + '%</span>';
        if (st.result) html += '<span title="' + st.result.slice(0, 50) + '" style="cursor:help">DOC</span>';
        html += '</div>';
      });
    } else {
      html += '<div style="margin-bottom:8px;color:var(--text-muted);font-size:12px">No subtasks. Please decompose or add manually.</div>';
      html += '<div style="margin-bottom:8px;display:flex;gap:6px">';
      html += '<button class="cfg-btn primary" id="orch-decompose-btn" data-pkg="' + pkgId + '">\uD83D\uDD04 \u6DFB\u52A0\u5B50\u4EFB\u52A1</button>';
      html += '<button class="cfg-btn" id="orch-analyze-btn" data-pkg="' + pkgId + '">\uD83D\uDD0D \u5206\u6790\u667A\u80FD\u4F53</button>';
      html += '</div>';
    }
    
    // 终结?
    if (pkg.final_result) {
      html += '<div style="margin-top:12px;padding:8px 12px;background:var(--bg-elevated);border-radius:6px">';
      html += '<div style="font-weight:500;margin-bottom:4px">\u7ED3\u679C</div>';
      var fr = pkg.final_result;
      if (fr.final_summary) html += '<div>' + fr.final_summary + '</div>';
      html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px">\u5B8C\u6210: ' + fr.completed + '/' + fr.total_subtasks + '</div>';
      html += '</div>';
    }
    
    $('orch-detail-body').innerHTML = html;
    
    // 绑定事件
    bindOrchDetailEvents(pkgId);
    
    $('orchDetailPanel').style.display = 'flex';
    
  } catch(e) {
    addMessage('error', '加载任务详情失败: ' + e.message);
  }
}

// 绑定详情面板按钮事件
function bindOrchDetailEvents(pkgId) {
  var analyzeBtn = $('orch-analyze-btn');
  if (analyzeBtn) {
    analyzeBtn.addEventListener('click', async function() {
      addMessage('system', '🔍 正在分析智能体能力...');
      try {
        var r = await fetch('/api/orchestrator/analyze', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({package_id: pkgId})
        });
        var d = await r.json();
        if (d.success && d.suggestions) {
          addMessage('system', '\u2705 Analysis done: ' + d.suggestions.length + ' suggestions');
          showOrchDetail(pkgId);
        } else {
          addMessage('error', '分析失败: ' + (d.error || ''));
        }
      } catch(e) {
        addMessage('error', '分析失败: ' + e.message);
      }
    });
  }
  
  var assignBtn = $('orch-assign-all-btn');
  if (assignBtn) {
    assignBtn.addEventListener('click', async function() {
      addMessage('system', '📦 正在自动分配任务...');
      
      // 收集当前下拉框的选择
      var assigns = {};
      document.querySelectorAll('.assign-select').forEach(function(sel) {
        if (sel.value) assigns[sel.dataset.st] = sel.value;
      });
      
      try {
        var r = await fetch('/api/orchestrator/assign', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({package_id: pkgId, assignment: assigns})
        });
        var d = await r.json();
        if (d.success) {
          addMessage('system', '\u2705 已分配 ' + d.assigned.length + ' 个子任务');
          showOrchDetail(pkgId);
        } else {
          addMessage('error', '分配失败: ' + (d.error || ''));
        }
      } catch(e) {
        addMessage('error', '分配失败: ' + e.message);
      }
    });
  }
  
  var monitorBtn = $('orch-monitor-btn');
  if (monitorBtn) {
    monitorBtn.addEventListener('click', async function() {
      try {
        var r = await fetch('/api/orchestrator/monitor', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({package_id: pkgId})
        });
        var d = await r.json();
        if (d.success) {
          showOrchDetail(pkgId);
          addMessage('system', '\uD83D\uDD0D Progress synced');
        }
      } catch(e) {}
    });
  }
  
  var collectBtn = $('orch-collect-btn');
  if (collectBtn) {
    collectBtn.addEventListener('click', async function() {
      try {
        var r = await fetch('/api/orchestrator/collect', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({package_id: pkgId})
        });
        var d = await r.json();
        if (d.success) {
          addMessage('system', '\u2705 Collected: ' + d.completed + '/' + (d.completed + d.failed + d.pending) + ' results');
          showOrchDetail(pkgId);
        }
      } catch(e) {}
    });
  }
  
  var reportBtn = $('orch-report-btn');
  if (reportBtn) {
    reportBtn.addEventListener('click', async function() {
      addMessage('system', '\uD83D\uDCCA 正在生成报告...');
      try {
        var r = await fetch('/api/orchestrator/report', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({package_id: pkgId})
        });
        var d = await r.json();
        if (d.success && d.report) {
          var rpt = d.report;
          addMessage('system', 
            '\uD83D\uDCCA \u62A5\u544A: ' + rpt.title +
            ' | \u8FDB\u5EA6: ' + rpt.progress_pct + '%' +
            ' | \u5B8C\u6210: ' + rpt.completed + '/' + rpt.total_tasks +
            (rpt.failed ? ' | \u5931\u8D25: ' + rpt.failed : '')
          );
        }
      } catch(e) {}
    });
  }
  
  var decomposeBtn = $('orch-decompose-btn');
  if (decomposeBtn) {
    decomposeBtn.addEventListener('click', function() {
      var desc = prompt('输入子任务描?');
      if (!desc) return;
      addSubtaskManually(pkgId, desc);
    });
  }

  // 循环引擎启动按钮
  var cycleBtn = $('orch-cycle-btn');
  if (!cycleBtn) {
    // 动添加启动循玻ť详情面板底部
    var detailBody = $('orch-detail-body');
    if (detailBody) {
      var cycleRow = document.createElement('div');
      cycleRow.style.cssText = 'margin-top:12px;padding-top:12px;border-top:1px solid var(--border);display:flex;gap:6px;flex-wrap:wrap';
      cycleRow.innerHTML = '' +
        '<button class="cfg-btn primary" id="orch-cycle-btn" data-pkg="' + pkgId + '">\uD83D\uDD04 \u542F\u52A8\u5FAA\u73AF\u8C03\u5EA6</button>' +
        '<span class="cfg-label" id="orch-cycle-status" style="font-size:11px;color:var(--text-muted);display:flex;align-items:center"></span>';
      detailBody.appendChild(cycleRow);
    }
  }

  // 绑定循环启动
  var cycleBtn2 = $('orch-cycle-btn');
  if (cycleBtn2) {
    cycleBtn2.addEventListener('click', async function() {
      var btn = $('orch-cycle-btn');
      var status = $('orch-cycle-status');
      if (btn) btn.disabled = true;
      if (status) status.textContent = '\u23F3 \u542F\u52A8\u4E2D...';
      
      try {
        var r = await fetch('/api/engine/start', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            package_id: pkgId,
            max_rounds: 3,
            dispatch_ratio: 0.5
          })
        });
        var d = await r.json();
        if (d.success) {
          if (status) status.textContent = '\u2705 \u5FAA\u73AF\u5DF2\u542F\u52A8';
          addMessage('system', '\uD83D\uDD04 \u5FAA\u73AF\u8C03\u5EA6\u5DF2\u542F\u52A8\uFF0C\u7CFB\u7EDF\u5C06\u6309\u8F6E\u6B21\u5206\u53D1/\u6536\u96C6/\u5206\u6790/\u91CD\u5206\u914D');
          startCyclePolling();
        } else {
          if (status) status.textContent = '\u274C \u5931\u8D25: ' + (d.error || '');
          if (btn) btn.disabled = false;
        }
      } catch(e) {
        if (status) status.textContent = '\u274C ' + e.message;
        if (btn) btn.disabled = false;
      }
    });
  }
  
  // 一键编排（pipeline）
  var pipelineBtn = document.querySelector('#orch-pipeline-btn[data-pkg="' + pkgId + '"]');
  if (pipelineBtn) {
    pipelineBtn.addEventListener('click', async function() {
      addMessage('system', '⚡ 启动一键编排流水线...');
      var btn = pipelineBtn;
      btn.disabled = true;
      try {
        var pkgResp = await fetch('/api/orchestrator/package/' + pkgId);
        var pkgData = await pkgResp.json();
        if (!pkgData.success) { addMessage('error', '获取任务包失败'); btn.disabled = false; return; }
        var pkg = pkgData.package;
        
        var r = await fetch('/api/orchestrator/pipeline', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            goal: pkg.goal,
            background: pkg.background || '',
            quality: pkg.quality_standards || '',
            files: pkg.files || [],
            auto_start: true
          })
        });
        var d = await r.json();
        if (d.success) {
          addMessage('system', '✅ 一键编排完成！共 ' + d.steps.length + ' 个步骤');
          d.steps.forEach(function(s) {
            addMessage('system', '  ' + (s.status === 'ok' ? '✅' : '⏭️') + ' ' + s.step + ': ' + JSON.stringify(s).slice(0, 80));
          });
          showOrchDetail(d.package.id);
          startCyclePolling();
        } else {
          addMessage('error', '编排失败: ' + (d.error || ''));
        }
      } catch(e) {
        addMessage('error', '编排失败: ' + e.message);
      }
      btn.disabled = false;
    });
  }
  
  // 启动循环引擎按钮
  var engineBtn = document.querySelector('#orch-engine-start-btn[data-pkg="' + pkgId + '"]');
  if (engineBtn) {
    engineBtn.addEventListener('click', async function() {
      var btn = engineBtn;
      btn.disabled = true;
      btn.textContent = '⏳ 启动中...';
      addMessage('system', '🚀 启动循环引擎...');
      try {
        var r = await fetch('/api/engine/start', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            package_id: pkgId,
            max_rounds: 3,
            dispatch_ratio: 0.5
          })
        });
        var d = await r.json();
        if (d.success) {
          addMessage('system', '🔄 循环调度已启动，系统将按轮次分发/收集/分析/重分配');
          btn.textContent = '✅ 已启动';
          startCyclePolling();
        } else {
          addMessage('error', '引擎启动失败: ' + (d.error || ''));
          btn.textContent = '🚀 启动循环引擎';
          btn.disabled = false;
        }
      } catch(e) {
        addMessage('error', '引擎启动失败: ' + e.message);
        btn.textContent = '🚀 启动循环引擎';
        btn.disabled = false;
      }
    });
  }
}

// 手动添加子任?
async function addSubtaskManually(pkgId, description) {
  var subtask = {
    id: 'st_manual_' + Date.now(),
    package_id: pkgId,
    description: description,
    background: '',
    requirements: '',
    quality_standards: '',
    assigned_to: '',
    files: [],
    dependencies: [],
    status: 'pending',
    progress: 0,
    result: '',
    error: '',
    created_at: Date.now() / 1000,
    assigned_at: null,
    completed_at: null
  };
  
  try {
    var r = await fetch('/api/orchestrator/add-subtask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({package_id: pkgId, subtask: subtask})
    });
    var d = await r.json();
    if (d.success) {
      addMessage('system', '\u2705 已添加子任务: ' + description.slice(0, 30));
      showOrchDetail(pkgId);
    } else {
      addMessage('error', '添加失败: ' + d.error);
    }
  } catch(e) {
    addMessage('error', '添加失败: ' + e.message);
  }
}

// 获取叵㔨智能体项列表
function getAvailableAgentOptions(selected) {
  var opts = '<option value="">\u81EA\u52A8</option>';
  opts += '<option value="agent_main"' + (selected === 'agent_main' ? ' selected' : '') + '>\u4E3B\u667A\u80FD\u7BA1\u5BB6</option>';
  if (clones && clones.length) {
    clones.forEach(function(c) {
      var name = getCloneName(c.id);
      opts += '<option value="' + c.id + '"' + (selected === c.id ? ' selected' : '') + '>' + name + '</option>';
    });
  }
  return opts;
}

// 鍒濆始鍖?
setTimeout(function() {
  startOrchPolling();
}, 1000);

// ===== 循环引擎轮询 =====
var cyclePollTimer = null;

function startCyclePolling() {
  if (cyclePollTimer) clearInterval(cyclePollTimer);
  cyclePollTimer = setInterval(pollCycles, 5000);
}

async function pollCycles() {
  try {
    var r = await fetch('/api/engine/cycles');
    var d = await r.json();
    if (!d.success || !d.cycles) return;
    
    var cycles = d.cycles;
    var hasActive = false;
    
    Object.keys(cycles).forEach(function(pkgId) {
      var c = cycles[pkgId];
      if (c.status === 'cycling' || c.status === 'paused') {
        hasActive = true;
        
        // 更新详情面板状?
        var statusEl = $('orch-cycle-status');
        if (statusEl) {
          var pct = 0;
          var total = c.completed_ids.length + c.failed_ids.length + c.pending_queue.length + c.active_ids.length;
          if (total > 0) {
            pct = Math.round((c.completed_ids.length + (c.done_by_self_ids || []).length) / total * 100);
          }
          statusEl.textContent = '\u23F3 \u7B2C' + c.current_round + '/' + c.max_rounds + '\u8F6E | ' +
            '\u5F85\u53D1: ' + c.pending_queue.length + ' | ' +
            '\u6D3B\u8DC3: ' + c.active_ids.length + ' | ' +
            '\u5B8C\u6210: ' + c.completed_ids.length + ' | ' +
            '\u5931\u8D25: ' + c.failed_ids.length + ' | ' +
            pct + '%';
        }
        
        // 更新侧栏状?
        if (c.user_messages && c.user_messages.length) {
          c.user_messages.forEach(function(msg) {
            addMessage('system', '\uD83D\uDCE2 ' + msg.message);
          });
          // 清空ѶϢ
          cycles[pkgId].user_messages = [];
        }
      }
    });
    
    if (!hasActive && cyclePollTimer) {
      // 鎵有循环都结束了，降低轮询频率
    }
  } catch(e) {}
}

// 添加ѭ状到侧栏面板
(function() {
  // 在任务编排面板添加循玵㊶态
  var list = $('orch-list');
  if (list) {
    var statusRow = document.createElement('div');
    statusRow.id = 'cycle-status-row';
    statusRow.style.cssText = 'margin-top:6px;padding:4px 8px;font-size:11px;color:var(--text-muted);display:none';
    statusRow.textContent = '\u23F3 \u5FAA\u73AF\u72B6\u6001\u67E5\u8BE2\u4E2D...';
    list.parentNode.insertBefore(statusRow, list.nextSibling);
  }
})();

// 暂停/恢复循环（从侧栏控制）
async function pauseCycle(pkgId) {
  try {
    var r = await fetch('/api/engine/pause', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({package_id: pkgId})
    });
    return await r.json();
  } catch(e) {
    return {success: false, error: e.message};
  }
}

async function resumeCycle(pkgId) {
  try {
    var r = await fetch('/api/engine/resume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({package_id: pkgId})
    });
    return await r.json();
  } catch(e) {
    return {success: false, error: e.message};
  }
}
*/

// ===== 弹出独立窗口（已停用——v5.9 无多标签页UI） =====
/*
async function popoutAgentTab(agentId, port) {
  var baseUrl = location.protocol + '//' + location.hostname + ':' + (location.port || '80');
  var popoutUrl = baseUrl + '/?agent=' + encodeURIComponent(agentId) + '&port=' + port + '&popout=1';
  var w = window.open(popoutUrl, 'trueagent_popout_' + agentId, 
    'width=600,height=800,menubar=no,toolbar=no,location=no,status=no,resizable=yes');
  if (w) {
    addMessage('system', '\uD83D\uDD39 ' + getCloneName(agentId) + ' \u5DF2\u5F39\u51FA\u72EC\u7ACB\u7A97\u53E3');
    try { w.focus(); } catch(e) {}
  } else {
    addMessage('system', '\u26A0\uFE0F \u5F39\u7A97\u88AB\u62E6\u622A\uFF0C\u8BF7\u5141\u8BB8\u5F39\u51FA\u7A97\u53E3');
  }
}
*/

// ===== 审批面板轮询 v2（已停用——v1 版本 L880 已覆盖此功能） =====
/*
function startApprovalPolling() {
  async function poll() {
    try {
      const r = await fetch('/api/pending-modify');
      const d = await r.json();
      renderApprovalList(d.proposals || []);
    } catch(e) { // silenced }
    setTimeout(poll, 15000);  // 每15秒轮询
  }
  poll();
}
function renderApprovalList(proposals) {
  const container = document.getElementById('approvalList');
  if (!container) return;
  if (!proposals.length) {
    container.innerHTML = '<div class="approval-empty">暂无待审批修改</div>';
    return;
  }
  let html = '';
  proposals.forEach(p => {
    const remaining = Math.max(0, Math.floor((p.expire - Date.now()/1000) / 60));
    html += '<div class="approval-card">';
    html += '<div class="approval-summary">' + escHtml(p.summary || '系统维护建议') + '</div>';
    html += '<div class="approval-detail">' + escHtml((p.detail || '').substring(0, 120)) + '</div>';
    if (p.analysis) html += '<div class="approval-analysis">' + escHtml(p.analysis.substring(0, 150)) + '</div>';
    html += '<div class="approval-meta">⏱ ' + remaining + '分钟后自动决策</div>';
    html += '<div class="approval-actions">';
    html += '<button class="approval-btn approve" onclick="decideApproval(\'' + p.id + '\',\'approve\')">✅ 批准</button>';
    html += '<button class="approval-btn reject" onclick="decideApproval(\'' + p.id + '\',\'reject\')">❌ 拒绝</button>';
    html += '</div></div>';
  });
  container.innerHTML = html;
}
async function decideApproval(id, decision) {
  try {
    const r = await fetch('/api/modify-decision', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({proposal_id: id, decision})
    });
    const d = await r.json();
    if (d.ok) {
      addMessage('system', (decision === 'approve' ? '✅ 已批准' : '❌ 已拒绝') + '修改提案 #' + id);
    }
  } catch(e) { addMessage('error', '审批操作失败: ' + e.message); }
}
*/

// ===== 工具函数 =====
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ===== 上下文压缩 =====
function compressOldMessages() {
  const msgs = $('messages').querySelectorAll('.message:not(.msg-system)');
  if (msgs.length < 20) { addMessage('system', '消息不多，无需压缩'); return; }
  // 保留最近 15 条，其余折叠
  let count = 0;
  const keep = 15;
  const toFold = msgs.length - keep;
  msgs.forEach((m, i) => {
    if (i < toFold) { m.classList.add('compressed'); count++; }
    else m.classList.remove('compressed');
  });
  // 插入展开按钮
  let expBtn = $('expandOldBtn');
  if (!expBtn) {
    expBtn = document.createElement('div');
    expBtn.id = 'expandOldBtn';
    expBtn.className = 'message msg-system';
    expBtn.innerHTML = '<div class="msg-bubble expand-old" style="cursor:pointer;text-align:center;opacity:0.7;font-size:12px;padding:6px">📜 展开 ' + count + ' 条旧消息</div>';
    expBtn.onclick = function() {
      $('messages').querySelectorAll('.compressed').forEach(m => m.classList.remove('compressed'));
      expBtn.remove();
    };
    $('messages').insertBefore(expBtn, msgs[toFold]);
  }
  addMessage('system', '🗜 已折叠 ' + count + ' 条旧消息（保留最近 ' + keep + ' 条）');
}

// ===== 审批轮询 =====
window._approvalPollTimer = null;
function pollApprovalProposals() {
  fetch('/api/pending-modify')
    .then(r => r.json())
    .then(data => {
      var proposals = data.proposals || [];
      var panel = document.getElementById('approval-panel');
      var list = document.getElementById('approval-list');
      var badge = document.getElementById('approval-count');
      
      if (!panel || !list) return;
      
      if (proposals.length > 0) {
        panel.style.display = 'flex';
        badge.textContent = proposals.length;
        
        var html = '';
        proposals.forEach(function(p) {
          var desc = (p.description || p.reason || p.summary || '无描述').substring(0, 120);
          var target = (p.target || p.file || '').substring(0, 60);
          var id = p.id || '';
          html += '<div class="approval-item" data-id="' + id + '">' +
            '<div class="prop-desc">' + h(desc) + '</div>' +
            (target ? '<div class="prop-meta">📁 ' + h(target) + '</div>' : '') +
            '<div class="prop-actions">' +
            '<button class="prop-btn approve" onclick="decideApproval(\'' + id + '\',\'approve\',this)">✅ 批准</button>' +
            '<button class="prop-btn reject" onclick="decideApproval(\'' + id + '\',\'reject\',this)">❌ 拒绝</button>' +
            '</div></div>';
        });
        list.innerHTML = html;
      } else {
        // 无待审批项
        if (panel.style.display === 'flex') {
          list.innerHTML = '<div class="approval-empty">✅ 暂无待审批提案</div>';
        }
        badge.textContent = '0';
      }
    })
    .catch(function(e) { console.log('审批轮询异常:', e); });
}

window._approvalPollTimer = setInterval(pollApprovalProposals, 15000);

function decideApproval(proposalId, decision, btn) {
  if (!proposalId) return;
  // 禁用按钮防重复点击
  var item = btn.closest('.approval-item');
  if (item) item.querySelectorAll('.prop-btn').forEach(function(b) { b.disabled = true; });
  
  fetch('/api/modify-decision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ proposal_id: proposalId, decision: decision })
  })
    .then(r => r.json())
    .then(function(res) {
      if (item) {
        item.style.opacity = '0.5';
        item.querySelector('.prop-actions').innerHTML = 
          decision === 'approve' ? '<span style="color:#22c55e">✅ 已批准</span>' : 
          '<span style="color:#ef4444">❌ 已拒绝</span>';
      }
      // 刷新列表
      setTimeout(pollApprovalProposals, 500);
    })
    .catch(function(e) { console.error('审批决策失败:', e); });
}

// 初始轮询（延迟等页面初始化完成）
setTimeout(pollApprovalProposals, 3000);

// ===== 多 Key 智能池模式：分身自动从池取 Key，用户无需配置 =====

window.__appInited = true;
console.log('TrueAgent WebUI v5.9 loaded (Multi-Key Pool Mode)');

