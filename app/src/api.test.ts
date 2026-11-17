import {beforeAll,beforeEach,describe,it,expect,vi} from 'vitest';
let api:typeof import('./api');
beforeAll(async()=>{vi.stubGlobal('localStorage',{getItem:()=>null,setItem:()=>{}});api=await import('./api');});
beforeEach(()=>{api.state.token='session';api.state.server='https://example.com';});
describe('连接与会话',()=>{
 it('拒绝明文远程地址、内嵌凭据和无效地址',()=>{expect(api.validServer('http://example.com')).toBe(false);expect(api.validServer('https://user:pass@example.com')).toBe(false);expect(api.validServer('bad')).toBe(false);expect(api.validServer('https://photos.example.com')).toBe(true);});
 it('会话失效时清空令牌并提示重新登录',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'登录已失效'}),{status:401})));await expect(api.api('/images')).rejects.toThrow('登录已失效');expect(api.state.token).toBe('');});
 it('把中文筛选与编辑内容原样传给服务端，不在 URL 暴露令牌',async()=>{const fetcher=vi.fn().mockResolvedValue(new Response('{"ok":true}'));vi.stubGlobal('fetch',fetcher);await api.api('/images/a','PATCH',{note:'中文',tags:['壁纸']});const [url,options]=fetcher.mock.calls[0];expect(url).not.toContain('session');expect(options.headers.Authorization).toBe('Bearer session');expect(JSON.parse(options.body)).toEqual({note:'中文',tags:['壁纸']});});
});
