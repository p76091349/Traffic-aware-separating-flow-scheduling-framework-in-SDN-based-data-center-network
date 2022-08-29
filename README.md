# Traffic-aware-separating-flow-scheduling-framework-in-SDN-based-data-center-network
## install Mininet and Ryu
update update upgrade
```
sudo apt update
sudo apt upgrade
```
download mininet
```
git clone git://github.com/mininet/mininet
cd mininet
git tag
git checkout 2.3.0
util/install.sh -a
sudo mn
```
![image](https://user-images.githubusercontent.com/97156698/187158696-1ec8159c-3e76-40f3-90a7-ab214cfdcafa.png)

Install Ryu
```
pip install ryu
sudo apt install python-pip
cd ryu
python ./setup.py install
sudo apt-get install python-setuptools
ryu-manager
```
![image](https://user-images.githubusercontent.com/97156698/187159396-dbb4001f-3436-4dd5-a6b5-8078143ab000.png)
install package
```
sudo apt-get install python-eventlet
sudo apt-get install python-routes
sudo apt-get install python-webob
sudo apt-get install python-paramiko
sudo apt-get install python-essential
sudo apt-get install python-gevent

pip install lxml
pip install paramiko
pip install ovs
```

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
choose ct, ut, md scenario

start mininet
```
cd ~/Traffic-aware-separating-flow-scheduling-framework-in-SDN-based-data-center-network
sudo python fattree.py
```
![image](https://user-images.githubusercontent.com/97156698/187156705-0cf82b50-8fe7-4be6-a3c9-0af676bf4389.png)
![image](https://user-images.githubusercontent.com/97156698/187156788-7b25ba17-00b6-44c0-9caf-4e6f1dea25e2.png)


start controller
```
ryu-manager --observe-links main.py
```
![image](https://user-images.githubusercontent.com/97156698/187157251-483f146d-ec5d-4ef4-9172-ff2eaa2f91ed.png)


