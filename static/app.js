// 活动报名页：输入模拟用户 ID 报名，显示剩余名额与报名名单
const API = '/api';
const $ = (id) => document.getElementById(id);

function setMsg(text, bad = false) {
  const el = $('msg');
  el.textContent = text;
  el.className = bad ? 'msg bad' : 'msg';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// 拉取活动状态（剩余名额 + 名单）并渲染
async function load() {
  try {
    const res = await fetch(`${API}/activity`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (e) {
    setMsg(`加载失败：${e.message}`, true);
  }
}

function render(a) {
  $('title').textContent = a.title;
  const left = $('remaining');
  left.textContent = a.remaining;
  left.classList.toggle('full', a.remaining <= 0);

  $('list-count').textContent = `（${a.signups.length} 人）`;
  const list = $('list');
  if (!a.signups.length) {
    list.innerHTML = '<li class="empty">暂无报名</li>';
    return;
  }
  list.innerHTML = a.signups.map((s) => `
    <li>
      <span class="seat">${s.seat_no ?? '-'}</span>
      <span class="who">${escapeHtml(s.user_id)}</span>
      <span class="when">${(s.created_at || '').replace('T', ' ').slice(0, 19)}</span>
      <button class="cancel" data-cancel="${escapeHtml(s.user_id)}">取消报名</button>
    </li>`).join('');
}

// 单个用户报名
async function signup() {
  const user_id = $('uid').value.trim();
  if (!user_id) { setMsg('请先输入模拟用户 ID', true); return; }

  const btn = $('btn-signup');
  btn.disabled = true;                    // 防连点（真正的防重靠后端唯一键）
  try {
    const res = await fetch(`${API}/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setMsg(data.message || '报名成功');
    } else {
      setMsg(data.detail || `报名失败（HTTP ${res.status}）`, true);
    }
    await load();
  } catch (e) {
    setMsg(`请求失败：${e.message}`, true);
  } finally {
    btn.disabled = false;
  }
}

// 取消报名（名单里每一行的「取消报名」按钮）
async function cancel(user_id, btn) {
  if (!confirm(`确定取消 ${user_id} 的报名？名额会归还。`)) return;
  btn.disabled = true;
  try {
    const res = await fetch(`${API}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      setMsg(data.message || '已取消报名');
    } else {
      setMsg(data.detail || `取消失败（HTTP ${res.status}）`, true);
    }
    await load();
  } catch (e) {
    setMsg(`请求失败：${e.message}`, true);
    btn.disabled = false;
  }
}

async function reset() {
  if (!confirm('确定重置活动？会清空所有报名记录并释放座位。')) return;
  await fetch(`${API}/admin/reset`, { method: 'POST', cache: 'no-store' });
  setMsg('已重置');
  await load();
}

window.addEventListener('DOMContentLoaded', () => {
  $('btn-signup').addEventListener('click', signup);
  $('uid').addEventListener('keydown', (e) => { if (e.key === 'Enter') signup(); });
  $('btn-refresh').addEventListener('click', load);
  $('btn-reset').addEventListener('click', reset);
  $('list').addEventListener('click', (e) => {           // 事件委托：名额行是动态渲染的
    const btn = e.target.closest('button[data-cancel]');
    if (btn) cancel(btn.dataset.cancel, btn);
  });
  load();
  setInterval(load, 5000);   // 每 5 秒自动刷新名额与名单
});
