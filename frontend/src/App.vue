<template>
  <main :class="{ wide: view === 'labels' }">
    <h1>光伏组串IV扫描台</h1>
    <div v-if="!session">
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>
    <div v-else>
      <header class="topbar">
        <nav>
          <button :class="{ active: view === 'overview' }" @click="view = 'overview'">总览</button>
          <button :class="{ active: view === 'submit' }" @click="view = 'submit'">交扫</button>
          <button :class="{ active: view === 'labels' }" @click="view = 'labels'">贴码口</button>
          <button class="secondary" @click="logout">退出</button>
        </nav>
        <span class="who">{{ session.username }}（{{ isWriter ? "可提交" : "只读" }}）</span>
      </header>

      <section v-if="view === 'overview'">
        <div class="bar">
          <h2>扫描总览</h2>
          <button class="secondary" @click="refresh">刷新列表</button>
        </div>
        <table>
          <thead>
            <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>状态</th><th>结论</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in logs" :key="row.id" class="clickable" @click="openDoc(row.id)">
              <td>{{ row.id }}</td>
              <td>{{ row.string_code }}</td>
              <td>{{ row.voc_v }}</td>
              <td>{{ row.isc_a }}</td>
              <td>{{ row.fill_factor }}</td>
              <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '待处理' : '已完成' }}</span></td>
              <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
            </tr>
          </tbody>
        </table>
        <p class="hint">点击任意一行可打开那份单据，查看码号等完整信息。</p>
      </section>

      <section v-if="view === 'submit'">
        <h2>提交扫描</h2>
        <template v-if="isWriter">
          <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05（须先在贴码口贴码）" />
          <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
          <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
          <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
          <button :disabled="loading" @click="submit">提交扫描</button>
          <p v-if="error" class="err">{{ error }}</p>
        </template>
        <p v-else class="hint">观察员只读，不能报送扫描。</p>
      </section>

      <div v-if="view === 'labels'" class="labels-page">
        <section v-if="isWriter" class="label-form">
          <h2>登记贴码</h2>
          <label>组串编号</label>
          <input v-model="labelString" list="pendingStrings" placeholder="待贴清单里的组串，或手工输入" />
          <datalist id="pendingStrings">
            <option v-for="p in board.pending" :key="p.string_code" :value="p.string_code" />
          </datalist>
          <label>现场二维码</label><input v-model="labelQr" placeholder="例如 QR-阵列C-串05" />
          <button :disabled="loading" @click="stick">贴码</button>
          <p v-if="labelError" class="err">{{ labelError }}</p>
          <p v-if="labelOk" class="okmsg">{{ labelOk }}</p>
        </section>
        <section v-else class="label-form">
          <p class="hint">观察员可以翻牌册和单据上的码，但不能改贴。</p>
        </section>
        <div class="panes">
          <section class="pane">
            <h2>待贴清单</h2>
            <ul v-if="board.pending.length">
              <li v-for="p in board.pending" :key="p.string_code">{{ p.string_code }}</li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
          <section class="pane">
            <h2>已贴清单</h2>
            <ul v-if="board.labeled.length">
              <li v-for="l in board.labeled" :key="l.id">
                <b>{{ l.string_code }}</b> → {{ l.qr_code }}
                <small>{{ l.labeled_by }} · {{ fmt(l.labeled_at) }}</small>
              </li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
          <section class="pane">
            <h2>退回原因</h2>
            <ul v-if="board.rejections.length">
              <li v-for="r in board.rejections" :key="r.id">
                <b>{{ r.string_code }}</b>：{{ r.reason }}
                <small>{{ r.attempted_by }} · {{ fmt(r.attempted_at) }}</small>
              </li>
            </ul>
            <p v-else class="empty">还没有贴码痕迹</p>
          </section>
        </div>
      </div>

      <div v-if="doc" class="mask" @click.self="doc = null">
        <section class="doc">
          <h2>单据 #{{ doc.id }}</h2>
          <dl>
            <dt>组串</dt><dd>{{ doc.string_code }}</dd>
            <dt>码号</dt><dd>{{ doc.qr_code || "未贴码" }}</dd>
            <dt>开路电压</dt><dd>{{ doc.voc_v }} V</dd>
            <dt>短路电流</dt><dd>{{ doc.isc_a }} A</dd>
            <dt>填充因子</dt><dd>{{ doc.fill_factor }}</dd>
            <dt>状态</dt><dd>{{ doc.status === 'pending' ? '待处理' : '已完成' }}</dd>
            <dt>结论</dt><dd>{{ doc.verdict || "—" }}</dd>
            <dt>原因</dt><dd>{{ doc.reason || "—" }}</dd>
            <dt>提交人</dt><dd>{{ doc.created_by }}</dd>
            <dt>提交时间</dt><dd>{{ fmt(doc.created_at) }}</dd>
            <dt>处理时间</dt><dd>{{ doc.processed_at ? fmt(doc.processed_at) : "—" }}</dd>
          </dl>
          <button class="secondary" @click="doc = null">关闭</button>
        </section>
      </div>
    </div>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
