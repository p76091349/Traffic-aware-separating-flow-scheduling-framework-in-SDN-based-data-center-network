import re
import numpy as np
import time
import os
from pyexcel_ods import save_data
from collections import OrderedDict

data=OrderedDict()
path="mice_flow"
files=os.listdir(path)

s=[]
for file in files:
    f=open(path+"/"+file);
    iter_f=iter(f);
    fct_list=[]
    for line in iter_f:
        fct=re.findall(r"=(.*)s",line)
        if len(fct)>0:
            s.append(float(fct[0]))
            if float(fct[0])>1:
                print(file)
                print(float(fct[0]))
print(s)
print(len(s))
data.update({"Sheet 1": [s]})
save_data("fct.ods",data)
#while True:    
#    with open('CT_h013','r') as f:
#        fct_list=[]
#        row_data = f.readlines()
#        for line in row_data:
#            fct = re.findall(r"-(.*) sec",line)
#            if len(fct) > 0 and fct[0] not in fct_list:
#                fct_list.append(float(fct[0]))
#    print(fct_list)
#    time.sleep(1)
