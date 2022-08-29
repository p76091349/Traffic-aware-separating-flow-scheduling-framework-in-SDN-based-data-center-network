# Traffic-aware-separating-flow-scheduling-framework-in-SDN-based-data-center-network
## Requirement
```
mininet==2.3.0
python==2.8.2
scipy==1.7.3
seaborn==0.11.2
matplotlib==3.5.1
ryu==4.34
pip=21.2.4
eventlet==0.27.0
Routes==2.4.1
WebOb==1.7.3
paramiko==2.0.0
gevent==20.6.2
lxml==4.5.2
paramiko==2.0.0
ovs==2.13.0
networkx==2.2
```
## Git
```
sudo apt-get update
sudo  apt install git
git clone https://github.com/p76091349/Traffic-aware-separating-flow-scheduling-framework-in-SDN-based-data-center-network.git
```

## Quick start
start mininet
```
cd ~/Traffic-aware-separating-flow-scheduling-framework-in-SDN-based-data-center-network
sudo python fattree.py
```

start controller
```
ryu-manager --observe-links main.py
```

