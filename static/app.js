'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
let state = {settings:{}, jobs:[], has_session:false};
let currentTab = 'search', lastSearch = null, page = 1, pages = 1, searching = false;
let searchSerial = 0, toastTimer, loginWasOpen = false, stopped = false;
let initialState, shelfSerial=0, stateSerial=0, stateTimer;
const bookCache=window.BookCache, DAY=86400000;
const downloadNodes=new Map();
function syncCacheScope() {
  const scope=JSON.stringify([state.settings.domain||'',state.settings.proxy||'']);
  if(bookCache.scope()!==scope){bookCache.setScope(scope);window.dispatchEvent(new Event('book-cache-scope-changed'));}
}

async function api(path, payload) {
  const options = payload === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Local-Token':token}, body:JSON.stringify(payload)};
  let response;
  try { response = await fetch('/api/' + path, options); }
  catch { throw new Error('本地服务没有响应，请重新双击启动文件。'); }
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || '操作失败，请重试。'); error.code = result.code; throw error; }
  return result;
}
function showToast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 5000); }
function showError(id, message='') { $(id).textContent = message; $(id).hidden = !message; }
function element(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; }
function busy(button, active, message) { if (active) { button.dataset.oldText = button.textContent; button.textContent = message; } else { button.textContent = button.dataset.oldText || button.textContent; } button.disabled = active; }
function switchTab(tab) {
  currentTab = tab; $('search-view').hidden = tab !== 'search'; $('downloads-view').hidden = tab !== 'downloads';
  $('nav-search').classList.toggle('active', tab === 'search'); $('nav-downloads').classList.toggle('active', tab === 'downloads');
  $('nav-search').setAttribute('aria-current', tab === 'search' ? 'page' : 'false');
  $('nav-downloads').setAttribute('aria-current', tab === 'downloads' ? 'page' : 'false');
}
async function refreshState(quiet=false) {
  const serial=++stateSerial;
  try {
    const next=await api('state'); if(serial!==stateSerial)return;
    state = next; syncCacheScope(); renderJobs();
    $('setup-notice').hidden = state.has_session;
    $('setup-notice').querySelector('span').textContent=state.settings.domain?'首次使用：登录账号后即可搜索和下载。':'首次使用：先设置访问域名，再登录账号。';
    $('setup-button').textContent=state.settings.domain?'登录账号':'去设置';
    if (loginWasOpen && !state.login_open) { showToast('登录窗口已关闭，正在检查账号…'); refreshProfile(); }
    loginWasOpen = state.login_open;
  } catch(error) { if (!quiet) showToast(error.message); }
}
async function refreshProfile() {
  const button = $('refresh-profile'); button.disabled = true;
  try {
    const profile = await api('profile', {});
    $('account-status').textContent = profile.quota_known ? `今日剩余 ${profile.daily_remaining}` : '已连接';
    $('account-status').title = profile.name || '账号已连接'; $('login-button').textContent = '切换账号';
    $('setup-notice').hidden = true;
  } catch(error) { $('account-status').textContent = error.code === 'login_required' ? '未登录' : '连接失败'; showToast(error.message); }
  finally { button.disabled = false; }
}
async function search(targetPage=1) {
  if (searching) return;
  await initialState;
  if(searching)return;
  const query = $('query').value.trim();
  if (!query) { $('query').focus(); return; }
  const serial = ++searchSerial;
  const criteria = targetPage === 1 ? {query, format:$('format').value, language:$('language').value} : lastSearch;
  if (!criteria) return;
  searching = true; $('featured-section').hidden = true; $('results-section').hidden = false; $('back-home').disabled = true;
  showError('search-error'); busy($('search-button'), true, '正在搜索…');
  $('empty-state').hidden = true; $('book-results').hidden = true; $('pagination').hidden = true; $('loading-state').hidden = false;
  $('results-summary').textContent = '正在查询书库…';
  $('results-section').setAttribute('aria-busy','true');
  $('loading-message').textContent='正在搜索中，请耐心等待…';
  const waiting=setTimeout(()=>{if(serial===searchSerial)$('loading-message').textContent='搜索仍在进行中，请耐心等待，不用重复提交。';},8000);
  const scope=bookCache.scope(), cacheKey=bookCache.searchKey({...criteria,page:targetPage});
  try {
    const cached=bookCache.get('search',cacheKey,scope);
    const result = cached || await api('search', {...criteria, page:targetPage});
    if (serial !== searchSerial) return;
    if(scope!==bookCache.scope())throw new Error('连接设置已更改，请重新搜索。');
    if(!cached)bookCache.put('search',cacheKey,result,600000,scope);
    lastSearch = criteria; page = Number(result.page) || targetPage; pages = Math.max(1, Number(result.total_pages) || 1);
    renderBooks(result.books || []);
    $('results-summary').textContent = `“${criteria.query}” · 本页 ${(result.books || []).length} 本${criteria.format?'':' · PDF 优先'}`;
    $('results-summary').title=cached?'已使用十分钟内的本地缓存':'';
    $('pagination').hidden = !result.books?.length;
    $('page-label').textContent = `第 ${page} / ${pages} 页`; $('prev-page').disabled = page <= 1; $('next-page').disabled = page >= pages;
  } catch(error) {
    showError('search-error', error.message); $('book-results').replaceChildren();
    $('empty-state').hidden = true; $('results-summary').textContent = '搜索未完成';
  } finally { clearTimeout(waiting); searching = false; $('results-section').setAttribute('aria-busy','false'); $('back-home').disabled = false; busy($('search-button'), false); $('loading-state').hidden = true; $('book-results').hidden = false; }
}
async function loadFeatured() {
  const serial=++shelfSerial,scope=bookCache.scope();
  const cached=bookCache.get('featured','home',scope);
  if(cached)renderFeatured(cached);
  try {
    const result=await api('featured');
    if(serial!==shelfSerial||scope!==bookCache.scope())return;
    bookCache.put('featured','home',result,DAY,scope);renderFeatured(result);
  }catch{if(!cached)$('featured-books').replaceChildren(element('p','shelf-status','书架暂时无法加载，可以在上方搜索图书。'));}
}
function renderFeatured(result) {
  const container = $('featured-books');
  container.replaceChildren();
    (result.books || []).forEach(book => {
        const card=element('button','shelf-card'); card.type='button'; card.setAttribute('aria-label',`查看《${book.name}》详情`);
        const cover=element('div','shelf-cover'), image=element('img'); image.src=book.cover; image.alt=`${book.name}封面`; image.decoding='async';
        image.addEventListener('error',()=>{image.remove();cover.append(element('span','cover-placeholder','封面未能加载'));}); cover.append(image);
        const info=element('div','shelf-info'); info.append(element('h3','',book.name));
        const authors=element('p','shelf-author',(book.authors || []).join(' / ')); authors.title=authors.textContent;
        info.append(authors,element('p','shelf-publisher',book.publisher || ''));
        card.append(cover,info); card.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('book-details-open',{detail:book}))); container.append(card);
    });
    if (!container.children.length) container.append(element('p','shelf-status','书架暂时为空，可以在上方搜索图书。'));
}
function showHome() {
  if (searching) return;
  lastSearch=null; page=1; pages=1; $('query').value=''; showError('search-error');
  $('results-section').hidden=true; $('featured-section').hidden=false; $('query').focus();
}
function renderBooks(books) {
  books=[...books].sort((a,b)=>Number((a.extension||'').toLowerCase()!=='pdf')-Number((b.extension||'').toLowerCase()!=='pdf'));
  $('book-results').replaceChildren(); $('empty-state').hidden = books.length > 0;
  if (!books.length) { $('empty-title').textContent = '没有找到图书'; $('empty-description').textContent = '试试缩短关键词，或放宽格式和语言限制。'; $('empty-description').hidden = false; }
  books.forEach(book => {
    const row = element('article','book-row');
    const openDetails = () => window.dispatchEvent(new CustomEvent('book-details-open',{detail:book}));
    const cover = element('button','book-cover'); cover.type='button'; cover.setAttribute('aria-label',`查看《${book.name || '图书'}》详情`);
    cover.append(element('span','cover-placeholder','暂无封面'));
    if(book.cover) {
      const image = element('img'); image.alt = `${book.name || '图书'}封面`; image.loading='lazy'; image.decoding='async'; image.referrerPolicy='no-referrer';
      image.addEventListener('load',()=>cover.classList.add('has-cover'));
      image.addEventListener('error',()=>{image.remove();cover.classList.remove('has-cover');cover.querySelector('span').textContent='封面未能加载';});
      image.src=book.cover; cover.append(image);
    }
    cover.addEventListener('click',openDetails);
    const info = element('div','book-info'), heading=element('h3'), title=element('button','book-title',book.name || '未命名图书');
    title.type='button'; title.addEventListener('click',openDetails); heading.append(title); info.append(heading);
    const authors = Array.isArray(book.authors) ? book.authors.join(' / ') : book.authors || '作者信息未提供';
    info.append(element('p','',authors));
    const meta = element('div','book-meta'); meta.append(element('span','format-tag',(book.extension || '未知格式').toUpperCase()));
    [book.year && book.year !== '0' ? book.year : '', book.language, book.size, book.publisher].filter(Boolean).forEach(text => meta.append(element('span','',text)));
    info.append(meta); const actions=element('div','book-actions'), details=element('button','text-button','查看详情');
    details.type='button'; details.addEventListener('click',openDetails);
    const button = element('button','button','下载'); button.type = 'button';
    button.disabled = !/^\d+:[a-z0-9]+$/i.test(book.id || ''); button.title = button.disabled ? '此条目没有可用的下载编号' : '下载到本机';
    button.addEventListener('click', () => queueDownload(book, button)); actions.append(details,button); row.append(cover,info,actions); $('book-results').append(row);
  });
}
async function queueDownload(book, button) {
  busy(button,true,'加入中…');
  try { await api('download',{book_id:book.id, title:book.name}); showToast('已加入下载队列，可在“下载记录”查看状态。'); await refreshState(); }
  catch(error) { showToast(error.message); }
  finally { busy(button,false); }
}
function renderJobs() {
  const jobs = state.jobs || [], list = $('download-list');
  const active = jobs.filter(j => ['running','queued','cancelling'].includes(j.status)).length;
  $('job-count').textContent = active || jobs.length; $('download-total').textContent = jobs.length; $('downloads-empty').hidden = jobs.length > 0;
  $('job-count').hidden = jobs.length === 0;
  jobs.forEach((job,index) => {
    let parts=downloadNodes.get(job.id);
    if(!parts){
      const row=element('article','download-row'),info=element('div','download-info'),title=element('h3'),date=element('p'),label=element('p','download-progress-label');
      const track=element('div','download-progress'),fill=element('span','download-progress-fill');track.append(fill);track.setAttribute('role','progressbar');track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');
      const path=element('p','download-path'),error=element('p','download-error'),retry=element('button','text-button retry-button','重新下载 →');
      retry.type='button';retry.addEventListener('click',()=>queueDownload({id:job.book_id,name:job.title},retry));
      const icon=element('div','download-file-icon');icon.setAttribute('aria-hidden','true');icon.append(fileIcon());
      const actions=element('div','download-actions'),menu=element('details','download-menu'),summary=element('summary','download-icon-button','⋮'),popup=element('div','download-menu-popup');
      summary.setAttribute('aria-label','更多操作');summary.title='更多操作';const deleteFile=element('button','download-menu-item danger','删除文件');deleteFile.type='button';deleteFile.title='移到回收站';
      popup.append(deleteFile);menu.append(summary,popup);const dismiss=element('button','download-icon-button download-dismiss','×');dismiss.type='button';
      actions.append(menu,dismiss);info.append(title,date,label,track,path,error,retry);row.append(icon,info,actions);
      parts={row,title,date,label,track,fill,path,error,retry,menu,deleteFile,dismiss,icon,pending:false,job};
      dismiss.addEventListener('click',()=>dismissDownload(parts));deleteFile.addEventListener('click',()=>deleteDownloadFile(parts));downloadNodes.set(job.id,parts);
    }
    parts.job=job;
    const {row,title,date,label,track,fill,path,error,retry,menu,deleteFile,dismiss,icon}=parts;
    const active=['queued','running','cancelling'].includes(job.status);
    title.textContent=job.title;date.textContent=new Date(job.created_at).toLocaleString('zh-CN');
    path.textContent=job.path||'';path.hidden=!job.path;path.classList.toggle('is-deleted',!!job.file_deleted);icon.classList.toggle('is-deleted',!!job.file_deleted);
    error.textContent=job.error||'';error.hidden=!job.error;retry.hidden=!['failed','cancelled'].includes(job.status);
    track.hidden=!active;
    dismiss.disabled=parts.pending||job.status==='cancelling';dismiss.title=active?'终止下载':'移除下载记录';dismiss.setAttribute('aria-label',dismiss.title+'：'+job.title);
    menu.hidden=job.status!=='completed'||!job.path||!!job.file_deleted;deleteFile.disabled=parts.pending;
    const known=job.status==='completed'||(typeof job.percent==='number'&&Number.isFinite(job.percent)),percent=job.status==='completed'?100:Math.max(0,Math.min(100,job.percent||0));
    track.className='download-progress '+job.status+(!known&&['running','queued'].includes(job.status)?' indeterminate':'');
    track.setAttribute('aria-label',job.title+'下载进度');track.setAttribute('aria-valuetext',downloadLabel(job));
    if(known){track.setAttribute('aria-valuenow',String(percent));fill.style.width=percent+'%';}else{track.removeAttribute('aria-valuenow');fill.style.width='';}
    label.textContent=downloadLabel(job);
    if(list.children[index]!==row)list.insertBefore(row,list.children[index]||null);
  });
  const ids=new Set(jobs.map(job=>job.id));for(const [id,parts] of downloadNodes)if(!ids.has(id)){parts.row.remove();downloadNodes.delete(id);}
}
function formatBytes(value){if(!(value>0))return '0 B';const units=['B','KB','MB','GB'];const index=Math.min(3,Math.floor(Math.log(value)/Math.log(1024)));return (value/1024**index).toFixed(index?1:0)+' '+units[index];}
function downloadLabel(job){
  if(job.file_deleted)return job.file_state==='missing'?'文件已不存在':'文件已移到回收站';
  if(job.status==='cancelled')return '下载已终止';
  if(job.status==='cancelling')return '正在终止下载…';
  if(job.status==='queued')return '等待下载…';
  if(job.status==='completed')return '下载完成'+(job.transferred_bytes?' · '+formatBytes(job.transferred_bytes):'');
  if(job.status==='failed')return '下载失败';
  if(job.phase==='preparing'||!job.phase)return '正在获取下载链接，请稍候…';
  if(job.phase==='connecting')return '正在连接下载服务器…';
  if(job.phase==='finalizing')return '100% · 正在完成保存…';
  if(typeof job.percent==='number')return `${job.percent}% · ${formatBytes(job.transferred_bytes)} / ${formatBytes(job.total_bytes)}`;
  return job.transferred_bytes?'已下载 '+formatBytes(job.transferred_bytes)+' · 总大小未知':'正在下载，请稍候…';
}
function fileIcon(){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linejoin','round');
  const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6');svg.append(path);return svg;
}
async function dismissDownload(parts){
  if(parts.pending)return;
  const job=parts.job,active=['queued','running','cancelling'].includes(job.status);
  parts.pending=true;parts.dismiss.disabled=true;
  try{
    const result=await api('download/'+(active?'cancel':'remove'),{job_id:job.id});stateSerial++;
    if(active)state.jobs=state.jobs.map(item=>item.id===job.id?result:item);else state.jobs=state.jobs.filter(item=>item.id!==job.id);
    renderJobs();if(!active)showToast('已移除下载记录。');await refreshState(true);
  }catch(error){showToast(error.message);}
  finally{parts.pending=false;renderJobs();}
}
async function deleteDownloadFile(parts){
  parts.menu.open=false;
  const job=parts.job;
  if(parts.pending||!confirm('将这个下载文件移到回收站？\n\n'+job.path))return;
  parts.pending=true;parts.deleteFile.disabled=true;parts.dismiss.disabled=true;
  try{
    const result=await api('download/delete-file',{job_id:job.id});stateSerial++;
    state.jobs=state.jobs.map(item=>item.id===job.id?result:item);renderJobs();showToast(result.file_state==='missing'?'文件已不存在。':'文件已移到回收站。');await refreshState(true);
  }catch(error){showToast(error.message);}
  finally{parts.pending=false;renderJobs();}
}
function openSettings() {
  $('domain').value = state.settings.domain || ''; $('proxy').value = state.settings.proxy || ''; $('download-dir').value = state.settings.download_dir || '';
  showError('settings-error'); if (!$('settings-dialog').open) $('settings-dialog').showModal();
}
async function saveSettings(close=true) {
  const result = await api('settings',{domain:$('domain').value,proxy:$('proxy').value,download_dir:$('download-dir').value});
  state.settings = result.settings;
  stateSerial++;syncCacheScope();
  await loadFeatured();
  if(close) { $('settings-dialog').close(); showToast('设置已保存。'); }
}
async function probeDomains() {
  busy($('probe-button'),true,'检测中…'); showError('settings-error'); $('domain-results').replaceChildren();
  try {
    await saveSettings(false);
    const result = await api('doctor', {}), domains = result.domains || [];
    $('domain-options').replaceChildren();
    domains.forEach(item => {
      const url = item.final_url ? new URL(item.final_url).origin : item.domain;
      const option = element('option','',url); option.value=url; $('domain-options').append(option);
      const button = element('button','',url+' ✓'); button.type='button'; button.addEventListener('click',()=>{$('domain').value=url; showToast('已选择域名，点击“保存设置”生效。');}); $('domain-results').append(button);
    });
    if(!domains.length) showError('settings-error','暂时没有可用域名，请检查网络或本地代理设置。');
  } catch(error) { showError('settings-error',error.message); }
  finally { busy($('probe-button'),false); }
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();search(1);});
$('prev-page').addEventListener('click',()=>search(page-1)); $('next-page').addEventListener('click',()=>search(page+1));
$('back-home').addEventListener('click',showHome);
$('nav-search').addEventListener('click',()=>switchTab('search')); $('nav-downloads').addEventListener('click',()=>switchTab('downloads')); $('back-search').addEventListener('click',()=>switchTab('search'));
$('nav-settings').addEventListener('click',openSettings);
$('setup-button').addEventListener('click',()=>state.settings.domain?window.dispatchEvent(new Event('book-login-open')):openSettings());
$('close-settings').addEventListener('click',()=>$('settings-dialog').close());
$('settings-dialog').addEventListener('click',event=>{if(event.target===$('settings-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
$('settings-form').addEventListener('submit',async event=>{event.preventDefault();busy($('save-settings'),true,'保存中…');try{await saveSettings();}catch(error){showError('settings-error',error.message);}finally{busy($('save-settings'),false);}});
$('probe-button').addEventListener('click',probeDomains);
$('refresh-profile').addEventListener('click',refreshProfile);
$('login-button').addEventListener('click',()=>window.dispatchEvent(new CustomEvent('book-login-open')));
window.addEventListener('book-auth-success',()=>{showToast('登录成功');refreshProfile();refreshState(true);});
window.addEventListener('book-open-settings',openSettings);
window.addEventListener('book-download-added',()=>{showToast('已加入下载队列，可在“下载记录”查看状态。');refreshState(true);});
$('open-folder').addEventListener('click',async()=>{try{await api('open-folder',{});}catch(error){showToast(error.message);}});
$('shutdown-button').addEventListener('click',async()=>{if(!confirm('退出本地服务？如有下载任务，请等待完成后再退出。'))return;try{await api('shutdown',{});stopped=true;$('settings-dialog').close();showError('search-error','本地服务已退出。下次使用请重新双击启动文件。');showToast('本地服务已退出。');}catch(error){showToast(error.message);}});
async function pollState(){if(stopped)return;if(document.visibilityState==='visible')await refreshState(true);stateTimer=setTimeout(pollState,(state.jobs||[]).some(job=>['queued','running','cancelling'].includes(job.status))?700:2500);}
initialState=refreshState();initialState.then(()=>{loadFeatured();stateTimer=setTimeout(pollState,1000);});
document.addEventListener('visibilitychange',()=>{if(!stopped&&document.visibilityState==='visible')refreshState(true);});
document.addEventListener('click',event=>{document.querySelectorAll('.download-menu[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false;});});
document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.download-menu[open]').forEach(menu=>{const focused=menu.contains(document.activeElement);menu.open=false;if(focused)menu.querySelector('summary').focus();});});
