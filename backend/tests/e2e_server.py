import tempfile
import time
import uvicorn
from PIL import Image, ImageDraw
from collector.db import Store,run
from collector.api import create_app,passwords
from collector.service import ingest,process_one

root=tempfile.TemporaryDirectory()
store=Store(root.name)
store.init()
with store.tx() as c:
    run(c,'UPDATE settings SET password=:p',p=passwords.hash('local-test-password'))
    run(c,"INSERT INTO sources(external_id,name) VALUES('123','插画分享群')")
for n in range(6):
    ingest(store,{'self_id':9,'group_id':123,'message_id':n,'time':time.time(),'message_type':'group','user_id':42,'message':[{'type':'text','data':{'text':'测试图片 · 山色'}},{'type':'image','data':{'url':str(n)}}]})
def draw(url,path):
    n=int(url)
    colors=['#b2c8a0','#a9bec9','#dbc69e','#9cb6b1','#c9b0a2','#b2b7ce']
    im=Image.new('RGB',(500,640),colors[n])
    d=ImageDraw.Draw(im)
    d.ellipse((300,50,400,150),fill='#f6ead3')
    d.polygon([(0,450),(160,180+n*20),(360,500),(500,340),(500,640),(0,640)],fill='#405f53')
    d.polygon([(0,570),(300,360),(500,560),(500,640),(0,640)],fill='#749183')
    im.save(path,'PNG')
while process_one(store,draw):pass
uvicorn.run(create_app(store),host='127.0.0.1',port=8765,access_log=False)
