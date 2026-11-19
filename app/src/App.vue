<script setup lang="ts">
import {ref,watch,onMounted,onUnmounted} from 'vue';
import {api,ApiError,state,validServer,clearCache,discardImageMedia,exportImage} from './api';
import Media from './Media.vue';
import AiReview from './AiReview.vue';
const confirm=window.confirm.bind(window),localStorage=window.localStorage;
const page=ref('gallery'),password=ref(''),error=ref(''),notice=ref(''),busy=ref(false),images=ref<any[]>([]),sources=ref<any[]>([]),tasks=ref<any[]>([]),settings=ref<any>({}),total=ref(0),selected=ref<any>(null),tags=ref(''),zoom=ref(1);
const query=ref(''),source=ref(''),date=ref(''),favorite=ref(false),tag=ref(''),group=ref(''),name=ref('');let searchVersion=0;
const deleting=ref(false);
const pageSize=40;
async function action(fn:()=>Promise<void>){error.value='';busy.value=true;try{await fn();}catch(e){error.value=(e as Error).message;}finally{busy.value=false;}}
async function login(){await action(async()=>{if(!validServer(state.server))throw new Error('请输入有效的 HTTPS 服务器地址');state.server=state.server.replace(/\/$/,'');const r=await api('/login','POST',{password:password.value});state.token=r.token;password.value='';localStorage.setItem('server',state.server);await refresh();});}
async function load(more=false, count=pageSize){
 if(!state.token)return;
 const current=++searchVersion;
 const offset=more?images.value.length:0;
 const params=new URLSearchParams({q:query.value,tag:tag.value,favorite:String(favorite.value)});
 if(source.value)params.set('source',source.value);
 if(date.value){
  const start=new Date(date.value+'T00:00:00');
  const end=new Date(start);
  end.setDate(end.getDate()+1);
  params.set('start',String(+start/1000));
  params.set('end',String(+end/1000));
 }
 const items=[];
 let result;
 do{
  params.set('offset',String(offset+items.length));
  params.set('limit',String(Math.min(100,count-items.length)));
  result=await api('/images?'+params);
  if(current!==searchVersion||!state.token)return;
  items.push(...result.items);
 }while(result.items.length&&items.length<count&&offset+items.length<result.total);
 images.value=more?[...images.value,...items]:items;
 total.value=result.total;
}
async function refresh(){
 const detail=selected.value;
 let keepImageId:string|undefined;
 if(detail){
  try{
   const latest=await api('/images/'+detail.id);
   if(selected.value===detail){
    detail.sources=latest.sources;
    keepImageId=detail.id;
   }
  }catch(e){
   if(!(e instanceof ApiError) || e.status!==404)throw e;
   if(selected.value===detail){selected.value=null;notice.value=e.message;}
  }
 }
 clearCache(keepImageId);
 [sources.value,tasks.value,settings.value]=await Promise.all([api('/sources'),api('/tasks'),api('/settings')]);
 await load();
}
async function open(id:string){await action(async()=>{selected.value=await api('/images/'+id);tags.value=selected.value.tags.join('，');zoom.value=1;});}
async function deleteImage(image:{id:string;favorite:boolean|number}){
 if(deleting.value)return;
 const warning=image.favorite?'这张图片已收藏。':'';
 if(!confirm(warning+'永久删除这张图片及其全部来源记录？'))return;
 deleting.value=true;
 notice.value='';
 try{
  await action(async()=>{
   await api('/images/'+image.id,'DELETE');
   const count=Math.max(pageSize,images.value.length);
   const remaining=images.value.filter(item=>item.id!==image.id);
   total.value-=images.value.length-remaining.length;
   images.value=remaining;
   if(selected.value?.id===image.id)selected.value=null;
   discardImageMedia(image.id);
   notice.value='图片已删除';
   clearTimeout(timer);
   try{
    await load(false,count);
   }catch(e){
    throw new Error('图片已删除，图库刷新失败：'+(e as Error).message);
   }
  });
 }finally{
  deleting.value=false;
 }
}
async function save(){await action(async()=>{const body={favorite:!!selected.value.favorite,note:selected.value.note,tags:tags.value.split(/[,，]/),confirm_expired:false};try{await api('/images/'+selected.value.id,'PATCH',body);}catch(e){if((e as Error).message.includes('全部来源已过期')&&confirm((e as Error).message)){await api('/images/'+selected.value.id,'PATCH',{...body,confirm_expired:true});selected.value=null;}else throw e;}notice.value='已保存';await load();});}
async function addSource(){await action(async()=>{await api('/sources','POST',{external_id:group.value,name:name.value});group.value='';name.value='';sources.value=await api('/sources');});}
async function logout(){clearTimeout(timer);searchVersion++;await action(async()=>{await api('/session','DELETE');state.token='';clearCache();images.value=[];selected.value=null;});}
async function updateSettings(){if(!confirm('保留天数将按原接收时间重新计算，缩短后部分图片可能立即过期。继续？'))return;await action(async()=>{await api('/settings','PUT',{days:Number(settings.value.days),budget:Math.round(Number(settings.value.budget))});await refresh();notice.value='设置已更新';});}
function size(n:number){return (n/1024/1024).toFixed(1)+' MiB';}
function time(n:number){return n?new Date(n*1000).toLocaleString():'尚未收到';}
function online(){return settings.value.online&&Date.now()/1000-settings.value.heartbeat<120;}
let timer:ReturnType<typeof setTimeout>;watch([query,source,date,favorite,tag],()=>{clearTimeout(timer);timer=setTimeout(()=>action(()=>load()),250);});
watch(()=>state.token,value=>{if(!value){images.value=[];selected.value=null;}});
function onVisibilityChange(){if(!document.hidden&&state.token)action(refresh);}
onMounted(()=>document.addEventListener('visibilitychange',onVisibilityChange));
onUnmounted(()=>document.removeEventListener('visibilitychange',onVisibilityChange));
</script>
<template>
 <main v-if="!state.token" class="login"><div class="brandmark">拾</div><p class="eyebrow">SHITU · 私人图片收藏夹</p><h1>把喜欢的图片<br>好好留下来。</h1><p class="muted">群聊里的灵感，收进自己的图库。</p><form @submit.prevent="login"><label>云端地址<input v-model="state.server" placeholder="https://photos.example.com" required autocomplete="url"></label><label>登录密码<input v-model="password" type="password" placeholder="管理员设置的密码" required autocomplete="current-password"></label><button class="primary" :disabled="busy">{{busy?'正在连接…':'连接我的图库 →'}}</button></form><p v-if="error" role="alert" class="error">{{error}}</p><p class="small muted">单账号私人使用 · 凭据仅保留在本次会话</p></main>
 <div v-else class="shell">
  <header><div class="wordmark">拾图</div><button aria-label="刷新" @click="action(refresh)" :disabled="busy">刷新</button></header>
  <p v-if="error" role="alert" class="error banner">{{error}}</p><p v-if="notice" role="status" class="notice" @click="notice=''">{{notice}} <span>×</span></p>
  <section v-if="page==='gallery'"><div class="title-row"><div><h1>我的图库 <small>{{total}}</small></h1></div><button :class="{active:favorite}" @click="favorite=!favorite">{{favorite?'★ 已收藏':'☆ 收藏'}}</button></div>
   <input class="search" v-model="query" aria-label="搜索图片" placeholder="搜索标签、备注或消息文字">
   <div class="filters"><select v-model="source" aria-label="来源筛选"><option value="">全部来源</option><option v-for="s in sources" :value="s.id">{{s.name}}</option></select><input type="date" v-model="date" aria-label="日期筛选"><input v-model="tag" aria-label="标签筛选" placeholder="标签"><button v-if="source||date||tag||query||favorite" @click="source='';date='';tag='';query='';favorite=false">重置</button></div>
   <p class="hint">普通图片保留 {{settings.days||5}} 天，收藏后长期保留。</p>
   <div v-if="images.length" class="grid">
    <article v-for="i in images" :key="i.id" class="tile">
     <Media :id="i.id"/>
     <span v-if="i.favorite" class="star">★</span>
     <div class="tile-caption">{{i.tags[0]||'未分类'}}<span>{{i.width}} × {{i.height}}</span></div>
     <button type="button" class="tile-open" :aria-label="'查看图片：'+(i.tags[0]||'未分类')" @click="open(i.id)"></button>
     <button type="button" class="tile-delete" aria-label="删除图片" :disabled="deleting" @click="deleteImage(i)">删除</button>
    </article>
   </div>
   <div v-else class="empty"><div>▧</div><h2>{{query||source||date||tag||favorite?'没有符合条件的图片':'等待第一张图片'}}</h2><p>{{sources.length?'启用来源后，收到的新图片会出现在这里。':'先添加一个 QQ 群，开始收集喜欢的图片。'}}</p><button v-if="!sources.length" class="primary" @click="page='sources'">添加收集来源</button></div>
   <button v-if="images.length<total" class="more" @click="action(()=>load(true))" :disabled="busy||deleting">加载更多</button>
  </section>
  <section v-if="page==='sources'"><h1>收集来源</h1><div class="connection"><span :class="['dot',{online:online()}]"></span><strong>{{online()?'QQ 接入在线':'QQ 接入未连接或心跳超时'}}</strong><p>最近心跳：{{time(settings.heartbeat)}}</p><p v-if="Date.now()/1000-settings.worker>120">后台 worker 尚未运行或心跳超时</p></div><form class="source-form" @submit.prevent="addSource"><label>QQ 群号<input v-model="group" inputmode="numeric" pattern="[0-9]+" required placeholder="输入目标群号"></label><label>来源名称<input v-model="name" required maxlength="100" placeholder="例如：插画分享群"></label><button class="primary" :disabled="busy">添加来源</button></form><p class="hint">仅收集接入后的新图片。移除来源会保留已收集内容。</p>
   <article v-for="s in sources" class="source-card"><div><h3>{{s.name}}</h3><p>QQ {{s.external_id}} · {{s.enabled?'收集中':'已暂停'}}</p><small>最近内容：{{time(s.last_event)}}</small></div><div class="row"><button @click="action(async()=>{await api('/sources/'+s.id,'PATCH',{enabled:!s.enabled});sources=await api('/sources');})">{{s.enabled?'暂停':'启用'}}</button><button class="danger" @click="action(async()=>{if(confirm('移除这个来源？已收集的图片会保留。')){await api('/sources/'+s.id,'DELETE');sources=await api('/sources');}})">移除</button></div></article>
   <h2>下载任务 <small>{{tasks.length}}</small></h2><p class="muted" v-if="!tasks.length">没有等待或失败的下载。</p><article class="task" v-for="t in tasks"><div><strong>{{t.name}}</strong><p>{{t.error||({'waiting':'等待下载','running':'正在下载'} as any)[t.state]||t.state}}</p><small>已尝试 {{t.attempts}} 次</small></div><button v-if="t.state!=='running'" @click="action(async()=>{await api('/tasks/'+t.id+'/retry','POST');tasks=await api('/tasks');})">重试</button></article>
  </section>
  <section v-if="page==='settings'"><h1>设置与存储</h1><div class="storage"><span>服务器图片用量</span><h2>{{size(settings.used||0)}} <small>/ {{size(settings.budget||0)}}</small></h2><progress :value="settings.used" :max="settings.budget"></progress><p>收藏 {{size(settings.favorites_bytes||0)}} · 数据库 {{size(settings.database_bytes||0)}}<br>磁盘剩余 {{size(settings.free||0)}}</p><p v-if="settings.budget-settings.used<26214400" class="error">容量不足，新的图片下载将暂停。</p></div><form @submit.prevent="updateSettings"><label>普通图片保留天数<input type="number" min="1" max="365" v-model.number="settings.days" required></label><label>图片容量预算（字节）<input type="number" min="31457280" v-model.number="settings.budget" required></label><button class="primary" :disabled="busy">保存服务器设置</button></form><div class="storage"><h2>手机缓存</h2><p>{{size(state.cacheBytes)}} / {{size(state.cacheLimit)}}</p><label>缓存上限（MiB）<input type="number" min="30" max="1000" :value="state.cacheLimit/1048576" @change="state.cacheLimit=Math.max(30,Math.min(1000,Number(($event.target as HTMLInputElement).value)))*1048576;localStorage.setItem('cacheLimit',String(state.cacheLimit));clearCache()"></label><button @click="clearCache();notice='缓存已清理'">清理缓存</button><p class="hint">缓存保存在内存，退出后释放。主动保存到相册的副本不会被清理。</p></div><AiReview/><button class="danger" :disabled="busy" @click="logout">退出登录</button></section>
  <nav><button :class="{active:page==='gallery'}" @click="page='gallery'">▧ <span>图库</span></button><button :class="{active:page==='sources'}" @click="page='sources';action(refresh)">⊞ <span>来源</span></button><button :class="{active:page==='settings'}" @click="page='settings';action(refresh)">⚙ <span>设置</span></button></nav>
  <div v-if="selected" class="detail" role="dialog" aria-label="图片详情"><div class="detail-top"><button @click="selected=null">← 返回图库</button><span>{{selected.width}} × {{selected.height}}</span></div><p v-if="error" class="error" role="alert">{{error}}</p><div class="viewer"><div :style="{width:zoom*100+'%'}"><Media :id="selected.id" large/></div></div><label class="zoom">缩放<input type="range" min="1" max="4" step="0.1" v-model.number="zoom"></label><div class="row"><button :disabled="images.findIndex(i=>i.id===selected.id)<=0" @click="open(images[images.findIndex(i=>i.id===selected.id)-1].id)">上一张</button><button :disabled="images.findIndex(i=>i.id===selected.id)>=images.length-1" @click="open(images[images.findIndex(i=>i.id===selected.id)+1].id)">下一张</button><button @click="action(async()=>{await exportImage(selected.id,selected.format);notice='已保存到相册';})">保存相册</button><button @click="action(()=>exportImage(selected.id,selected.format,true))">分享</button></div><div class="detail-body"><label class="check"><input type="checkbox" v-model="selected.favorite">收藏，长期保留</label><label>标签<input v-model="tags" placeholder="用逗号分隔，例如：插画，灵感"></label><label>备注<textarea v-model="selected.note" maxlength="5000" placeholder="记下喜欢它的理由"></textarea></label><button class="primary" @click="save" :disabled="busy">保存整理</button><h2>来源记录 <small>{{selected.sources.length}}</small></h2><article class="provenance" v-for="s in selected.sources"><h3>{{s.name}}</h3><p>{{s.body||'（无伴随文字）'}}</p><small>发送者 {{s.sender||'未知'}} · {{time(s.published)}}<br>{{selected.favorite?'收藏后长期保留':'保留至 '+time(s.expires)}}</small></article><button class="danger" :disabled="deleting" @click="deleteImage(selected)">永久删除图片</button></div></div>
 </div>
</template>
