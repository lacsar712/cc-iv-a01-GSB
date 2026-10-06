<template>
  <main>
    <div v-if="!session" class="login-wrap">
      <h1>光伏组串IV扫描台</h1>
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>

    <div v-else class="station">
      <header class="topbar">
        <span class="brand">光伏组串IV扫描台</span>
        <nav class="tabs">
          <button :class="{ on: view === 'overview' }" @click="view = 'overview'">总览</button>
          <button :class="{ on: view === 'submit' }" @click="view = 'submit'">交扫</button>
          <button :class="{ on: view === 'codes' }" @click="view = 'codes'">贴码口</button>
          <button class="secondary" @click="logout">退出</button>
        </nav>
        <span class="who">{{ session.username }}（{{ isWriter ? "扫描员" : "观察员" }}）</span>
      </header>

      <div v-if="view === 'overview'" class="wrap">
        <section>
          <h2>扫描总览</h2>
          <table>
            <thead>
              <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>状态</th><th>结论</th><th>单据</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in logs" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.string_code }}</td>
                <td>{{ row.voc_v }}</td>
                <td>{{ row.isc_a }}</td>
                <td>{{ row.fill_factor }}</td>
                <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '等候处理' : '已完成' }}</span></td>
                <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
                <td><button class="link" @click="openDoc(row)">查看</button></td>
              </tr>
              <tr v-if="!logs.length"><td colspan="8" class="muted">还没有扫描记录</td></tr>
            </tbody>
          </table>
        </section>
      </div>

      <div v-else-if="view === 'submit'" class="wrap">
        <section v-if="isWriter">
          <h2>交扫</h2>
          <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05" />
          <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
          <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
          <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
          <button :disabled="loading" @click="submit">提交扫描</button>
          <p v-if="error" class="err">{{ error }}</p>
          <p class="muted">组串没贴现场二维码就禁止入队，请先到贴码口贴码。</p>
        </section>
        <section v-else>
          <h2>交扫</h2>
          <p class="muted">观察员只能翻牌册和单据，不能改贴也不能报送。</p>
        </section>
      </div>

      <div v-else-if="view === 'codes'" class="codes-page">
        <div class="codes-head">
          <h2>贴码口</h2>
          <form v-if="isWriter" class="paste-form" @submit.prevent="paste">
            <input v-model="pasteString" placeholder="组串编号，例如 阵列A-串03" />
            <input v-model="pasteQr" placeholder="现场码号，例如 QR-A-001" />
            <button type="submit" :disabled="loading">贴码</button>
          </form>
          <p v-else class="muted">观察员可翻牌册与单据上的码，不能改贴也不能报送。</p>
          <p v-if="codesError" class="err">{{ codesError }}</p>
          <p v-if="codesOk" class="okmsg">{{ codesOk }}</p>
        </div>
        <div class="panels">
          <section class="panel">
            <h3>待贴清单</h3>
            <ul v-if="board.pending.length">
              <li v-for="code in board.pending" :key="code">{{ code }}</li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
          <section class="panel">
            <h3>已贴清单</h3>
            <ul v-if="board.pasted.length">
              <li v-for="b in board.pasted" :key="b.id">
                <strong>{{ b.string_code }}</strong> — 码号 {{ b.qr_code }}
                <span class="muted">（{{ b.pasted_by }} 贴于 {{ fmt(b.pasted_at) }}）</span>
              </li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
          <section class="panel">
            <h3>退回原因</h3>
            <ul v-if="board.rejections.length">
              <li v-for="r in board.rejections" :key="r.id">
                <strong>{{ r.string_code }}</strong>：{{ r.reason }}
                <span class="muted">（{{ r.attempted_by }} {{ fmt(r.created_at) }}）</span>
              </li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
        </div>
      </div>
    </div>

    <div v-if="doc" class="mask" @click.self="doc = null">
      <div class="doc">
        <h3>扫描单据 #{{ doc.id }}</h3>
        <dl>
          <dt>组串</dt><dd>{{ doc.string_code }}</dd>
          <dt>现场码号</dt><dd>{{ doc.qr_code || "—" }}</dd>
          <dt>开路电压</dt><dd>{{ doc.voc_v }} V</dd>
          <dt>短路电流</dt><dd>{{ doc.isc_a }} A</dd>
          <dt>填充因子</dt><dd>{{ doc.fill_factor }}</dd>
          <dt>状态</dt><dd>{{ doc.status === 'pending' ? '等候处理' : '已完成' }}</dd>
          <dt>结论</dt><dd>{{ doc.verdict || "—" }}</dd>
          <dt>原因</dt><dd>{{ doc.reason || "—" }}</dd>
          <dt>提交人</dt><dd>{{ doc.created_by }}</dd>
          <dt>提交时间</dt><dd>{{ fmt(doc.created_at) }}</dd>
          <dt>处理时间</dt><dd>{{ doc.processed_at ? fmt(doc.processed_at) : "—" }}</dd>
        </dl>
        <button class="secondary" @click="doc = null">关闭</button>
      </div>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const session = ref(null);
