"""Use the remaining measured budget for additional seeds on already assigned open families."""
import json,gzip
from panel5d import E,load,cohort
def augment():
    primary=load(E/"panel.gz")
    extra={}
    for group,seeds in (("train",1),("dev",2)):
        extra[group+"2"]=[w|dict(spec=w["spec"]|dict(seed=cohort.seed(w["family"],"5d-"+group+"-extra",rep)))
            for rep in range(seeds) for w in primary[group]]
    with gzip.open(E/"augmentation.gz","xt") as f:json.dump(extra,f)
if __name__=="__main__":augment()
