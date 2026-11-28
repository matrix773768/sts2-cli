"""Rasterize the measured cost and clustered intervals on linear axes."""
from math import floor,ceil
from PIL import Image,ImageDraw,ImageFont

def draw(stats,pairs,path):
    image=Image.new("RGB",(1040,570),"white")
    d=ImageDraw.Draw(image)
    def label(x,y,words,size=18,anchor="la",color="#273744"):
        d.text((x,y),words,font=ImageFont.truetype("segoeui.ttf",size),fill=color,anchor=anchor)
    data=[]
    for arm,s in stats.items():
        u=pairs[arm+"-v2"]["utility"] if arm!="v2" else dict(mean=0,ci=[0,0])
        data.append((arm,s["cost"],u["mean"],*u["ci"]))
    xmin=floor(min(r[1] for r in data)*10-1)/10
    xmax=ceil(max(r[1] for r in data)*10+1)/10
    ymin=floor(min(r[3] for r in data))
    ymax=ceil(max(r[4] for r in data))
    def px(x):return 82+900*(x-xmin)/(xmax-xmin)
    def py(y):return 445-330*(y-ymin)/(ymax-ymin)
    label(52,25,"Cost and terminal utility across 384 paired worlds",31)
    label(53,78,"Mean utility difference vs H5  |  95% family-bootstrap intervals",19)
    for y in range(ymin,ymax+1):
        d.line((82,py(y),982,py(y)),fill="#80919a" if y==0 else "#dbe2e6",width=2 if y==0 else 1)
        label(66,py(y),str(y),17,"rm")
    for i in range(round(xmin*10),round(xmax*10)+1):
        x=px(i/10);d.line((x,445,x,451),fill="#657780")
        label(x,458,f"{i/10:.1f}",17,"ma")
    label(532,507,"End-to-end worker seconds per attempted battle",20,"ma")
    names={"v2":"H5 tactical32","low":"6A low","general":"Selective branches"}
    colors={"v2":"#555963","low":"#287a9c","general":"#b65e23"}
    for arm,cost,mu,lo,hi in data:
        x=px(cost);y=py(mu);color=colors[arm]
        d.line((x,py(lo),x,py(hi)),fill=color,width=4)
        for end in (lo,hi):d.line((x-9,py(end),x+9,py(end)),fill=color,width=3)
        d.ellipse((x-6,y-6,x+6,y+6),fill=color)
        label(x+13,y-28 if arm=="v2" else y-11,names[arm],17,color=color)
    image.save(path)