const view = ref("overview");
const logs = ref([]);
const board = ref({ pending: [], pasted: [], rejections: [] });
const doc = ref(null);
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const pasteString = ref("");
const pasteQr = ref("");
const error = ref("");
const codesError = ref("");
const codesOk = ref("");
const loading = ref(false);
let timer;

const isWriter = computed(() => session.value?.role === "writer");

function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}

function fmt(t) {
  if (!t) return "—";
  const d = new Date(t);
  return isNaN(d) ? t : d.toLocaleString();
}

async function refresh() {
  if (!session.value) return;
  let logsRes, boardRes;
  try {
    [logsRes, boardRes] = await Promise.all([
      fetch("/api/logs", { headers: headers() }),
      fetch("/api/codes/board", { headers: headers() }),
    ]);
  } catch { return; }
  if (logsRes.status === 401 || boardRes.status === 401) { logout(); return; }
  if (logsRes.ok) {
    logs.value = await logsRes.json();
    if (doc.value) {
      const fresh = logs.value.find((r) => r.id === doc.value.id);
      if (fresh) doc.value = fresh;
    }
  }
  if (boardRes.ok) board.value = await boardRes.json();
}

function startPolling() {
  if (timer) clearInterval(timer);
  timer = setInterval(refresh, 2000);
}

async function login() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: loginUser.value, password: loginPass.value }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "登录失败"; return; }
    session.value = { token: data.access_token, username: data.username, role: data.role };
    localStorage.setItem("pv_session", JSON.stringify(session.value));
    view.value = "overview";
    await refresh();
    startPolling();
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}

function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  board.value = { pending: [], pasted: [], rejections: [] };
  doc.value = null;
  view.value = "overview";
  localStorage.removeItem("pv_session");
}

async function submit() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({
        string_code: stringCode.value,
        voc_v: Number(voc.value),
        isc_a: Number(isc.value),
        fill_factor: Number(ff.value),
      }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "提交失败"; await refresh(); return; }
    stringCode.value = voc.value = isc.value = ff.value = "";
    await refresh();
    view.value = "overview";
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}

async function paste() {
  codesError.value = "";
  codesOk.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/codes/paste", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ string_code: pasteString.value, qr_code: pasteQr.value }),
    });
    const data = await res.json();
    if (!res.ok) { codesError.value = data.detail || "贴码失败"; await refresh(); return; }
    codesOk.value = `已贴码并入队：${data.string_code} — ${data.qr_code}`;
    pasteString.value = pasteQr.value = "";
    await refresh();
  } catch { codesError.value = "贴码时网络异常"; }
  finally { loading.value = false; }
}

function openDoc(row) {
  doc.value = row;
}

onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refresh();
      startPolling();
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>

<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { min-height: 100vh; }
h1 { color: #86efac; margin: 0 0 0.25rem; }
h2 { color: #86efac; margin: 0 0 0.75rem; font-size: 1.1rem; }
h3 { color: #86efac; margin: 0 0 0.6rem; font-size: 1rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
.login-wrap { max-width: 560px; margin: 0 auto; padding: 3rem 1.5rem; }
.wrap { max-width: 980px; margin: 0 auto; padding: 1.25rem 1.5rem; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button.secondary { background: #365314; }
button.link { background: transparent; color: #86efac; text-decoration: underline; padding: 0.1rem 0.3rem; margin: 0; font-weight: 500; }
.err { color: #fecaca; }
.okmsg { color: #bbf7d0; }
.muted { color: #a7f3d0; opacity: 0.75; font-size: 0.85rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }

.station { min-height: 100vh; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 1rem; background: #14532d; border-bottom: 1px solid #166534; position: sticky; top: 0; z-index: 5; }
.brand { color: #86efac; font-weight: 700; margin-right: 0.5rem; white-space: nowrap; }
.tabs { display: flex; gap: 0.4rem; }
.tabs button { margin-right: 0; background: #365314; }
.tabs button.on { background: #16a34a; box-shadow: 0 0 0 2px #4ade80 inset; }
.who { margin-left: auto; color: #a7f3d0; font-size: 0.85rem; white-space: nowrap; }

.codes-page { flex: 1; display: flex; flex-direction: column; gap: 1rem; padding: 1rem 1.25rem 1.25rem; min-height: 0; }
.codes-head { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; }
.paste-form { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.paste-form input { flex: 1 1 220px; margin-bottom: 0; }
.paste-form button { margin-right: 0; }
.panels { flex: 1; display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; min-height: 0; }
.panel { margin-bottom: 0; overflow: auto; }
.panel ul { margin: 0; padding-left: 1.1rem; }
.panel li { margin-bottom: 0.45rem; }
.empty { color: #a7f3d0; opacity: 0.8; }
@media (max-width: 820px) { .panels { grid-template-columns: 1fr; } }

.mask { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55); display: flex; align-items: center; justify-content: center; z-index: 20; }
.doc { background: #14532d; border: 1px solid #166534; border-radius: 10px; padding: 1.25rem 1.5rem; width: min(520px, 92vw); max-height: 86vh; overflow: auto; }
.doc dl { display: grid; grid-template-columns: 6.5rem 1fr; gap: 0.35rem 0.75rem; margin: 0 0 1rem; }
.doc dt { color: #a7f3d0; }
.doc dd { margin: 0; }
</style>