const session = ref(null);
const view = ref("overview");
const logs = ref([]);
const board = ref({ pending: [], labeled: [], rejections: [] });
const doc = ref(null);
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const labelString = ref("");
const labelQr = ref("");
const error = ref("");
const labelError = ref("");
const labelOk = ref("");
const loading = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");
function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmt(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}
async function refresh() {
  if (!session.value) return;
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
  const b = await fetch("/api/labels/board", { headers: headers() });
  if (b.ok) board.value = await b.json();
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
    await refresh();
    timer = setInterval(refresh, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  board.value = { pending: [], labeled: [], rejections: [] };
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
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
async function stick() {
  labelError.value = "";
  labelOk.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ string_code: labelString.value, qr_code: labelQr.value }),
    });
    const data = await res.json();
    if (!res.ok) { labelError.value = data.detail || "贴码失败"; return; }
    labelOk.value = `已贴：${data.string_code} → ${data.qr_code}`;
    labelString.value = labelQr.value = "";
    await refresh();
  } catch { labelError.value = "贴码时网络异常"; }
  finally { loading.value = false; }
}
async function openDoc(id) {
  const res = await fetch(`/api/logs/${id}`, { headers: headers() });
  if (res.ok) doc.value = await res.json();
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refresh();
      timer = setInterval(refresh, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem; }
main.wide { max-width: none; }
h1 { color: #86efac; margin: 0 0 0.25rem; }
h2 { color: #86efac; font-size: 1.05rem; margin: 0 0 0.75rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button.secondary { background: #365314; }
.err { color: #fecaca; }
.okmsg { color: #86efac; }
.hint { color: #a7f3d0; font-size: 0.85rem; }
.topbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 0.6rem 1rem; margin-bottom: 1rem; }
.topbar nav { display: flex; gap: 0.4rem; }
.topbar button { margin-right: 0; }
.topbar button.active { outline: 2px solid #86efac; }
.who { color: #a7f3d0; font-size: 0.85rem; white-space: nowrap; }
.bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; }
.bar h2 { margin: 0; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
tr.clickable { cursor: pointer; }
tr.clickable:hover td { background: #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
.labels-page { display: flex; flex-direction: column; min-height: calc(100vh - 12rem); }
.panes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; flex: 1; align-items: stretch; }
.pane { margin-bottom: 0; min-height: 16rem; }
.pane ul { list-style: none; margin: 0; padding: 0; }
.pane li { padding: 0.45rem 0; border-bottom: 1px solid #166534; font-size: 0.9rem; }
.pane li small { display: block; color: #a7f3d0; }
.empty { color: #a7f3d0; font-style: italic; }
.mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; }
.doc { width: 26rem; max-width: 90vw; }
.doc dl { display: grid; grid-template-columns: 6rem 1fr; row-gap: 0.4rem; margin: 0 0 1rem; }
.doc dt { color: #a7f3d0; }
.doc dd { margin: 0; }
</style>
