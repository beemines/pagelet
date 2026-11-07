<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElDialog, ElForm, ElFormItem, ElInput, ElButton, ElAlert, ElIcon, ElConfigProvider } from 'element-plus'
import { Reading, Message, Lock, Close, ArrowRight, CircleCheckFilled, TopRight } from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

const visible = ref(false), busy = ref(false), success = ref(false)
const message = ref(''), domain = ref(''), formRef = ref(), emailRef = ref(), passwordRef = ref()
const credentials = reactive({ email: '', password: '' })
const registrationUrl = computed(() => {
  try {
    const base = new URL(domain.value)
    if (base.protocol !== 'https:' || base.username || base.password) return ''
    return new URL('/registration', base.origin).href
  } catch { return '' }
})
const rules = {
  email: [{ required: true, message: '请输入账号邮箱', trigger: 'blur' }, { type: 'email', message: '请输入正确的邮箱地址', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
let pollTimer, closeTimer, generation = 0
let attemptId = ''
let closing = false, reopenRequested = false
const token = document.querySelector('meta[name="local-token"]').content

async function request(path, payload) {
  const options = payload === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Local-Token': token }, body: JSON.stringify(payload) }
  let response
  try { response = await fetch('/api/auth/' + path, options) }
  catch { throw new Error('无法连接本机服务，请重新打开网页。') }
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '登录未完成，请重试。')
  return data
}
function hostLabel() {
  try { return new URL(domain.value).hostname }
  catch { return '尚未设置访问域名' }
}
async function open() {
  if (closing) { reopenRequested = true; return }
  if (visible.value) return
  const current = ++generation
  message.value = ''; success.value = false; credentials.password = ''; visible.value = true
  try {
    const state = await request('state')
    if (current !== generation || !visible.value) return
    domain.value = state.domain || ''
    busy.value = ['running', 'cancelling'].includes(state.status)
    attemptId = busy.value ? state.attempt_id || '' : ''
    if (busy.value) schedulePoll(generation)
  } catch (error) { message.value = error.message }
  await nextTick(); emailRef.value?.focus()
}
function schedulePoll(current) {
  clearTimeout(pollTimer)
  pollTimer = setTimeout(() => poll(current), 350)
}
async function poll(current) {
  if (current !== generation || !visible.value) return
  try {
    const state = await request('state')
    if (current !== generation || !visible.value) return
    if (['running', 'cancelling'].includes(state.status)) { schedulePoll(current); return }
    busy.value = false
    if (state.status === 'success') {
      success.value = true
      window.dispatchEvent(new CustomEvent('book-auth-success'))
      closeTimer = setTimeout(() => { closing = true; visible.value = false }, 850)
    } else {
      message.value = state.error || '登录已取消，可以重新输入。'
      await nextTick(); passwordRef.value?.focus()
    }
  } catch (error) { busy.value = false; message.value = error.message }
}
async function submit() {
  if (busy.value || success.value) return
  const opening = generation
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid || opening !== generation || !visible.value || busy.value) return
  message.value = ''; busy.value = true
  const current = ++generation
  attemptId = crypto.randomUUID()
  const password = credentials.password
  credentials.password = ''
  formRef.value?.clearValidate('password')
  try {
    await request('start', { email: credentials.email.trim(), password, attempt_id: attemptId })
    if (current === generation && visible.value) schedulePoll(current)
  } catch (error) { if (current === generation && visible.value) { busy.value = false; message.value = error.message } }
}
async function close() {
  generation++
  clearTimeout(pollTimer); clearTimeout(closeTimer)
  credentials.password = ''
  if (attemptId) {
    try { await request('cancel', { attempt_id: attemptId }) }
    catch (error) { message.value = error.message; return }
  }
  attemptId = ''; busy.value = false; closing = true; visible.value = false
}
function clear() {
  credentials.password = ''; formRef.value?.clearValidate(); message.value = ''; success.value = false; closing = false
  if (reopenRequested) { reopenRequested = false; nextTick(open) }
}
async function settings() {
  await close()
  if (!visible.value) window.dispatchEvent(new CustomEvent('book-open-settings'))
}
onMounted(() => window.addEventListener('book-login-open', open))
onBeforeUnmount(() => { window.removeEventListener('book-login-open', open); clearTimeout(pollTimer); clearTimeout(closeTimer) })
</script>

<template>
  <ElConfigProvider :locale="zhCn">
    <ElDialog v-model="visible" class="auth-dialog" modal-class="auth-overlay" width="430px" align-center append-to-body
      :show-close="false" :close-on-click-modal="false" :close-on-press-escape="false" destroy-on-close @closed="clear">
      <template #header="{ titleId }">
        <div class="auth-heading">
          <button class="auth-close" type="button" aria-label="关闭登录" @click="close"><ElIcon><Close /></ElIcon></button>
          <div class="auth-avatar"><ElIcon><Reading /></ElIcon></div>
          <h2 :id="titleId">登录Pagelet</h2>
          <p>连接你的 Z-Library 书库</p>
        </div>
      </template>
      <div class="auth-content">
        <ElForm ref="formRef" :model="credentials" :rules="rules" label-position="top" hide-required-asterisk @submit.prevent="submit">
          <ElFormItem label="账号邮箱" prop="email">
            <ElInput id="auth-email" ref="emailRef" v-model="credentials.email" :disabled="busy || success" placeholder="请输入邮箱地址" autocomplete="username" :prefix-icon="Message" clearable maxlength="320" />
          </ElFormItem>
          <ElFormItem label="密码" prop="password">
            <ElInput id="auth-password" ref="passwordRef" v-model="credentials.password" :disabled="busy || success" placeholder="请输入密码" type="password" show-password autocomplete="current-password" :prefix-icon="Lock" maxlength="1024" @keydown.enter.prevent="submit" />
          </ElFormItem>
          <ElAlert v-if="message" class="auth-alert" :title="message" type="error" show-icon :closable="false" />
          <ElButton type="primary" native-type="submit" class="auth-submit" :loading="busy" :disabled="success">
            <template v-if="success"><ElIcon><CircleCheckFilled /></ElIcon><span>登录成功</span></template>
            <template v-else><span>{{ busy ? '正在登录…' : '登录' }}</span><ElIcon v-if="!busy"><ArrowRight /></ElIcon></template>
          </ElButton>
        </ElForm>
        <div class="auth-signup">
          <span>还没有账号？</span>
          <a v-if="registrationUrl" :href="busy ? undefined : registrationUrl" target="_blank" rel="noopener noreferrer"
            :aria-disabled="busy" :tabindex="busy ? -1 : 0" title="在新窗口完成注册后，回到这里登录" @click="busy && $event.preventDefault()">
            去注册 <ElIcon><TopRight /></ElIcon>
          </a>
          <ElButton v-else link type="primary" :disabled="busy" @click="settings">先设置访问域名</ElButton>
        </div>
        <div class="auth-privacy"><ElIcon><Lock /></ElIcon><span>密码仅用于登录，不会保存</span></div>
        <div class="auth-connection"><span>{{ hostLabel() }}</span><ElButton link type="primary" :disabled="busy" @click="settings">连接设置</ElButton></div>
      </div>
    </ElDialog>
  </ElConfigProvider>
</template>

<style>
.auth-overlay{background:rgba(25,39,57,.38)!important;backdrop-filter:blur(5px)}
.auth-dialog.el-dialog{padding:0!important;border-radius:20px!important;border:1px solid #ffffffb3;box-shadow:0 24px 100px #152c493d;overflow:hidden;max-width:calc(100vw - 32px);--el-color-primary:#3988f8;--el-border-radius-base:9px;--el-font-family:var(--app-font)}
.auth-dialog .el-dialog__header{padding:0;margin:0}.auth-dialog .el-dialog__body{padding:0}
.auth-heading{position:relative;padding:36px 32px 23px;text-align:center;background:radial-gradient(ellipse at 50% 0,#ddecff 0,transparent 70%),linear-gradient(#f7faff,#fff)}
.auth-close{position:absolute;right:16px;top:16px;width:28px;height:28px;display:grid;place-items:center;border:0;border-radius:50%;background:transparent;color:#98a6b7;font-size:16px;cursor:pointer}
.auth-close:hover{background:#eaf0f9;color:#52647b}.auth-close:focus-visible{outline:2px solid #3988f8;outline-offset:2px}
.auth-avatar{width:70px;height:70px;margin:0 auto 18px;display:grid;place-items:center;border-radius:21px;background:linear-gradient(145deg,#60aaff,#367cf0);color:#fff;font-size:34px;box-shadow:0 8px 20px #3988f833,inset 0 1px 0 #ffffff52}
.auth-heading h2{font:600 25px/1.5 var(--app-font);color:#24364e;margin:0 0 5px;letter-spacing:.4px}
.auth-heading p{margin:0;font-size:12px;color:#94a2b4}
.auth-content{padding:4px 34px 23px}
.auth-dialog .el-form-item{margin-bottom:21px}
.auth-dialog .el-form-item__label{font-size:12px!important;font-weight:600;color:#62728a;line-height:20px;padding:0!important;margin-bottom:7px!important}
.auth-dialog .el-input__wrapper{border-radius:9px;padding:1px 13px;box-shadow:0 0 0 1px #dfe6f0 inset;background:#fff;transition:box-shadow .2s}
.auth-dialog .el-input__wrapper:hover{box-shadow:0 0 0 1px #b9cce6 inset}
.auth-dialog .el-input__wrapper.is-focus{box-shadow:0 0 0 1px #3988f8 inset,0 0 0 3px #3988f812}
.auth-dialog .el-input__inner{border:0!important;border-radius:0;padding:0!important;min-height:44px;box-shadow:none;background:transparent;font-size:13px;color:#33445d}
.auth-dialog .el-input__inner:focus-visible{outline:none}.auth-dialog .el-input__inner::placeholder{color:#b1bdcb}
.auth-dialog .el-input__prefix{margin-right:8px;color:#9aaac0;font-size:16px}.auth-dialog .el-input__suffix{font-size:16px}
.auth-dialog .el-form-item__error{font-size:11px;padding-top:5px}
.auth-dialog .auth-submit.el-button{width:100%;height:45px;border-radius:9px;margin-top:2px;font-size:14px;font-weight:500;border:0;background:linear-gradient(100deg,#4399fc,#367cf0);box-shadow:0 5px 13px #3988f825}
.auth-dialog .auth-submit.el-button:hover{background:linear-gradient(100deg,#388ff1,#2c70e5)}
.auth-dialog .auth-submit.el-button>span{display:flex;align-items:center;justify-content:center;gap:10px}
.auth-dialog .auth-submit.el-button.is-disabled{background:#82adf2;color:white}
.auth-dialog .auth-alert{margin:0 0 16px;border-radius:8px;padding:10px 12px;align-items:flex-start}
.auth-dialog .auth-alert .el-alert__title{font-size:11px;line-height:1.7;word-break:break-word}.auth-dialog .auth-alert .el-alert__icon{margin-top:2px}
.auth-signup{display:flex;align-items:center;justify-content:center;gap:5px;font-size:12px;color:#94a2b4;margin-top:19px}
.auth-signup a{display:inline-flex;align-items:center;gap:3px;color:#3988f8;font-weight:500}
.auth-signup a:hover{text-decoration:underline}.auth-signup a[aria-disabled="true"]{opacity:.5;cursor:default;text-decoration:none;pointer-events:none}
.auth-signup .el-button{font-size:12px;padding:0;height:auto}
.auth-privacy{display:flex;justify-content:center;align-items:center;gap:5px;color:#a2aec0;font-size:10px;margin-top:17px}
.auth-connection{border-top:1px solid #f0f3f7;margin-top:23px;padding-top:14px;display:flex;align-items:center;justify-content:space-between;color:#a1aec0;font-size:10px}
.auth-dialog .auth-connection .el-button{font-size:10px;height:auto;padding:0}
@media(max-width:480px){.auth-heading{padding-top:30px}.auth-content{padding:2px 26px 20px}.auth-avatar{width:62px;height:62px;font-size:30px;border-radius:18px;margin-bottom:15px}.auth-heading h2{font-size:23px}}
@media(prefers-reduced-motion:reduce){.auth-dialog *,.auth-overlay{transition:none!important;animation:none!important}}
</style>
