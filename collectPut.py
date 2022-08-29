import re
import numpy as np
import time
import os
from pyexcel_ods import save_data
from collections import OrderedDict

data=OrderedDict()
path="server_report"
files=os.listdir(path)
i=0
s=[]
for file in files:
    f=open(path+"/"+file);
    iter_f=iter(f);
    put_list=[]
    print("flie",file)
    for line in iter_f:
        put=re.findall(r".\s+\d+.  0.0-\d+.\d\s+sec\s+\d+.\d+\s+.Bytes\s+(.* \w)bits",line) 
        if len(put)>0:
            print('put=',put[0][:-2])
            if "K" in put[0]:
                a=put[0][:-2]
                a=float(a)/1000
            if "M" in put[0]:
                a=put[0]=put[0][:-2]
            #if float(a) < 200:
            s.append(a)
            #s.append(line)
print(s)
print(len(s))
data.update({"Sheet 1": [s]})
save_data("put.ods",data)
