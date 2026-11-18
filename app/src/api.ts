import {reactive} from 'vue';
import {Capacitor,registerPlugin} from '@capacitor/core';
export const state=reactive({server:localStorage.getItem('server')||'',token:'',cacheEpoch:0,cacheBytes:0,cacheLimit:Number(localStorage.getItem('cacheLimit'))||200*1024*1024});
const cache=new Map<string,{url:string,size:number}>();
export function clearCache(){state.cacheEpoch++;for(const x of cache.values())URL.revokeObjectURL(x.url);cache.clear();state.cacheBytes=0;}
export function validServer(value:string){try{const u=new URL(value);return !u.username&&!u.password&&!u.search&&!u.hash&&(u.protocol==='https:'||(!Capacitor.isNativePlatform()&&['localhost','127.0.0.1'].includes(u.hostname)&&u.protocol==='http:'));}catch{return false;}}
export async function api(path:string,method='GET',body?:unknown):Promise<any>{
 const response=await fetch(state.server.replace(/\/$/,'')+'/api'+path,{method,headers:{Authorization:'Bearer '+state.token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(30000)});
 if(response.status===401){state.token='';clearCache();}
 if(!response.ok){let message='请求失败';try{const error=await response.json();message=typeof error.detail==='string'?error.detail:'输入内容不符合要求';}catch{}throw new Error(message);}
 return response.status===204?null:response.json();
}
export async function media(id:string,thumbnail=true){
 const epoch=state.cacheEpoch;
 const key=id+':'+thumbnail;
 if(cache.has(key)){const item=cache.get(key)!;cache.delete(key);cache.set(key,item);return item.url;}
 const response=await fetch(state.server+'/api/images/'+id+'/file?thumbnail='+thumbnail,{headers:{Authorization:'Bearer '+state.token},signal:AbortSignal.timeout(30000)});
 if(!response.ok){if(response.status===401){state.token='';clearCache();}throw new Error(response.status===404?'图片已过期':'图片加载失败');}
 const blob=await response.blob();
 if(epoch!==state.cacheEpoch)throw new Error('缓存已更新，请重试');
 if(cache.has(key))return cache.get(key)!.url;
 while(state.cacheBytes+blob.size>state.cacheLimit&&cache.size){const oldest=cache.keys().next().value!;const item=cache.get(oldest)!;URL.revokeObjectURL(item.url);state.cacheBytes-=item.size;cache.delete(oldest);}
 if(blob.size>state.cacheLimit)throw new Error('图片超过手机缓存上限，请调整设置');
 const url=URL.createObjectURL(blob);cache.set(key,{url,size:blob.size});state.cacheBytes+=blob.size;return url;
}
export const NativeGallery=registerPlugin<{save(options:{data:string,name:string,mime:string,share:boolean}):Promise<void>}>('NativeGallery');
export async function exportImage(id:string,format:string,share=false){
 if(!Capacitor.isNativePlatform())throw new Error('保存到相册和分享请在 Android App 中使用');
 const blob=await (await fetch(await media(id,false))).blob();
 const data=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});
 await NativeGallery.save({data,name:'shitu-'+id.slice(0,12)+'.'+format.toLowerCase(),mime:blob.type,share});
}
