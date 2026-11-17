<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue';
import {media} from './api';
const props=defineProps<{id:string;large?:boolean}>();
const url=ref(''),error=ref('');let version=0;
async function load(){const current=++version;url.value='';error.value='';try{const result=await media(props.id,!props.large);if(current===version)url.value=result;}catch(e){if(current===version)error.value=(e as Error).message;}}
watch(()=>[props.id,props.large],load,{immediate:true});onUnmounted(()=>version++);
</script>
<template><img v-if="url" :src="url" alt="收集的图片" loading="lazy"><button v-else-if="error" class="image-error" @click.stop="load">{{error}} · 重试</button><span v-else class="placeholder">加载中</span></template>
