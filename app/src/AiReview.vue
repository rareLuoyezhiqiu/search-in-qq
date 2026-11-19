<script setup lang="ts">
import {onMounted,onUnmounted,reactive,ref} from 'vue';
import {api} from './api';
import Media from './Media.vue';

interface Item {
 image_id:string;
 status:string;
 decision:'keep'|'delete'|'uncertain'|null;
 reason:string;
}
interface Batch {
 started:number;
 counts:Record<string,number>;
 items:Item[];
}
interface ReviewStatus {
 enabled:number;
 daily_time:string;
 prompt:string;
 auto_favorite:number;
 key_configured:boolean;
 next_run:number|null;
 scheduled:Batch|null;
 preview:Batch|null;
}

const report=ref<ReviewStatus|null>(null);
const draft=reactive({enabled:false,daily_time:'23:30',prompt:'',auto_favorite:false});
const busy=ref(false),error=ref(''),notice=ref('');
const labels:Record<string,string>={
 pending:'待处理',running:'识别中',kept:'已保留',deleted:'已删除',protected:'收藏保护',
 uncertain:'待确认',failed:'失败',skipped:'已跳过',previewed:'已识别',
};
const decisions={keep:'建议保留',delete:'建议删除',uncertain:'待确认'};
const beijingTime=new Intl.DateTimeFormat('zh-CN',{
 timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23',
});
const time=(seconds:number)=>beijingTime.format(seconds*1000);
const active=(batch:Batch|null)=>Boolean(batch&&(batch.counts.pending||batch.counts.running));

function applySettings(data:ReviewStatus){
 report.value=data;
 Object.assign(draft,{
  enabled:!!data.enabled,daily_time:data.daily_time,prompt:data.prompt,auto_favorite:!!data.auto_favorite,
 });
}
async function perform(fn:()=>Promise<void>){
 busy.value=true;
 error.value='';
 notice.value='';
 try{await fn();}
 catch(e){error.value=(e as Error).message;}
 finally{busy.value=false;}
}
async function save(){
 await perform(async()=>{
  applySettings(await api('/ai-review','PUT',draft));
  notice.value='识别设置已保存';
 });
}
async function refresh(){
 await perform(async()=>{report.value=await api('/ai-review');});
}
async function preview(){
 await perform(async()=>{
  report.value=await api('/ai-review/preview','POST',{prompt:draft.prompt});
  notice.value='试跑已提交';
 });
}
let poll:ReturnType<typeof setInterval>;
onMounted(()=>{
 void perform(async()=>applySettings(await api('/ai-review')));
 poll=setInterval(()=>{
  if(!busy.value&&report.value&&(active(report.value.preview)||active(report.value.scheduled))){
   void api('/ai-review').then(data=>{if(!busy.value)report.value=data;}).catch(()=>{});
  }
 },5000);
});
onUnmounted(()=>clearInterval(poll));
</script>

<template>
 <div class="storage ai-review">
  <h2>定时图片识别</h2>
  <p v-if="error" role="alert" class="error">{{error}}</p>
  <p v-if="notice" aria-live="polite">{{notice}}</p>
  <button v-if="!report && !busy" @click="perform(async()=>applySettings(await api('/ai-review')))">重新加载</button>
  <template v-if="report">
   <form @submit.prevent="save">
    <p v-if="!report.key_configured">服务器尚未配置 DeepSeek API Key。时间和规则可以先保存。</p>
    <label class="check"><input type="checkbox" v-model="draft.enabled" :disabled="!report.key_configured&&!draft.enabled">启用定时识别和自动删除</label>
    <label>每日识别时间（北京时间）<input type="time" v-model="draft.daily_time" required></label>
    <label>图片保留规则<textarea v-model="draft.prompt" maxlength="4000" rows="4" placeholder="例如：保留指定角色的同人插画，排除纯聊天截图，无法判断的先留下"></textarea></label>
    <label class="check"><input type="checkbox" v-model="draft.auto_favorite">将符合规则的图片自动收藏</label>
    <p>缩略图会发给 DeepSeek。明确不符合的未收藏图片会永久删除，待确认和识别失败的图片按原期限保留。</p>
    <div class="row">
     <button type="submit" class="primary" :disabled="busy">保存识别设置</button>
     <button type="button" :disabled="busy||!report.key_configured||!draft.prompt.trim()||active(report.preview)" @click="preview">试跑规则</button>
    </div>
   </form>
   <p v-if="report.next_run">下一批：{{time(report.next_run)}}（北京时间）</p>
   <div v-if="report.preview||report.scheduled" class="ai-history">
    <button :disabled="busy" @click="refresh">刷新识别结果</button>
    <div v-if="report.scheduled">
     <h3>最近一次定时识别</h3>
     <p>{{time(report.scheduled.started)}} · {{Object.entries(report.scheduled.counts).map(([state,count])=>labels[state]+' '+count).join(' · ')||'暂无待识别图片'}}</p>
     <ul v-if="report.scheduled.items.some(item=>item.status==='deleted'||item.status==='failed')">
      <li v-for="item in report.scheduled.items.filter(item=>item.status==='deleted'||item.status==='failed')" :key="item.image_id">
       {{labels[item.status]}} · {{item.reason}}
      </li>
     </ul>
    </div>
    <div v-if="report.preview">
     <h3>最近一次试跑</h3>
     <p v-if="!report.preview.items.length">图库没有可试跑的图片。</p>
     <ul v-else class="ai-preview">
      <li v-for="item in report.preview.items" :key="item.image_id">
       <Media v-if="item.status!=='skipped'" :id="item.image_id"/>
       <div><strong>{{item.decision?decisions[item.decision]:labels[item.status]}}</strong><p v-if="item.reason">{{item.reason}}</p></div>
      </li>
     </ul>
    </div>
   </div>
  </template>
 </div>
</template>
