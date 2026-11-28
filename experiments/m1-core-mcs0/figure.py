"""Raster figures in the same Pillow workflow used by CORE-6B.2."""
from math import log10
from PIL import Image,ImageDraw,ImageFont
from freeze import E,read

def main():
    data=read(E/"results.json")
    rows=list(data["rows"].values())
    image=Image.new("RGB",(1320,760),"white")
    d=ImageDraw.Draw(image)
    def label(x,y,t,size=17,anchor="la",color="#263846"):
        font=ImageFont.truetype("segoeui.ttf",size)
        d.text((x,y),str(t),font=font,fill=color,anchor=anchor)
    def panel(x,y,title):
        label(x,y,title,22)
    def bars(x,y,labels,values,maxval,fmt):
        for j,(name,val) in enumerate(zip(labels,values)):
            yy=y+36*j
            label(x,yy,name)
            left=x+108
            d.rectangle((left,yy+4,left+236,yy+20),fill="#edf2f2")
            if val:d.rectangle((left,yy+4,left+236*val/maxval,yy+20),fill="#287b76")
            label(left+242,yy,fmt(val))
    label(40,20,"CORE-MCS-0   |   Public turn search on 64 synthetic roots",30)
    panel(40,90,"Exact solutions by query budget")
    bars(40,140,["32","128","512"],data["solved"],64,lambda v:f"{v}/64")
    panel(483,90,"Verified history classes")
    exact=[r for r in rows if r["exact"] is not None]
    vals=[sum(r["summary"]["histories"] for r in exact),sum(r["compression"]["classes"] for r in exact)]
    bars(483,140,["S0 histories","S1 classes"],vals,max(vals),str)
    panel(920,90,"Median histories observed")
    groups=data["groups"]
    for j,k in enumerate(["none","draw","multi_enemy","energy","X","cost_layer"]):
        yy=136+30*j
        v=groups[k]["histories"]["median"]
        label(920,yy,k)
        d.rectangle((1035,yy+3,1035+v/400*160,yy+18),fill="#687f9c")
        label(1242,yy,f"{v:g}",anchor="ra")
    panel(40,375,"Adopted-policy regret on 23 exact roots")
    label(40,409,"Points show individual roots. Values below 0.0001 round to zero.",15)
    for j,(key,name) in enumerate([("v2","H5"),("low","6A low"),("general","6B.2 general")]):
        yy=470+52*j
        label(40,yy,name,17,"lm")
        d.line((170,yy,572,yy),fill="#ccd5d8")
        for i,r in enumerate(exact):
            px=170+400*r["arms"][key]["adopted_gap"]/13
            py=yy+((i%7)-3)*3
            d.ellipse((px-3,py-3,px+3,py+3),fill="#854d75")
    for v in (0,3,6,9,12):
        label(170+400*v/13,620,v,15,"ma")
    panel(680,375,"Physical rule executions and elapsed search time")
    x0,y0=756,645
    for power in range(1,6):
        x=x0+(power-1)*115
        d.line((x,443,x,y0),fill="#e2e8e8")
        label(x,y0+7,f"10^{power}",15,"ma")
    for power in range(-2,3):
        y=y0-(power+2)*51
        d.line((x0,y,x0+460,y),fill="#e2e8e8")
        label(x0-8,y,f"{10**power:g}s",15,"rm")
    for r in rows:
        c=r["summary"]
        x=x0+(log10(c["steps"])-1)*115
        y=y0-(log10(c["seconds"])+2)*51
        d.ellipse((x-4,y-4,x+4,y+4),fill="#287b76" if r["exact"] is not None else "#b97149")
    label(980,680,"HotKernel.Step calls (log scale)",16,"ma")
    label(40,713,"Mechanism groups overlap. Censored history counts are lower bounds.   Green dots: exact.   Orange dots: censored.",17)
    image.save(E/"survey.png")
if __name__=="__main__":main()
