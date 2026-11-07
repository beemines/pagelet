<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElDrawer, ElButton, ElAlert, ElSkeleton, ElTag, ElIcon, ElConfigProvider } from 'element-plus'
import { TopRight, Download, Reading } from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

const visible = ref(false), loading = ref(false), downloading = ref(false), coverFailed = ref(false)
const book = ref({}), message = ref(''), downloadError = ref('')
const token = document.querySelector('meta[name="local-token"]').content
let generation = 0, controller
const authors = computed(() => book.value.authors?.join(' / ') || '作者信息未提供')
const metadata = computed(() => [
  ['出版社', book.value.publisher], ['出版年份', book.value.year !== '0' ? book.value.year : ''],
  ['语言', book.value.language], ['页数', book.value.pages], ['版本', book.value.edition],
  ['文件格式', book.value.extension?.toUpperCase()], ['文件大小', book.value.size],
  ['ISBN', book.value.isbn || book.value.isbn_13 || book.value.isbn_10], ['分类', book.value.categories],
].filter(([, value]) => value))
const canDownload = computed(() => /^\d+:[a-z0-9]+$/i.test(book.value.id || ''))
async function request(path, payload, signal) {
  const response = await fetch('/api/' + path, { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', 'X-Local-Token': token }, body: JSON.stringify(payload) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '读取失败，请重试。')
  return data
}
function open(event) {
  controller?.abort(); generation++
  book.value = { ...event.detail }; coverFailed.value = false; downloadError.value = ''; downloading.value = false
  visible.value = true
  load()
}
async function load(force=false) {
  controller?.abort(); controller = new AbortController()
  const current = ++generation
  const cache=window.BookCache,scope=cache?.scope()
  const cached=!force&&cache?.get('details',book.value.id,scope)
  if(cached){book.value=cache.mergeDetails(book.value,cached);message.value='';loading.value=false;return}
  loading.value = true; message.value = ''
  try {
    const details = await request('book/details', { book_id: book.value.id }, controller.signal)
    if (current === generation && visible.value && scope===cache?.scope()) {
      book.value = cache.mergeDetails(book.value,details)
      cache?.put('details',book.value.id,book.value,86400000,scope)
    }
  } catch (error) {
    if (current === generation && visible.value && error.name !== 'AbortError') {
      message.value = error instanceof TypeError ? '无法连接本地服务，请刷新页面后重试。' : error.message
    }
  } finally { if (current === generation) loading.value = false }
}
function close() { generation++; controller?.abort(); loading.value = false }
function scopeChanged(){visible.value=false;close();book.value={};message.value=''}
async function download() {
  const current = generation
  downloading.value = true; downloadError.value = ''
  try {
    await request('download', { book_id: book.value.id, title: book.value.name })
    window.dispatchEvent(new CustomEvent('book-download-added'))
    if (current === generation && visible.value) visible.value = false
  } catch (error) {
    if (current === generation && visible.value) downloadError.value = error instanceof TypeError ? '无法连接本地服务，请重试。' : error.message
  } finally { if (current === generation) downloading.value = false }
}
onMounted(() => {window.addEventListener('book-details-open', open);window.addEventListener('book-cache-scope-changed',scopeChanged)})
onBeforeUnmount(() => { window.removeEventListener('book-details-open', open);window.removeEventListener('book-cache-scope-changed',scopeChanged); close() })
</script>

<template>
  <ElConfigProvider :locale="zhCn">
    <ElDrawer v-model="visible" title="图书详情" class="book-details" modal-class="book-details-overlay" size="600px" append-to-body destroy-on-close @close="close">
      <div class="detail-hero">
        <div class="detail-cover">
          <img v-if="book.cover && !coverFailed" :src="book.cover" :alt="`${book.name}封面`" referrerpolicy="no-referrer" @error="coverFailed = true" />
          <div v-else class="detail-cover-empty"><ElIcon><Reading /></ElIcon><span>{{ coverFailed ? '封面未能加载' : '暂无封面' }}</span></div>
        </div>
        <div class="detail-heading">
          <ElTag v-if="book.extension" size="small" effect="light">{{ book.extension.toUpperCase() }}</ElTag>
          <h2>{{ book.name || '未命名图书' }}</h2>
          <p>{{ authors }}</p>
          <span v-if="book.publisher || book.year" class="detail-edition">{{ [book.publisher, book.year !== '0' ? book.year : ''].filter(Boolean).join(' · ') }}</span>
        </div>
      </div>
      <section class="detail-section">
        <h3>内容简介</h3>
        <ElSkeleton v-if="loading && !book.description" animated :rows="5" class="detail-loading" aria-label="正在加载图书简介" />
        <div v-if="message" class="detail-error">
          <ElAlert :title="message" type="warning" show-icon :closable="false" />
          <ElButton link type="primary" :disabled="downloading" @click="load(true)">重新加载</ElButton>
        </div>
        <p v-if="book.description" class="detail-description">{{ book.description }}</p>
        <p v-else-if="!loading && !message" class="detail-missing">书库暂未提供这本书的简介，可结合下方版本信息判断，或打开原站查看。</p>
        <p v-if="loading && book.description" class="detail-refreshing" role="status">正在更新简介…</p>
      </section>
      <section class="detail-section detail-bibliography">
        <h3>版本信息</h3>
        <dl v-if="metadata.length" class="detail-metadata">
          <div v-for="[label, value] in metadata" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
        </dl>
        <p v-else class="detail-missing">书库暂未提供更多版本信息。</p>
      </section>
      <template #footer>
        <ElAlert v-if="downloadError" :title="downloadError" type="error" :closable="false" class="detail-download-error" />
        <div class="detail-footer">
          <a v-if="book.url" :href="book.url" target="_blank" rel="noopener noreferrer">原站详情 <ElIcon><TopRight /></ElIcon></a>
          <span v-else></span>
          <ElButton type="primary" :icon="Download" :disabled="!canDownload" :loading="downloading" @click="download">下载此版本</ElButton>
        </div>
      </template>
    </ElDrawer>
  </ElConfigProvider>
</template>

<style>
.book-details-overlay{background:#1d34594d!important;backdrop-filter:blur(2px)}
.book-details.el-drawer{max-width:100vw;--el-color-primary:#3988f8;--el-text-color-primary:#26374f;--el-font-family:var(--app-font)}
.book-details .el-drawer__header{padding:24px 30px 20px!important;margin:0!important;border-bottom:1px solid #edf1f7}
.book-details .el-drawer__title{font-size:14px;font-weight:600;color:#526781}
.book-details .el-drawer__close-btn{font-size:19px;color:#8e9fb5}
.book-details .el-drawer__body{padding:28px 30px 32px}
.detail-hero{display:flex;align-items:flex-start;gap:24px}
.detail-cover{width:124px;height:176px;flex:0 0 124px;border:1px solid #e6edf5;border-radius:6px;background:#f3f7fc;overflow:hidden;box-shadow:0 5px 15px #29426914}
.detail-cover img{width:100%;height:100%;object-fit:contain}
.detail-cover-empty{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;color:#9eafc5;font-size:11px}
.detail-cover-empty .el-icon{font-size:30px;color:#b8c9df}
.detail-heading{min-width:0;padding-top:2px}.detail-heading h2{font-size:21px;line-height:1.6;font-weight:600;overflow-wrap:anywhere;margin:10px 0 8px;color:#26374f}
.detail-heading p{font-size:13px;color:#6b7e98;line-height:1.8;margin:0 0 12px;overflow-wrap:anywhere}
.detail-heading .el-tag{--el-tag-bg-color:#edf5ff;--el-tag-border-color:#e2eeff;--el-tag-text-color:#548edc;font-size:10px;height:21px}
.detail-edition{font-size:11px;line-height:1.8;color:#95a4b8;overflow-wrap:anywhere}
.detail-section{margin-top:32px}.detail-section h3{margin:0 0 16px;font-size:13px;font-weight:600;color:#455b78}
.detail-description{white-space:pre-wrap;font-size:13px;line-height:2;color:#62748d;overflow-wrap:anywhere;margin:0}
.detail-refreshing{font-size:11px;color:var(--muted);margin:12px 0 0}.detail-error+.detail-description{margin-top:16px}
.detail-missing{font-size:12px;line-height:1.9;color:#97a5b8;background:#f7faff;border:1px dashed #e5ecf6;border-radius:6px;padding:14px 16px;margin:0}
.detail-loading .el-skeleton__item{height:12px;background:#edf3fb}.detail-error .el-alert{align-items:flex-start;padding:11px 13px;border-radius:6px}.detail-error .el-alert__title{font-size:12px;line-height:1.8}.detail-error>.el-button{font-size:12px;margin-top:12px}
.detail-bibliography{padding-top:24px;border-top:1px solid #edf1f7}.detail-metadata{margin:0;display:grid;grid-template-columns:1fr 1fr;gap:17px 22px}
.detail-metadata>div{min-width:0}.detail-metadata dt{font-size:11px;color:#98a6b9;margin-bottom:6px}.detail-metadata dd{font-size:12px;color:#596d88;margin:0;line-height:1.7;overflow-wrap:anywhere}
.book-details .el-drawer__footer{padding:16px 30px 20px;border-top:1px solid #edf1f7;background:#fff}
.detail-footer{display:flex;align-items:center;justify-content:space-between;gap:16px}.detail-footer>a{font-size:12px;color:#6c92c5;display:flex;align-items:center;gap:5px}.detail-footer>a:hover{color:#3988f8;text-decoration:underline}
.detail-footer .el-button{height:37px;border-radius:6px;font-size:12px;padding:0 20px}.detail-download-error{margin-bottom:12px;text-align:left}
@media(max-width:480px){.book-details .el-drawer__header{padding:20px!important}.book-details .el-drawer__body{padding:24px 20px}.detail-hero{gap:18px}.detail-cover{width:98px;height:140px;flex-basis:98px}.detail-heading h2{font-size:18px;margin-top:7px}.detail-heading p{font-size:12px}.detail-section{margin-top:26px}.book-details .el-drawer__footer{padding:14px 20px 18px}.detail-metadata{gap:16px}.detail-description{font-size:12px}}
@media(prefers-reduced-motion:reduce){.book-details *{animation:none!important;transition:none!important}}
</style>
